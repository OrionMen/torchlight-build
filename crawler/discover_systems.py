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
    write_json,
)
from crawler.season_context import DEFAULT_SEASON, SeasonContext


ROOT = Path(__file__).resolve().parents[1]
KNOWN_SYSTEMS = {
    "Hero": ("hero", "英雄", "sources/hero_manifest.json"),
    "Help": ("help", "帮助手册", "sources/help_manifest.json"),
}
CONTEXT_HINTS = ("nav", "menu", "system", "category", "catalog", "directory", "index")
EXCLUDED_SLUGS = {
    "login", "account", "register", "search", "logout", "language", "languages",
    "privacy", "terms", "about", "contact",
}


def dom_locator(node: Element) -> str:
    marker = node.attrs.get("id")
    classes = str(node.attrs.get("class", "")).split()
    suffix = f"#{marker}" if marker else "".join(f".{item}" for item in classes[:2])
    return f"{node.tag}{suffix}"


def system_context(link: Element) -> Element | None:
    node = link.parent
    while node is not None and node.tag != "root":
        attrs = " ".join(
            str(node.attrs.get(key, "")) for key in ("id", "class", "role")
        ).lower()
        if node.tag in {"nav", "header"} or any(hint in attrs for hint in CONTEXT_HINTS):
            return node
        node = node.parent
    return None


def stable_candidate_id(slug: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", slug.lower()).strip("_") or "unknown"
    return f"candidate_{normalized}"


def extract_system_candidates(html: str, page_url: str) -> tuple[list[dict], dict]:
    parser = DOMParser()
    parser.feed(html)
    links = [item for item in parser.root.descendants() if item.tag == "a" and "href" in item.attrs]
    systems = []
    seen_urls: set[str] = set()
    duplicate_urls = 0
    excluded: dict[str, int] = {}
    raw_candidates = 0

    for link in links:
        canonical, slug, reason = classify_href(link.attrs.get("href"), page_url)
        if reason != "accepted":
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        raw_candidates += 1
        name = link.text()
        if not name:
            excluded["without_text"] = excluded.get("without_text", 0) + 1
            continue
        if slug.lower() in EXCLUDED_SLUGS:
            excluded["account_search_or_utility"] = excluded.get("account_search_or_utility", 0) + 1
            continue
        context = system_context(link)
        if context is None and slug not in KNOWN_SYSTEMS:
            excluded["ordinary_content_page"] = excluded.get("ordinary_content_page", 0) + 1
            continue
        if canonical in seen_urls:
            duplicate_urls += 1
            continue
        seen_urls.add(canonical)
        known = KNOWN_SYSTEMS.get(slug)
        system_id = known[0] if known else stable_candidate_id(slug)
        systems.append(
            {
                "system_id": system_id,
                "name_zh": name,
                "index_url": canonical,
                "index_slug": slug,
                "discovery_status": "confirmed" if known else "candidate",
                "classification_status": "confirmed" if known else "needs_review",
                "manifest_path": known[2] if known else f"sources/{system_id}_manifest.json",
                "entry_count": None,
                "entry_count_type": "unique",
                "source_order": len(systems),
                "source_locator": {
                    "page_url": page_url,
                    "dom_locator": dom_locator(context or link),
                    "link_text": name,
                },
            }
        )

    return systems, {
        "raw_candidate_link_count": raw_candidates,
        "duplicate_system_url_count": duplicate_urls,
        "excluded_link_counts_by_reason": excluded,
    }


def existing_manifest_summary(path: str) -> tuple[int | None, str | None]:
    manifest_path = ROOT / path
    if not manifest_path.is_file():
        return None, "existing manifest not found"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = data.get("entries")
    if not isinstance(entries, list):
        return None, "existing manifest has no entries list"
    return len(entries), None


def existing_discovery_summary(system_id: str) -> dict:
    path = ROOT / f"data/reports/manifest-discovery/{system_id}-manifest-report.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "displayed_count": data.get("filtered_count"),
        "extracted_unique_count": data.get("deduplicated_count"),
        "duplicate_count": data.get("duplicate_occurrences", 0),
        "warnings": data.get("warnings", []),
        "errors": data.get("errors", []),
    }


