from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from crawler.discover_manifest import (
    DOMParser,
    Element,
    classify_href,
    download_index,
    links_in,
    write_json,
)
from crawler.discover_systems import dom_locator


ROOT = Path(__file__).resolve().parents[1]
LIST_HINTS = (
    "list", "cards", "grid", "entries", "items", "catalog", "directory",
    "index", "relation", "mapping",
)


def discovery_confidence(report: dict) -> float:
    unique_count = report.get("extracted_unique_count", 0)
    occurrence_count = report.get("extracted_link_occurrence_count", 0)
    duplicate_count = report.get("duplicate_count", 0)
    displayed_count = report.get("displayed_count")
    if not report.get("detected_list_container") or unique_count == 0:
        return 0.0
    score = 0.70
    if unique_count >= 10:
        score += 0.20
    elif unique_count >= 2:
        score += 0.10
    if displayed_count is not None and displayed_count == unique_count:
        score += 0.09
    elif displayed_count is not None:
        score -= 0.05
    if occurrence_count:
        score -= min(duplicate_count / occurrence_count, 1.0) * 0.20
    return round(max(0.0, min(score, 0.99)), 2)


def accepted_links(node: Element, index_url: str) -> list[Element]:
    return [
        link
        for link in links_in(node)
        if classify_href(link.attrs.get("href"), index_url)[2] == "accepted" and link.text()
    ]


def locate_system_container(root: Element, index_url: str) -> tuple[Element | None, int | None, str]:
    candidates: list[tuple[Element, int, str]] = []
    for marker in root.descendants():
        if marker.tag not in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            continue
        match = re.search(r"/\s*(\d+)", marker.text())
        if not match:
            continue
        displayed = int(match.group(1))
        node = marker.parent
        while node is not None and node.tag != "root":
            if accepted_links(node, index_url):
                candidates.append((node, displayed, marker.text()))
                break
            node = node.parent
    if candidates:
        node, displayed, label = min(candidates, key=lambda item: len(list(item[0].descendants())))
        return node, displayed, label

    structural = []
    for node in root.descendants():
        attrs = " ".join(str(node.attrs.get(key, "")) for key in ("id", "class")).lower()
        if any(hint in attrs for hint in LIST_HINTS):
            count = len(accepted_links(node, index_url))
            if count:
                structural.append((count, node))
    if structural:
        _count, node = max(structural, key=lambda item: item[0])
        return node, None, node.text()[:80]
    return None, None, ""


def discover_entries_from_html(
    html: str,
    index_url: str,
    system_id: str,
) -> tuple[list[dict], dict]:
    parser = DOMParser()
    parser.feed(html)
    all_links = [item for item in parser.root.descendants() if item.tag == "a" and "href" in item.attrs]
    container, displayed_count, label = locate_system_container(parser.root, index_url)
    report = {
        "system_id": system_id,
        "index_url": index_url,
        "detected_list_container": dom_locator(container) if container else None,
        "container_label": label,
        "displayed_count": displayed_count,
        "extracted_link_occurrence_count": 0,
        "extracted_unique_count": 0,
        "duplicate_count": 0,
        "duplicate_urls": [],
        "duplicate_ids": [],
        "outside_container_count": len(all_links),
        "warnings": [],
        "errors": [],
    }
    if container is None:
        report["errors"].append("could not locate a stable system list container")
        report["errors"].append("no unique entity URLs discovered")
        report["displayed_count_mismatch"] = None
        report["warning_count"] = 0
        report["discovery_confidence"] = 0.0
        return [], report

    container_links = links_in(container)
    report["outside_container_count"] = len(all_links) - len(container_links)
    entries = []
    seen_urls: set[str] = set()
    seen_ids: set[str] = set()
    duplicate_urls: set[str] = set()
    duplicate_ids: set[str] = set()
    occurrence_count = 0
    for link in container_links:
        canonical, slug, reason = classify_href(link.attrs.get("href"), index_url)
        if reason != "accepted" or not link.text():
            continue
        occurrence_count += 1
        if canonical in seen_urls:
            duplicate_urls.add(canonical)
            continue
        if slug in seen_ids:
            duplicate_ids.add(slug)
            continue
        seen_urls.add(canonical)
        seen_ids.add(slug)
        entries.append(
            {
                "id": slug,
                "slug": slug,
                "name_zh": link.text(),
                "url": canonical,
                "source_order": len(entries),
                "source_locator": {
                    "dom_locator": dom_locator(container),
                    "container_label": label,
                    "link_text": link.text(),
                },
            }
        )

    report["extracted_link_occurrence_count"] = occurrence_count
    report["extracted_unique_count"] = len(entries)
    report["duplicate_count"] = occurrence_count - len(entries)
    report["duplicate_urls"] = sorted(duplicate_urls)
    report["duplicate_ids"] = sorted(duplicate_ids)
    if report["duplicate_count"]:
        report["warnings"].append(
            f"{report['duplicate_count']} duplicate link occurrence(s) removed"
        )
    if displayed_count is not None and displayed_count != len(entries):
        report["warnings"].append(
            f"displayed count {displayed_count} does not match unique count {len(entries)}"
        )
    if not entries:
        report["errors"].append("no unique entity URLs discovered")
    report["displayed_count_mismatch"] = (
        displayed_count is not None and displayed_count != len(entries)
    )
    report["warning_count"] = len(report["warnings"])
    report["discovery_confidence"] = discovery_confidence(report)
    return entries, report


