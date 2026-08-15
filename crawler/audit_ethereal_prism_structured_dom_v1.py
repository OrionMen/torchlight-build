"""Audit Ethereal Prism DOM contracts for a future structured parser."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from crawler.audit_ethereal_prism_v1 import inspect_ethereal_prism_html
from crawler.structured.structure_probe import probe_section_table


ENTITY_ID = "tlidb:cn:Ethereal_Prism"
ROUTE = "/cn/Ethereal_Prism/"
SECTIONS = (
    ("base_affixes", "基础词缀", "ethereal_prism_base_affix", ["Modifier"]),
    ("random_affixes", "随机词缀", "ethereal_prism_random_affix", ["Modifier", "出现位置"]),
)


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    @property
    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())


def _plain(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    return parser.text


def _section_fragment(html: str, section_id: str) -> str:
    starts = list(re.finditer(r'<div\s+id="([^"]+)"\s+class="tab-pane[^>]*>', html, re.I))
    for index, match in enumerate(starts):
        if match.group(1) == section_id:
            end = starts[index + 1].start() if index + 1 < len(starts) else len(html)
            return html[match.end():end]
    return ""


def inspect_section_rows(html: str, section_id: str) -> list[dict[str, Any]]:
    """Return one candidate per table row, using the outermost modifier key."""

    fragment = _section_fragment(html, section_id)
    records = []
    for row_index, match in enumerate(re.finditer(r"<tr\b[^>]*>(.*?)</tr>", fragment, re.I | re.S)):
        row_html = match.group(1)
        modifier_ids = re.findall(r'data-modifier-id=["\']([^"\']+)["\']', row_html, re.I)
        if not modifier_ids:
            continue
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row_html, re.I | re.S)
        records.append({
            "row_index": len(records),
            "outer_stable_key": modifier_ids[0],
            "nested_modifier_ids": modifier_ids[1:],
            "all_modifier_ids": modifier_ids,
            "text": _plain(cells[0]) if cells else "",
            "source_text": _plain(cells[1]) if len(cells) > 1 else "",
            "br_count": len(re.findall(r"<br\s*/?>", cells[0] if cells else "", re.I)),
        })
    return records


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _source(repo: Path) -> dict[str, Any]:
    manifest_path = repo / "sources/inventory_manifest.json"
    raw_path = repo / "data/raw/manifests/inventory/raw_html/Ethereal_Prism.html"
    meta_path = repo / "data/raw/manifests/inventory/meta/Ethereal_Prism.meta.json"
    manifest = _load(manifest_path)
    entry = next((item for item in manifest.get("entries", []) if item.get("id") == "Ethereal_Prism"), None)
    meta = _load(meta_path) if meta_path.is_file() else {}
    size = raw_path.stat().st_size if raw_path.is_file() else 0
    return {
        "source_system": "inventory",
        "source_page_id": "Ethereal_Prism",
        "manifest_entry_present": entry is not None,
        "manifest_path": str(manifest_path.relative_to(repo)),
        "canonical_url": (entry or {}).get("url"),
        "canonical_route": ROUTE,
        "raw_path": str(raw_path.relative_to(repo)),
        "raw_present": raw_path.is_file(),
        "raw_size": size,
        "raw_nonempty": size > 0,
        "zero_byte": raw_path.is_file() and size == 0,
        "missing": not raw_path.is_file(),
        "meta_present": meta_path.is_file(),
        "http_status": meta.get("http_status"),
        "meta_content_length": meta.get("content_length"),
        "meta_hash_present": bool(meta.get("html_sha256")),
    }


def _entity(repo: Path) -> dict[str, Any]:
    index = _load(repo / "data/generated/entity-index-v3.json")
    entity = next((item for item in index.get("entities", []) if item.get("entity_id") == ENTITY_ID), None)
    return {
        "entity_id": ENTITY_ID,
        "present": entity is not None,
        "entity_count": int(entity is not None),
        "entity_type": (entity or {}).get("entity_type"),
        "category": (entity or {}).get("content_category_id") or (entity or {}).get("category"),
        "subcategory": (entity or {}).get("content_subcategory_id") or (entity or {}).get("subcategory"),
        "canonical_route": (entity or {}).get("canonical_route"),
        "visibility": (entity or {}).get("entity_visibility"),
        "actual_subcategory_note": "The repository's versioned content-tree id is talent_ethereal_prism; the shorter ethereal_prism name is a business label, not the current stored id.",
        "model": "one talent_system Entity with two structured affix sections",
    }


def _excluded_sources(repo: Path, html: str) -> dict[str, Any]:
    legacy = inspect_ethereal_prism_html(html)
    item_links = legacy["item_section"]["linked_items"]
    recovered = _load(repo / "sources/recovered_internal_pages_manifest.json")
    recovered_ids = {item.get("id") for item in recovered.get("entries", [])}
    calibrate_raw = repo / "data/raw/manifests/recovered_internal_pages/raw_html/Calibrate_Ethereal_Prism.html"
    return {
        "item_tab_detected": legacy["item_section"]["detected"],
        "related_item_count": len(item_links),
        "related_items": [{
            "id": item["id"],
            "title": item["title"],
            "route": f'/cn/{item["id"]}/',
            "raw_snapshot_available": item["id"] in recovered_ids,
            "structured_affix_source": False,
        } for item in item_links],
        "calibrate": {
            "id": "Calibrate_Ethereal_Prism",
            "route": "/cn/Calibrate_Ethereal_Prism/",
            "manifest_entry_present": "Calibrate_Ethereal_Prism" in recovered_ids,
            "raw_present": calibrate_raw.is_file(),
            "raw_size": calibrate_raw.stat().st_size if calibrate_raw.is_file() else 0,
            "classification": "support_page",
            "structured_affix_source": False,
        },
        "main_record_sources": ["Ethereal_Prism#基础词缀", "Ethereal_Prism#随机词缀"],
    }


def _dupes(records: list[dict[str, Any]], field: str) -> dict[str, Any]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for record in records:
        grouped[record[field]].append(record["row_index"])
    duplicates = {value: rows for value, rows in grouped.items() if value and len(rows) > 1}
    return {
        "group_count": len(duplicates),
        "record_count": sum(len(rows) for rows in duplicates.values()),
        "examples": [{"value": value, "row_indexes": rows[:8]} for value, rows in list(duplicates.items())[:5]],
    }


def _case(record: dict[str, Any], section_key: str, section_name: str, record_type: str) -> dict[str, Any]:
    key = record["outer_stable_key"]
    return {
        "source_system": "inventory",
        "source_page_id": "Ethereal_Prism",
        "route": ROUTE,
        "section_key": section_key,
        "section_name": section_name,
        "record_type": record_type,
        "stable_key": f"modifier:{key}",
        "nested_modifier_ids": record["nested_modifier_ids"],
        "text": record["text"],
        "text_shape": "multi_line" if record["br_count"] else "single_line",
        "view_state": {"ethereal_prism_section": section_key, "datatable_ready": True},
        "locator_level": "record",
        "landing_selector": f'#{section_name} table.DataTable tbody [data-modifier-id="{key}"]',
    }


def build_report(repo: Path) -> dict[str, Any]:
    source = _source(repo)
    raw_path = repo / source["raw_path"]
    html = raw_path.read_text(encoding="utf-8", errors="replace") if raw_path.is_file() else ""
    entity = _entity(repo)
    excluded = _excluded_sources(repo, html) if html else {}
    sections = []
    records_by_key: dict[str, list[dict[str, Any]]] = {}
    all_outer: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_nested: Counter[str] = Counter()
    errors: list[str] = []

    for section_key, section_name, record_type, headers in SECTIONS:
        probe = probe_section_table(html, section_id=section_name)
        records = inspect_section_rows(html, section_name)
        records_by_key[section_key] = records
        for record in records:
            all_outer[record["outer_stable_key"]].append({
                "section_key": section_key, "row_index": record["row_index"],
            })
            all_nested.update(record["nested_modifier_ids"])
        descriptor = probe["descriptor"]
        structure_ok = all((
            descriptor["section_present"],
            descriptor["tab_target_present"],
            descriptor["table_count"] == 1,
            descriptor["headers"] == headers,
            len(records) > 0,
            all(record["outer_stable_key"] for record in records),
        ))
        if not structure_ok:
            errors.append(f"structure mismatch: {section_name}")
        signature_payload = {
            "section_present": descriptor["section_present"],
            "tab_target_present": descriptor["tab_target_present"],
            "pane_classes": descriptor["section_classes"],
            "table_count": descriptor["table_count"],
            "headers": descriptor["headers"],
            "row_count": len(records),
            "row_stable_attribute": "outermost data-modifier-id",
            "outer_stable_coverage": sum(bool(record["outer_stable_key"]) for record in records),
        }
        sections.append({
            "section_key": section_key,
            "section_name": section_name,
            "record_type": record_type,
            "container_selector": f"#{section_name}",
            "tab_target": f"#{section_name}",
            "pane_classes": descriptor["section_classes"],
            "table_selector": f"#{section_name} table.DataTable",
            "table_count": descriptor["table_count"],
            "headers": descriptor["headers"],
            "expected_headers": headers,
            "row_selector": "tbody tr containing an outer data-modifier-id",
            "record_separator": "one tbody tr",
            "row_count": len(records),
            "rows_with_outer_stable_key": sum(bool(record["outer_stable_key"]) for record in records),
            "rows_with_nested_modifier": sum(bool(record["nested_modifier_ids"]) for record in records),
            "stable_key_rule": "Use the first/outermost data-modifier-id in the row; nested modifier ids are effect payload, not row identity.",
            "structure_status": "matched" if structure_ok else "structure_mismatch",
            "structure_signature": hashlib.sha256(
                json.dumps(signature_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        })

    base = records_by_key.get("base_affixes", [])
    random = records_by_key.get("random_affixes", [])
    all_records = base + random
    duplicate_outer = {key: values for key, values in all_outer.items() if len(values) > 1}
    duplicate_nested = {key: count for key, count in all_nested.items() if count > 1}
    base_keys = {record["outer_stable_key"] for record in base}
    random_keys = {record["outer_stable_key"] for record in random}
    base_text = _dupes(base, "text")
    random_text = _dupes(random, "text")
    same_text_record = next((record for record in random if Counter(item["text"] for item in random)[record["text"]] > 1), None)
    multi_line = next((record for record in all_records if record["br_count"] > 0), None)

    if not source["manifest_entry_present"] or not source["raw_nonempty"] or source["http_status"] != 200:
        errors.append("source completeness failed")
    if not entity["present"] or entity["entity_type"] != "talent_system" or entity["category"] != "talent_board":
        errors.append("entity model mismatch")
    if len(base) != 33 or len(random) != 358:
        errors.append("record count differs from the confirmed 33/358 contract")
    if duplicate_outer:
        errors.append("outer stable-key collision")
    if excluded and (excluded["related_item_count"] != 24 or not excluded["calibrate"]["manifest_entry_present"]):
        errors.append("excluded source inventory mismatch")

    case_studies = {
        "base_affix": _case(base[0], "base_affixes", "基础词缀", "ethereal_prism_base_affix") if base else None,
        "random_affix": _case(random[0], "random_affixes", "随机词缀", "ethereal_prism_random_affix") if random else None,
        "multi_line_effect": _case(
            multi_line,
            "base_affixes" if multi_line in base else "random_affixes",
            "基础词缀" if multi_line in base else "随机词缀",
            "ethereal_prism_base_affix" if multi_line in base else "ethereal_prism_random_affix",
        ) if multi_line else None,
        "same_text_different_modifier": _case(
            same_text_record, "random_affixes", "随机词缀", "ethereal_prism_random_affix"
        ) if same_text_record else None,
        "cross_section_stable_key": None,
    }
    if same_text_record:
        case_studies["same_text_different_modifier"]["matching_outer_keys"] = [
            f'modifier:{record["outer_stable_key"]}'
            for record in random if record["text"] == same_text_record["text"]
        ]

    candidate_count = len(all_records)
    stable_count = sum(bool(record["outer_stable_key"]) for record in all_records)
    framework_compatible = not errors and stable_count == candidate_count
    return {
        "schema_version": 1,
        "audit_id": "ethereal-prism-structured-dom-audit-v1",
        "source_completeness": source,
        "entity_model": entity,
        "excluded_sources": excluded,
        "sections": sections,
        "candidate_record_types": [
            {"record_type": record_type, "section_key": section_key, "section_name": section_name, "count": len(records_by_key.get(section_key, []))}
            for section_key, section_name, record_type, _ in SECTIONS
        ],
        "record_counts": {
            "ethereal_prism_base_affix": len(base),
            "ethereal_prism_random_affix": len(random),
            "total": candidate_count,
        },
        "candidate_records": candidate_count,
        "stable_key_records": stable_count,
        "stable_key_coverage": stable_count / candidate_count if candidate_count else 0,
        "stable_identity": {
            "attribute": "data-modifier-id",
            "row_identity": "first/outermost modifier id",
            "rows_with_nested_modifier": sum(bool(record["nested_modifier_ids"]) for record in all_records),
            "nested_modifier_occurrences": sum(all_nested.values()),
            "nested_modifier_unique": len(all_nested),
            "recommended_record_identity": "entity_id + record_type + section_key + outer stable_key",
            "identity_independent_of": ["Chinese text", "numeric values", "Item count", "season_id"],
        },
        "duplicate_key_analysis": {
            "base_internal_outer_key_duplicates": len(base) - len(base_keys),
            "random_internal_outer_key_duplicates": len(random) - len(random_keys),
            "cross_section_outer_key_duplicates": len(base_keys & random_keys),
            "outer_key_collision_count": len(duplicate_outer),
            "nested_key_duplicate_count": len(duplicate_nested),
            "nested_key_duplicate_occurrences": sum(duplicate_nested.values()),
            "nested_key_examples": list(duplicate_nested.items())[:8],
            "base_same_text": base_text,
            "random_same_text": random_text,
            "same_text_records_remain_independent": True,
            "conclusion": "All 391 outer row keys are unique. Nested modifier ids are payload and may repeat; never use the last/nested modifier as row identity.",
        },
        "view_states": [
            {"ethereal_prism_section": "base_affixes", "tab_target": "#基础词缀", "datatable_ready": True},
            {"ethereal_prism_section": "random_affixes", "tab_target": "#随机词缀", "datatable_ready": True},
        ],
        "locator_support": {
            "record_level": stable_count,
            "section_level": candidate_count - stable_count,
            "page_level": 0,
            "record_level_coverage": stable_count / candidate_count if candidate_count else 0,
            "lookup_scope": "selected section's table.DataTable tbody",
            "fallback": ["record", "section", "page"],
        },
        "datatable_behavior": {
            "used_by_sections": ["基础词缀", "随机词缀"],
            "paging": False,
            "info": False,
            "auto_width": False,
            "order": [],
            "client_search": True,
            "state_save": False,
            "row_dom_lifecycle": "all 391 rows remain in DOM because paging is disabled",
            "page_length": "not applicable",
            "datatable_ready_required": True,
            "filter_reset_required": False,
        },
        "search_text_boundary": {
            "include": ["affix effect text", "section/type label"],
            "exclude": ["出现位置 Item names", "calibration prose", "UI labels", "internal IDs", "image/resource names", "tooltip metadata"],
            "random_affix_column_rule": "Use Modifier cell only; do not append 出现位置 to default search text.",
        },
        "noise_exclusions": [
            "Item tab and 24 related Item pages",
            "Calibrate_Ethereal_Prism support page",
            "navigation and footer",
            "scripts, styles, DataTable controls, and UI labels",
            "image src/alt and internal resource names",
            "tooltip attributes/data-bs-title",
            "nested modifier ids as independent records",
            "出现位置 links from default record text",
        ],
        "structure_signature_recommendation": {
            "include": ["section/tab presence", "pane classes", "one DataTable per section", "headers", "row count", "outer stable-key attribute and coverage"],
            "exclude": ["Chinese descriptions", "numeric values", "images", "Item count"],
            "section_signatures": {section["section_key"]: section["structure_signature"] for section in sections},
            "on_mismatch": "structure_mismatch; emit no apparently valid empty records",
        },
        "framework_compatible": framework_compatible,
        "framework_compatibility": {
            "compatible": framework_compatible,
            "existing_contracts_reused": ["record_id", "entity_id", "record_type", "route", "section", "stable_key", "source_locator", "view_state", "record-level landing", "datatable_ready"],
            "generic_extension_required": False,
            "special_parser_rule": "Select the outermost row modifier id; this is parser logic, not a framework extension.",
        },
        "case_studies": case_studies,
        "parser_recommendation": "Proceed with one Ethereal Prism parser profile producing 33 base-affix and 358 random-affix records. Use strict two-section whitelists, outer modifier identity, DataTable-ready landing, and Modifier-cell-only search text." if framework_compatible else "Stop parser implementation until the reported source/structure errors are resolved.",
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    report = build_report(repo)
    output = args.output or repo / "data/reports/local-wiki/ethereal-prism-structured-dom-audit-v1.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "errors": report["errors"]}, ensure_ascii=False))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
