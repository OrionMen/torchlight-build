from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from crawler.discover_manifest import (
    DOMParser,
    Element,
    USER_AGENT,
    classify_href,
    links_in,
    ssl_context,
    write_json,
)
from crawler.discover_system_manifest import (
    discover_entries_from_html,
    locate_system_container,
)
from crawler.discover_systems import dom_locator, system_context


ROOT = Path(__file__).resolve().parents[1]
CLASSIFICATIONS = (
    "confirmed_directory",
    "relation_index",
    "content_page",
    "navigation_only",
    "empty_or_invalid",
    "needs_review",
)
RELATION_HINTS = ("relation", "source", "drop", "mapping", "location", "来源", "获取")


def download_candidate(url: str, timeout: float) -> tuple[bytes, int, str, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout, context=ssl_context()) as response:
        return (
            response.read(),
            response.status,
            response.headers.get_content_charset() or "utf-8",
            response.geturl(),
        )


def canonical_page_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.path.rstrip("/"), "", ""))


def page_title(root: Element) -> str:
    title = next((item for item in root.descendants() if item.tag == "title"), None)
    return title.text() if title else ""


def repeated_entry_count(container: Element | None, index_url: str) -> int:
    if container is None:
        return 0
    signatures = []
    for node in container.descendants():
        node_links = [
            link
            for link in links_in(node)
            if classify_href(link.attrs.get("href"), index_url)[2] == "accepted" and link.text()
        ]
        if not node_links:
            continue
        classes = ".".join(str(node.attrs.get("class", "")).split())
        signatures.append(f"{node.tag}.{classes}")
    counts = Counter(signatures)
    return max(counts.values(), default=0)


def relation_evidence(container: Element | None, label: str) -> bool:
    if container is None:
        return False
    attrs = " ".join(str(container.attrs.get(key, "")) for key in ("id", "class", "role")).lower()
    text = f"{attrs} {label.lower()}"
    has_hint = any(hint in text for hint in RELATION_HINTS)
    has_table = container.tag == "table" or any(item.tag == "table" for item in container.descendants())
    return has_hint and has_table


