from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from crawler.parse_hero import Element, TreeParser, clean, split_dom_lines


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(body, encoding="utf-8")


def normalize_lines(lines: list[str]) -> list[str]:
    return [clean(line) for line in lines if clean(line)]


def parse_tooltip_payload(payload: str | None) -> tuple[str | None, str | None, list[str], str]:
    if payload is None:
        return None, None, [], "bootstrap_data_bs_title_missing"
    value = payload.strip()
    if not value:
        return None, None, [], "bootstrap_data_bs_title_html"
    if "<" not in value:
        text = clean(value) or None
        return None, text, [text] if text else [], "bootstrap_data_bs_title_text"

    # Cached tlidb pages store Bootstrap tooltip markup as HTML encoded inside
    # data-bs-title. The first child div is the title and the remaining divs are
    # the body; <br> boundaries are preserved as tooltip_lines_zh.
    parser = TreeParser()
    parser.feed(value)
    roots = [child for child in parser.root.children if isinstance(child, Element)]
    wrapper = roots[0] if len(roots) == 1 else parser.root
    blocks = [child for child in wrapper.children if isinstance(child, Element)]
    if len(blocks) >= 2:
        title = clean(blocks[0].text()) or None
        lines: list[str] = []
        for block in blocks[1:]:
            lines.extend(split_dom_lines(block))
    else:
        title = None
        lines = split_dom_lines(wrapper)
    lines = normalize_lines(lines)
    return title, "\n".join(lines) or None, lines, "bootstrap_data_bs_title_html"


def extract_html_occurrences(
    html: str,
    *,
    season: str,
    locale: str,
    source_type: str,
    entity_id: str,
    page_url: str,
    manifest_order: int,
    html_file: str,
    raw_sha256: str,
    meta_sha256: str | None,
) -> tuple[list[dict], list[str]]:
    parser = TreeParser()
    parser.feed(html)
    occurrences: list[dict] = []
    warnings: list[str] = []
    element_index = -1
    for element_index, node in enumerate(parser.root.descendants()):
        if node.attrs.get("data-bs-toggle") != "tooltip":
            continue
        occurrence_index = len(occurrences)
        title, text, lines, method = parse_tooltip_payload(node.attrs.get("data-bs-title"))
        term = clean(node.text()) or None
        occurrence_id = f"{season}.tooltip.{source_type}.{entity_id}.{occurrence_index}"
        if not text:
            warnings.append(f"{occurrence_id}: missing tooltip text")
        occurrence = {
            "schema_version": 1,
            "occurrence_id": occurrence_id,
            "season": season,
            "locale": locale,
            "source_type": source_type,
            "source_entity_id": entity_id,
            "source_page_url": page_url,
            "source_manifest_order": manifest_order,
            "term_zh": term,
            "tooltip_title_zh": title,
            "tooltip_text_zh": text,
            "tooltip_lines_zh": lines,
            "extract_method": method,
            "raw_html_sha256": raw_sha256,
            "structured_ref": None,
            "source": {
                "html_file": html_file,
                "dom_locator": f'{node.tag}[data-bs-toggle="tooltip"]@document-order-{element_index}',
                "attribute_name": "data-bs-title",
                "occurrence_index_in_page": occurrence_index,
                "meta_sha256": meta_sha256,
                "hash_match": None if meta_sha256 is None else meta_sha256 == raw_sha256,
            },
        }
        occurrences.append(occurrence)
    return occurrences, warnings