def load_system(path: Path, system_id: str) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    systems = data.get("systems")
    if not isinstance(systems, list):
        raise ValueError("system manifest must contain a systems list")
    matches = [item for item in systems if item.get("system_id") == system_id]
    if len(matches) != 1:
        raise ValueError(f"system_id must match exactly one system: {system_id}")
    return matches[0]


def discover_system(
    system: dict,
    timeout: float,
    html: str | None = None,
) -> tuple[dict, dict]:
    index_url = system.get("index_url")
    system_id = system.get("system_id")
    if not isinstance(index_url, str) or not isinstance(system_id, str):
        raise ValueError("system requires system_id and index_url")
    fetched_at = datetime.now(timezone.utc).isoformat()
    if html is None:
        body, status, encoding = download_index(index_url, timeout)
        decoded = body.decode(encoding, errors="replace")
    else:
        body = html.encode("utf-8")
        status = 200
        decoded = html
    entries, report = discover_entries_from_html(decoded, index_url, system_id)
    report["http_status"] = status
    report["html_sha256"] = hashlib.sha256(body).hexdigest()
    report["fetched_at"] = fetched_at
    manifest = {
        "schema_version": 1,
        "source": {
            "site": "tlidb",
            "locale": "cn",
            "index_url": index_url,
            "fetched_at": fetched_at,
            "http_status": status,
            "html_sha256": report["html_sha256"],
        },
        "system_id": system_id,
        "entity_type": system_id,
        "displayed_entry_count": report["displayed_count"],
        "unique_entry_count": len(entries),
        "duplicate_occurrence_count": report["duplicate_count"],
        "discovery_confidence": report["discovery_confidence"],
        "quality": {
            "displayed_entry_count": report["displayed_count"],
            "unique_entry_count": len(entries),
            "duplicate_occurrence_count": report["duplicate_count"],
            "discovery_confidence": report["discovery_confidence"],
            "warnings": list(report["warnings"]),
        },
        "entries": entries,
    }
    return manifest, report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Discover one TLIDB system page manifest")
    parser.add_argument("--system-manifest", required=True, type=Path)
    parser.add_argument("--system-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        manifest_path = args.system_manifest if args.system_manifest.is_absolute() else ROOT / args.system_manifest
        system = load_system(manifest_path, args.system_id)
        if system.get("discovery_status") != "confirmed":
            raise ValueError(f"system is not confirmed: {args.system_id}")
        manifest, report = discover_system(system, args.timeout)
        output = args.output if args.output.is_absolute() else ROOT / args.output
        write_json(output, manifest)
        report_path = args.report or Path(f"data/reports/system-discovery/{args.system_id}-manifest-report.json")
        report_path = report_path if report_path.is_absolute() else ROOT / report_path
        write_json(report_path, report)
        print("System manifest discovery")
        print(f"- system: {args.system_id}")
        print(f"- unique entries: {manifest['unique_entry_count']}")
        print(f"- duplicates: {manifest['duplicate_occurrence_count']}")
        print(f"- warnings: {len(report['warnings'])}")
        print(f"- output: {output.relative_to(ROOT) if output.is_relative_to(ROOT) else output}")
        return 1 if report["errors"] else 0
    except Exception as exc:
        if args.debug:
            traceback.print_exc()
        print(f"System manifest discovery failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