def merge_systems(discovered: list[dict]) -> tuple[list[dict], int, int]:
    merged = []
    by_url: set[str] = set()
    duplicate_ids = 0
    duplicate_urls = 0
    ids: set[str] = set()
    for item in discovered:
        if item["index_url"] in by_url:
            duplicate_urls += 1
            continue
        if item["system_id"] in ids:
            duplicate_ids += 1
            base = stable_candidate_id(item["index_slug"])
            suffix = 2
            candidate_id = base
            while candidate_id in ids:
                candidate_id = f"{base}_{suffix}"
                suffix += 1
            item = {**item, "system_id": candidate_id}
        by_url.add(item["index_url"])
        ids.add(item["system_id"])
        merged.append(item)

    for slug, (system_id, name_zh, manifest_path) in KNOWN_SYSTEMS.items():
        url = f"https://tlidb.com/cn/{slug}"
        existing = next((item for item in merged if item["index_url"] == url), None)
        if existing is None:
            existing = {
                "system_id": system_id,
                "name_zh": name_zh,
                "index_url": url,
                "index_slug": slug,
                "discovery_status": "confirmed",
                "classification_status": "confirmed",
                "manifest_path": manifest_path,
                "entry_count": None,
                "entry_count_type": "unique",
                "source_order": len(merged),
                "source_locator": {
                    "page_url": url,
                    "dom_locator": "existing_manifest",
                    "link_text": name_zh,
                },
            }
            merged.append(existing)
        count, error = existing_manifest_summary(manifest_path)
        existing.update(
            {
                "system_id": system_id,
                "discovery_status": "confirmed",
                "classification_status": "confirmed",
                "manifest_path": manifest_path,
                "entry_count": count,
                "entry_count_type": "unique",
            }
        )
        if error:
            existing["manifest_warning"] = error
    for order, item in enumerate(merged):
        item["source_order"] = order
    return merged, duplicate_ids, duplicate_urls


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Discover TLIDB top-level systems")
    parser.add_argument("--url", action="append", required=True, dest="urls")
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    fetched_at = datetime.now(timezone.utc).isoformat()
    all_systems: list[dict] = []
    statuses = []
    excluded: dict[str, int] = {}
    warnings: list[str] = []
    errors: list[str] = []
    raw_count = 0
    duplicate_urls = 0
    try:
        for url in args.urls:
            try:
                body, status, encoding = download_index(url, args.timeout)
                statuses.append({"url": url, "http_status": status, "html_sha256": hashlib.sha256(body).hexdigest()})
                html = body.decode(encoding, errors="replace")
                systems, local = extract_system_candidates(html, url)
                all_systems.extend(systems)
                raw_count += local["raw_candidate_link_count"]
                duplicate_urls += local["duplicate_system_url_count"]
                for reason, count in local["excluded_link_counts_by_reason"].items():
                    excluded[reason] = excluded.get(reason, 0) + count
            except Exception as exc:
                statuses.append({"url": url, "http_status": getattr(exc, "code", None)})
                errors.append(f"{url}: {exc}")
                if args.debug:
                    traceback.print_exc()

        systems, duplicate_ids, merged_duplicate_urls = merge_systems(all_systems)
        context = SeasonContext(ROOT, args.season)
        for item in systems:
            item["manifest_path"] = str(
                Path("sources/seasons") / args.season / Path(item["manifest_path"]).name
            )
        duplicate_urls += merged_duplicate_urls
        confirmed = sum(item["discovery_status"] == "confirmed" for item in systems)
        candidates = sum(item["discovery_status"] == "candidate" for item in systems)
        manifest = {
            "schema_version": 1,
            "site": "tlidb",
            "locale": "cn",
            "fetched_at": fetched_at,
            "source_urls": args.urls,
            "system_count": len(systems),
            "systems": systems,
        }
        output_arg = args.output or context.system_manifest
        output = output_arg if output_arg.is_absolute() else ROOT / output_arg
        write_json(output, manifest)
        report_systems = []
        for item in systems:
            existing_summary = existing_discovery_summary(item["system_id"])
            report_systems.append({
                "system_id": item["system_id"],
                "name_zh": item["name_zh"],
                "index_url": item["index_url"],
                "status": item["discovery_status"],
                "detected_list_container": item["source_locator"]["dom_locator"],
                "displayed_count": existing_summary.get("displayed_count"),
                "extracted_unique_count": existing_summary.get("extracted_unique_count", item["entry_count"]),
                "duplicate_count": existing_summary.get("duplicate_count", 0),
                "manifest_generated": (ROOT / item["manifest_path"]).is_file(),
                "manifest_path": item["manifest_path"],
                "warnings": existing_summary.get("warnings", []) + ([item["manifest_warning"]] if item.get("manifest_warning") else []),
                "errors": existing_summary.get("errors", []),
            })
        report = {
            "schema_version": 1,
            "source_urls": args.urls,
            "http_statuses": statuses,
            "raw_candidate_link_count": raw_count,
            "filtered_candidate_system_count": len(systems),
            "confirmed_system_count": confirmed,
            "candidate_system_count": candidates,
            "unclassified_link_count": candidates,
            "duplicate_system_url_count": duplicate_urls,
            "duplicate_system_id_count": duplicate_ids,
            "known_existing_manifests": ["sources/hero_manifest.json", "sources/help_manifest.json"],
            "systems": report_systems,
            "excluded_link_counts_by_reason": excluded,
            "warnings": warnings,
            "errors": errors,
        }
        report_path = args.report or context.report_root / "system-discovery-report.json"
        report_path = report_path if report_path.is_absolute() else ROOT / report_path
        write_json(report_path, report)
        print("System discovery")
        print(f"- confirmed: {confirmed}")
        print(f"- candidates: {candidates}")
        print("- manifests generated: 0")
        print(f"- warnings: {len(warnings)}")
        print(f"- output: {output.relative_to(ROOT) if output.is_relative_to(ROOT) else output}")
        return 1 if errors else 0
    except Exception as exc:
        if args.debug:
            traceback.print_exc()
        print(f"System discovery failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