def extract_manifest(
    *, season: str, manifest_path: Path, raw_dir: Path, meta_dir: Path, output_dir: Path
) -> tuple[list[dict], dict]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise ValueError("manifest entries must be a list")
    source_type = manifest.get("entity_type")
    if not isinstance(source_type, str) or not source_type:
        raise ValueError("manifest entity_type must be a non-empty string")
    locale = manifest.get("source", {}).get("locale") or "cn"
    report = {
        "schema_version": 1,
        "season": season,
        "source_type": source_type,
        "manifest_count": len(entries),
        "html_found": 0,
        "html_missing": 0,
        "pages_scanned": 0,
        "pages_failed": 0,
        "tooltip_occurrence_count": 0,
        "pages_with_tooltips": 0,
        "pages_without_tooltips": 0,
        "occurrence_count_by_extract_method": {},
        "missing_title_count": 0,
        "missing_text_count": 0,
        "structured_exact_match_count": 0,
        "structured_unmatched_count": 0,
        "warnings": [],
        "errors": [],
    }
    occurrences: list[dict] = []
    methods: Counter[str] = Counter()
    for position, entry in enumerate(entries):
        entity_id = entry.get("id")
        slug = entry.get("slug") or entity_id
        if not isinstance(entity_id, str) or not entity_id or not isinstance(slug, str) or not slug:
            report["pages_failed"] += 1
            report["errors"].append({"manifest_order": position, "error": "entry requires id and slug"})
            continue
        stem = quote(slug, safe="-_.")
        html_path = raw_dir / f"{stem}.html"
        meta_path = meta_dir / f"{stem}.meta.json"
        if not html_path.is_file():
            report["html_missing"] += 1
            report["warnings"].append(f"missing HTML: {html_path.name}")
            continue
        report["html_found"] += 1
        report["pages_scanned"] += 1
        try:
            raw = html_path.read_bytes()
            raw_sha256 = hashlib.sha256(raw).hexdigest()
            meta_sha256 = None
            if meta_path.is_file():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                meta_sha256 = meta.get("sha256")
                if meta_sha256 and meta_sha256 != raw_sha256:
                    report["warnings"].append(f"source hash mismatch: {html_path.name}")
            else:
                report["warnings"].append(f"missing meta: {meta_path.name}")
            page_rows, page_warnings = extract_html_occurrences(
                raw.decode("utf-8"),
                season=season,
                locale=locale,
                source_type=source_type,
                entity_id=entity_id,
                page_url=entry.get("url") or "",
                manifest_order=entry.get("source_order", position),
                html_file=html_path.name,
                raw_sha256=raw_sha256,
                meta_sha256=meta_sha256,
            )
            occurrences.extend(page_rows)
            report["warnings"].extend(page_warnings)
            if page_rows:
                report["pages_with_tooltips"] += 1
            else:
                report["pages_without_tooltips"] += 1
            methods.update(row["extract_method"] for row in page_rows)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            report["pages_failed"] += 1
            report["errors"].append({"id": entity_id, "error": str(exc)})
    report["tooltip_occurrence_count"] = len(occurrences)
    report["occurrence_count_by_extract_method"] = dict(sorted(methods.items()))
    report["missing_title_count"] = sum(row["tooltip_title_zh"] is None for row in occurrences)
    report["missing_text_count"] = sum(row["tooltip_text_zh"] is None for row in occurrences)
    report["structured_unmatched_count"] = sum(row["structured_ref"] is None for row in occurrences)
    write_jsonl(output_dir / "occurrences.jsonl", occurrences)
    write_json(output_dir / "report.json", report)
    return occurrences, report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Extract static Bootstrap tooltips from cached manifest HTML")
    parser.add_argument("--season", required=True)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--raw-dir", required=True, type=Path)
    parser.add_argument("--meta-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args(argv)


def rooted(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        occurrences, report = extract_manifest(
            season=args.season,
            manifest_path=rooted(args.manifest),
            raw_dir=rooted(args.raw_dir),
            meta_dir=rooted(args.meta_dir),
            output_dir=rooted(args.output),
        )
        print("Tooltip extraction")
        print(f"- pages scanned: {report['pages_scanned']}")
        print(f"- occurrences: {len(occurrences)}")
        print(f"- failed: {report['pages_failed']}")
        print(f"- output: {args.output}")
        return 1 if report["pages_failed"] else 0
    except Exception as exc:
        if args.debug:
            raise
        print(f"Tooltip extraction failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