def verify_html(
    system: dict,
    html: str,
    http_status: int = 200,
    final_url: str | None = None,
    body: bytes | None = None,
) -> dict:
    index_url = system["index_url"]
    final_url = final_url or index_url
    body = body if body is not None else html.encode("utf-8")
    parser = DOMParser()
    parser.feed(html)
    root = parser.root
    all_links = [item for item in root.descendants() if item.tag == "a" and "href" in item.attrs]
    raw_internal = 0
    external = 0
    static = 0
    navigation = 0
    for link in all_links:
        _canonical, _slug, reason = classify_href(link.attrs.get("href"), index_url)
        if reason == "accepted":
            raw_internal += 1
            if system_context(link) is not None:
                navigation += 1
        elif reason == "external_domain":
            external += 1
        elif reason == "static_resource":
            static += 1

    container, displayed_count, container_label = locate_system_container(root, index_url)
    entries, entry_report = discover_entries_from_html(html, index_url, system["system_id"])
    unique_count = len(entries) if container is not None else 0
    occurrence_count = entry_report.get("extracted_link_occurrence_count", 0) if container is not None else 0
    duplicate_count = entry_report.get("duplicate_count", 0) if container is not None else 0
    repeated_count = repeated_entry_count(container, index_url)
    text = root.text()
    paragraphs = [item for item in root.descendants() if item.tag == "p" and item.text()]
    redirected_elsewhere = canonical_page_url(final_url) != canonical_page_url(index_url)
    warnings = list(entry_report.get("warnings", [])) if container is not None else []
    errors: list[str] = []
    reason_zh = ""

    if http_status != 200 or not text or redirected_elsewhere:
        classification = "empty_or_invalid"
        confidence = 1.0 if http_status != 200 or redirected_elsewhere else 0.95
        reason_zh = "页面无有效内容、HTTP 状态异常或重定向到其他入口。"
        if http_status != 200:
            errors.append(f"HTTP {http_status}")
        if redirected_elsewhere:
            errors.append(f"redirected to unrelated page: {final_url}")
    elif relation_evidence(container, container_label) and unique_count >= 2 and repeated_count >= 2:
        classification = "relation_index"
        confidence = 0.9
        reason_zh = "检测到边界清晰、具有重复行结构的关系索引容器。"
    elif container is not None and unique_count >= 2 and repeated_count >= 2:
        classification = "confirmed_directory"
        confidence = 0.95 if displayed_count is None or displayed_count == unique_count else 0.85
        reason_zh = "检测到边界清晰且具有多个重复条目的目录容器。"
    elif container is not None and unique_count == 1:
        classification = "needs_review"
        confidence = 0.55
        reason_zh = "检测到结构化容器，但只有一个唯一条目。"
    elif raw_internal >= 2 and navigation == raw_internal:
        classification = "navigation_only"
        confidence = 0.9
        reason_zh = "有效站内链接全部位于导航结构中，未发现独立实体列表。"
    elif len(paragraphs) >= 2 and len(text) >= 80 and raw_internal <= 2:
        classification = "content_page"
        confidence = 0.9
        reason_zh = "页面以连续说明正文为主，仅包含少量引用链接。"
    else:
        classification = "needs_review"
        confidence = 0.5
        reason_zh = "页面存在内容或链接，但缺少可稳定确认的目录边界与重复结构。"

    eligible = classification in {"confirmed_directory", "relation_index"}
    recommended_id = system["system_id"]
    if eligible and recommended_id.startswith("candidate_"):
        recommended_id = recommended_id[len("candidate_"):]
    count_matches = None if displayed_count is None else displayed_count == unique_count
    result = {
        "system_id": system["system_id"],
        "name_zh": system.get("name_zh"),
        "index_url": index_url,
        "http_status": http_status,
        "final_url": final_url,
        "page_title": page_title(root),
        "html_sha256": hashlib.sha256(body).hexdigest(),
        "classification": classification,
        "classification_confidence": confidence,
        "detected_list_container": container is not None,
        "container_locator": dom_locator(container) if container else None,
        "raw_internal_link_count": raw_internal,
        "candidate_entry_link_count": occurrence_count,
        "unique_entry_count": unique_count,
        "duplicate_entry_count": duplicate_count,
        "external_link_count": external,
        "static_asset_link_count": static,
        "navigation_link_count": navigation,
        "displayed_entry_count": displayed_count,
        "count_matches": count_matches,
        "manifest_eligible": eligible,
        "recommended_system_id": recommended_id,
        "recommended_entity_type": recommended_id if eligible else None,
        "recommended_manifest_path": f"sources/{recommended_id}_manifest.json" if eligible else None,
        "system_role": "relation_index" if classification == "relation_index" else "entity_directory" if eligible else None,
        "reason_zh": reason_zh,
        "warnings": warnings,
        "errors": errors,
        "_entries": entries if eligible else [],
    }
    return result


def invalid_result(system: dict, exc: Exception) -> dict:
    status = getattr(exc, "code", None)
    result = verify_html(system, "", http_status=status or 0, final_url=system["index_url"])
    result["errors"] = [str(exc)]
    return result


def preview_manifest(result: dict) -> dict:
    return {
        "schema_version": 1,
        "system_id": result["recommended_system_id"],
        "entity_type": result["recommended_entity_type"],
        "preview": True,
        "source": {
            "index_url": result["index_url"],
            "http_status": result["http_status"],
            "html_sha256": result["html_sha256"],
        },
        "displayed_entry_count": result["displayed_entry_count"],
        "unique_entry_count": result["unique_entry_count"],
        "duplicate_occurrence_count": result["duplicate_entry_count"],
        "entries": result["_entries"],
    }


def public_result(result: dict) -> dict:
    return {key: value for key, value in result.items() if not key.startswith("_")}


def backup_path_for_manifest(manifest_path: Path) -> Path:
    """Keep the pre-apply snapshot in the manifest's own namespace."""
    return manifest_path.with_name(
        f"{manifest_path.stem}.before_candidate_verification{manifest_path.suffix}"
    )


def atomic_replace_bytes(path: Path, content: bytes) -> None:
    """Replace *path* atomically using a temporary file in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def apply_results(
    manifest_path: Path,
    manifest: dict,
    results: list[dict],
    backup_path: Path,
    force: bool,
    verified_at: str,
) -> None:
    # A backup is a per-apply diagnostic/rollback snapshot. Refreshing it is
    # intentional: Stage 1 regenerates the manifest before every rebuild, so a
    # stale snapshot must neither block Stage 2 nor represent another run.
    _ = force  # Retained for CLI/API compatibility; backup refresh is always safe.
    atomic_replace_bytes(backup_path, manifest_path.read_bytes())
    by_id = {result["system_id"]: result for result in results}
    for system in manifest["systems"]:
        original_id = system.get("system_id")
        if original_id in {"hero", "help"} or original_id not in by_id:
            continue
        result = by_id[original_id]
        classification = result["classification"]
        system["verification_status"] = "verified" if classification != "needs_review" else "needs_review"
        system["verification_classification"] = classification
        system["verification_confidence"] = result["classification_confidence"]
        system["verified_at"] = verified_at
        system["system_role"] = result["system_role"]
        if classification in {"confirmed_directory", "relation_index"}:
            system["system_id"] = result["recommended_system_id"]
            system["discovery_status"] = "confirmed"
            system["manifest_path"] = result["recommended_manifest_path"]
            system["entry_count"] = result["unique_entry_count"]
        elif classification == "content_page":
            system["discovery_status"] = "content_page"
            system["manifest_path"] = None
            system["entry_count"] = None
        elif classification == "navigation_only":
            system["discovery_status"] = "navigation_only"
            system["manifest_path"] = None
            system["entry_count"] = None
        elif classification == "empty_or_invalid":
            system["discovery_status"] = "invalid"
            system["manifest_path"] = None
            system["entry_count"] = None
        else:
            system["discovery_status"] = "candidate"
    encoded_manifest = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    atomic_replace_bytes(manifest_path, encoded_manifest)


def build_report(results: list[dict], candidate_input_count: int, applied: bool, backup_path: Path | None) -> dict:
    classifications = {name: 0 for name in CLASSIFICATIONS}
    for result in results:
        classifications[result["classification"]] += 1
    return {
        "schema_version": 1,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "candidate_input_count": candidate_input_count,
        "pages_requested": len(results),
        "pages_succeeded": sum(result["http_status"] == 200 for result in results),
        "pages_failed": sum(result["http_status"] != 200 for result in results),
        "detail_pages_requested": 0,
        "confirmed_directory_count": classifications["confirmed_directory"],
        "relation_index_count": classifications["relation_index"],
        "content_page_count": classifications["content_page"],
        "navigation_only_count": classifications["navigation_only"],
        "empty_or_invalid_count": classifications["empty_or_invalid"],
        "needs_review_count": classifications["needs_review"],
        "auto_upgrade_eligible_count": sum(result["manifest_eligible"] for result in results),
        "total_unique_entry_count": sum(result["unique_entry_count"] for result in results),
        "duplicate_entry_count": sum(result["duplicate_entry_count"] for result in results),
        "classifications": classifications,
        "systems": [public_result(result) for result in results],
        "warnings": [f"{result['system_id']}: {warning}" for result in results for warning in result["warnings"]],
        "errors": [f"{result['system_id']}: {error}" for result in results for error in result["errors"]],
        "applied": applied,
        "backup_path": str(backup_path) if backup_path else None,
    }


def render_summary(report: dict) -> str:
    labels = {
        "confirmed_directory": "已确认目录",
        "relation_index": "关系索引",
        "content_page": "内容页",
        "navigation_only": "仅导航",
        "empty_or_invalid": "无效入口",
        "needs_review": "需要人工确认",
    }
    lines = ["# TLIDB 候选系统验证摘要", "", f"- 输入候选：{report['candidate_input_count']}", f"- 实际请求：{report['pages_requested']}", "- 详情页请求：0", ""]
    grouped = {name: [] for name in CLASSIFICATIONS}
    for system in report["systems"]:
        grouped[system["classification"]].append(system)
    for classification in CLASSIFICATIONS:
        lines.extend([f"## {labels[classification]}", ""])
        if not grouped[classification]:
            lines.extend(["- 无", ""])
            continue
        for system in grouped[classification]:
            warning = "；".join(system["warnings"]) or "无"
            lines.extend(
                [
                    f"### {system['name_zh']}",
                    "",
                    f"- URL：{system['index_url']}",
                    f"- 条目数：{system['unique_entry_count']}",
                    f"- 置信度：{system['classification_confidence']:.2f}",
                    f"- 判断依据：{system['reason_zh']}",
                    f"- Warning：{warning}",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def verify_candidates(
    manifest: dict,
    selected_ids: set[str] | None,
    timeout: float,
    fetcher: Callable = download_candidate,
) -> tuple[list[dict], int]:
    candidates = [item for item in manifest.get("systems", []) if item.get("discovery_status") == "candidate"]
    if selected_ids is not None:
        candidates = [item for item in candidates if item.get("system_id") in selected_ids]
    results = []
    for system in candidates:
        try:
            body, status, encoding, final_url = fetcher(system["index_url"], timeout)
            html = body.decode(encoding, errors="replace")
            results.append(verify_html(system, html, status, final_url, body))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            results.append(invalid_result(system, exc))
    return results, len(candidates)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Verify TLIDB candidate system index pages")
    parser.add_argument("--system-manifest", required=True, type=Path)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--system-id", action="append", dest="system_ids")
    selection.add_argument("--all", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("data/reports/system-discovery/candidate-verification-report.json"))
    parser.add_argument("--summary", type=Path, default=Path("data/reports/system-discovery/candidate-verification-summary.md"))
    parser.add_argument("--preview-dir", type=Path, default=Path("data/reports/system-discovery/manifest-previews"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        manifest_path = args.system_manifest if args.system_manifest.is_absolute() else ROOT / args.system_manifest
        report_path = args.report if args.report.is_absolute() else ROOT / args.report
        summary_path = args.summary if args.summary.is_absolute() else ROOT / args.summary
        preview_dir = args.preview_dir if args.preview_dir.is_absolute() else ROOT / args.preview_dir
        if not args.force and not args.apply and (report_path.exists() or summary_path.exists()):
            raise FileExistsError("report or summary already exists; use --force to overwrite")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        selected = None if args.all else set(args.system_ids or [])
        if selected is not None:
            known_candidates = {item.get("system_id") for item in manifest.get("systems", []) if item.get("discovery_status") == "candidate"}
            missing = selected - known_candidates
            if missing:
                raise ValueError("unknown candidate system_id: " + ", ".join(sorted(missing)))
        results, candidate_count = verify_candidates(manifest, selected, args.timeout)
        for result in results:
            if not result["manifest_eligible"]:
                continue
            preview_path = preview_dir / f"{result['recommended_system_id']}.json"
            if preview_path.exists() and not args.force:
                result["warnings"].append(f"preview exists and was not overwritten: {preview_path}")
            else:
                write_json(preview_path, preview_manifest(result))
        backup_path = backup_path_for_manifest(manifest_path) if args.apply else None
        verified_at = datetime.now(timezone.utc).isoformat()
        if args.apply:
            apply_results(manifest_path, manifest, results, backup_path, args.force, verified_at)
        report = build_report(results, candidate_count, args.apply, backup_path)
        write_json(report_path, report)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(render_summary(report), encoding="utf-8")
        print("Candidate verification")
        print(f"- input: {report['candidate_input_count']}")
        print(f"- confirmed directories: {report['confirmed_directory_count']}")
        print(f"- relation indexes: {report['relation_index_count']}")
        print(f"- content pages: {report['content_page_count']}")
        print(f"- navigation only: {report['navigation_only_count']}")
        print(f"- invalid: {report['empty_or_invalid_count']}")
        print(f"- needs review: {report['needs_review_count']}")
        print(f"- applied: {'yes' if args.apply else 'no'}")
        print(f"- report: {report_path.relative_to(ROOT) if report_path.is_relative_to(ROOT) else report_path}")
        strict_failure = args.strict and (report["needs_review_count"] or report["pages_failed"] or report["errors"])
        return 1 if strict_failure else 0
    except Exception as exc:
        if args.debug:
            traceback.print_exc()
        print(f"Candidate verification failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
