"""Audit the five approved Memory structured-data sections without parsing records."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from crawler.structured.structure_probe import probe_section_table


ENTITY_ID = "tlidb:cn:Hero_Memories"
SECTION_SPECS = (
    ("base_attributes", "基础属性", "memory_base_attribute", "inventory", "Hero_Memories", "/cn/Hero_Memories/"),
    ("fixed_affixes", "固有词缀", "memory_fixed_affix", "inventory", "Hero_Memories", "/cn/Hero_Memories/"),
    ("random_affixes", "随机词缀", "memory_random_affix", "inventory", "Hero_Memories", "/cn/Hero_Memories/"),
    ("revival_affixes", "复苏词缀", "memory_revival_affix", "help", "Memory_Revival", "/cn/Memory_Revival/"),
    ("revival_moon_affixes", "复苏词缀（月相）", "memory_revival_moon_affix", "help", "Memory_Revival", "/cn/Memory_Revival/"),
)
EXPECTED_HEADERS = {
    "inventory": ["Tier", "Modifier", "Level", "Weight", "来源"],
    "help": ["Tier", "Modifier", "Level", "Weight"],
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _source(repo: Path, system: str, page_id: str) -> dict[str, Any]:
    manifest_path = repo / f"sources/{system}_manifest.json"
    raw_path = repo / f"data/raw/manifests/{system}/raw_html/{page_id}.html"
    meta_path = repo / f"data/raw/manifests/{system}/meta/{page_id}.meta.json"
    manifest = _load_json(manifest_path)
    entry = next(
        (entry for entry in manifest.get("entries", []) if entry.get("id") == page_id or entry.get("slug") == page_id),
        None,
    )
    meta = _load_json(meta_path) if meta_path.is_file() else {}
    size = raw_path.stat().st_size if raw_path.is_file() else 0
    return {
        "system_id": system,
        "page_id": page_id,
        "manifest_path": str(manifest_path.relative_to(repo)),
        "manifest_entry_present": entry is not None,
        "canonical_url": (entry or {}).get("url"),
        "raw_path": str(raw_path.relative_to(repo)),
        "raw_present": raw_path.is_file(),
        "raw_size": size,
        "raw_nonempty": size > 0,
        "meta_present": meta_path.is_file(),
        "http_status": meta.get("http_status"),
        "meta_content_length": meta.get("content_length"),
        "meta_hash_present": bool(meta.get("html_sha256")),
    }


def _entity_model(repo: Path) -> dict[str, Any]:
    index = _load_json(repo / "data/generated/entity-index-v3.json")
    entity = next((item for item in index.get("entities", []) if item.get("entity_id") == ENTITY_ID), None)
    revival_entities = [
        item.get("entity_id") for item in index.get("entities", [])
        if item.get("canonical_route") == "/cn/Memory_Revival/"
    ]
    return {
        "entity_id": ENTITY_ID,
        "entity_present": entity is not None,
        "entity_type": (entity or {}).get("entity_type"),
        "category": (entity or {}).get("content_category_id") or (entity or {}).get("category"),
        "subcategory": (entity or {}).get("content_subcategory_id") or (entity or {}).get("subcategory"),
        "canonical_route": (entity or {}).get("canonical_route"),
        "memory_revival_is_independent_entity": bool(revival_entities),
        "memory_revival_entity_ids": revival_entities,
        "recommended_model": "one Hero_Memories entity with Memory_Revival as a supplemental record source",
    }


def _source_overlaps(repo: Path, page_id: str) -> list[str]:
    systems = []
    for path in sorted((repo / "sources").glob("*_manifest.json")):
        data = _load_json(path)
        if any(entry.get("id") == page_id or entry.get("slug") == page_id for entry in data.get("entries", [])):
            systems.append(path.stem.removesuffix("_manifest"))
    return systems


def _row_has_line_break(html: str, stable_key: str) -> bool:
    match = re.search(
        rf"<tr\b[^>]*>.*?data-modifier-id=[\"']{re.escape(stable_key)}[\"'].*?</tr>",
        html,
        re.I | re.S,
    )
    return bool(match and re.search(r"<br\s*/?>", match.group(0), re.I))


def build_report(repo: Path) -> dict[str, Any]:
    sources = {
        "hero_memories": _source(repo, "inventory", "Hero_Memories"),
        "memory_revival": _source(repo, "help", "Memory_Revival"),
    }
    html_by_page = {
        "Hero_Memories": (repo / sources["hero_memories"]["raw_path"]).read_text(encoding="utf-8", errors="replace"),
        "Memory_Revival": (repo / sources["memory_revival"]["raw_path"]).read_text(encoding="utf-8", errors="replace"),
    }
    sections: list[dict[str, Any]] = []
    key_occurrences: dict[str, list[dict[str, Any]]] = defaultdict(list)
    record_counts: Counter[str] = Counter()
    examples: dict[str, Any] = {}
    longest: tuple[int, dict[str, Any]] | None = None
    errors: list[str] = []

    for section_key, section_name, record_type, system, page_id, route in SECTION_SPECS:
        probe = probe_section_table(html_by_page[page_id], section_id=section_name)
        descriptor = probe["descriptor"]
        rows = list(probe["rows"])
        headers_ok = descriptor["headers"] == EXPECTED_HEADERS[system]
        stable_count = descriptor["rows_with_stable_key"]
        structure_ok = all((
            descriptor["section_present"],
            descriptor["tab_target_present"],
            descriptor["table_count"] == 1,
            headers_ok,
            descriptor["row_count"] > 0,
            stable_count == descriptor["row_count"],
        ))
        if not structure_ok:
            errors.append(f"structure mismatch: {page_id}#{section_name}")
        for index, row in enumerate(rows):
            if row.stable_key:
                key_occurrences[row.stable_key].append({
                    "section_key": section_key,
                    "record_type": record_type,
                    "source_page_id": page_id,
                    "row_index": index,
                })
            text = row.cells[1] if len(row.cells) > 1 else ""
            candidate = {
                "stable_key": row.stable_key,
                "text": text,
                "source_page_id": page_id,
                "route": route,
                "section_key": section_key,
                "row_index": index,
                "has_dom_line_break": bool(row.stable_key and _row_has_line_break(html_by_page[page_id], row.stable_key)),
            }
            if longest is None or len(text) > longest[0]:
                longest = (len(text), candidate)
        first = rows[0]
        examples[record_type] = {
            "stable_key": first.stable_key,
            "text": first.cells[1] if len(first.cells) > 1 else "",
            "source_page_id": page_id,
            "route": route,
            "section_key": section_key,
        }
        record_counts[record_type] = len(rows)
        sections.append({
            "section_key": section_key,
            "section_name": section_name,
            "record_type": record_type,
            "source_system": system,
            "source_page_id": page_id,
            "route": route,
            "dom_id": section_name,
            "tab_target": f"#{section_name}",
            "pane_classes": descriptor["section_classes"],
            "table_count": descriptor["table_count"],
            "headers": descriptor["headers"],
            "expected_headers": EXPECTED_HEADERS[system],
            "headers_match": headers_ok,
            "row_count": descriptor["row_count"],
            "stable_key_attribute": descriptor["stable_key_attribute"],
            "rows_with_stable_key": stable_count,
            "stable_key_coverage": stable_count / descriptor["row_count"] if descriptor["row_count"] else 0,
            "modifier_column_index": 1,
            "tab_target_present": descriptor["tab_target_present"],
            "structure_status": "matched" if structure_ok else "structure_mismatch",
            "structure_signature": probe["structure_signature"],
            "recommended_locator": f'#{section_name} [data-modifier-id="<stable_key>"]',
        })

    duplicates = {
        key: occurrences for key, occurrences in key_occurrences.items() if len(occurrences) > 1
    }
    total = sum(record_counts.values())
    stable_total = sum(section["rows_with_stable_key"] for section in sections)
    entity = _entity_model(repo)
    if not all(source["manifest_entry_present"] and source["raw_nonempty"] for source in sources.values()):
        errors.append("source completeness failed")
    if not entity["entity_present"] or entity["memory_revival_is_independent_entity"]:
        errors.append("entity model mismatch")

    return {
        "schema_version": 1,
        "audit_id": "memory-structured-dom-audit-v1",
        "entity_model": entity,
        "source_completeness": {
            **sources,
            "authorized_sources_complete": not any("source completeness" in error for error in errors),
            "hero_memories_source_overlaps": _source_overlaps(repo, "Hero_Memories"),
            "source_selection": {
                "Hero_Memories": "inventory canonical source",
                "Memory_Revival": "help supplemental source",
            },
        },
        "sections": sections,
        "candidate_record_types": [
            {
                "record_type": record_type,
                "section_key": section_key,
                "section_name": section_name,
                "count": record_counts[record_type],
                "entity_id": ENTITY_ID,
                "source_system": system,
                "source_page_id": page_id,
                "route": route,
            }
            for section_key, section_name, record_type, system, page_id, route in SECTION_SPECS
        ],
        "record_counts": {**record_counts, "total": total},
        "stable_identity": {
            "attribute": "data-modifier-id",
            "records_with_stable_key": stable_total,
            "coverage": stable_total / total if total else 0,
            "recommended_identity": "entity_id + record_type + section_key + stable_key",
            "identity_independent_of": ["Chinese text", "numeric values", "season_id"],
        },
        "duplicate_key_analysis": {
            "unique_stable_keys": len(key_occurrences),
            "duplicate_stable_key_count": len(duplicates),
            "duplicate_occurrence_count": sum(len(items) for items in duplicates.values()),
            "duplicates": duplicates,
            "conclusion": "No stable-key collision was found across the five approved sections." if not duplicates else "Scope lookup by section and record type; do not use a page-global key lookup.",
        },
        "view_state": {
            "required_dimension": "memory_section",
            "values": [spec[0] for spec in SECTION_SPECS],
            "bootstrap_tab_activation_required": True,
            "tier_filter_required": False,
            "client_filter_required": False,
            "landing_order": ["activate source page tab", "wait for shown.bs.tab", "lookup section-scoped data-modifier-id", "scroll", "highlight"],
        },
        "locator_support": {
            "record_level": stable_total,
            "section_level": total - stable_total,
            "page_level": 0,
            "record_level_coverage": stable_total / total if total else 0,
            "scope_rule": "Resolve data-modifier-id inside the selected tab pane, never globally.",
        },
        "supplemental_source_landing": {
            "entity_id": ENTITY_ID,
            "entity_canonical_route": "/cn/Hero_Memories/",
            "revival_record_route": "/cn/Memory_Revival/",
            "source_system": "help",
            "source_page_id": "Memory_Revival",
            "contract_supported": True,
            "reason": "Structured records already carry route/source_page_id independently from entity_id.",
        },
        "noise_exclusions": {
            "whitelist_only": [spec[1] for spec in SECTION_SPECS],
            "excluded": [
                "aggregate 词缀 tab",
                "Item and related item lists",
                "追忆复苏 overview/help tabs",
                "navigation and footer",
                "scripts and styles",
                "image/resource names",
                "Tier/Level/Weight/来源 columns as record text",
                "unapproved page prose and material instructions",
            ],
            "record_boundary": "one approved table body row",
            "record_text": "Modifier cell only; player-facing tooltip detail may remain within the same record, without semantic splitting.",
        },
        "structure_signature_contract": {
            "fields": ["section presence", "tab target", "pane classes", "table count", "headers", "row count", "stable-key attribute", "stable-key coverage"],
            "on_mismatch": "structure_mismatch; do not emit apparently valid empty records",
            "section_signatures": {section["section_key"]: section["structure_signature"] for section in sections},
        },
        "case_studies": {
            "one_per_record_type": examples,
            "multi_effect_record": longest[1] if longest else None,
            "duplicate_stable_key": next(iter(duplicates.items()), None),
        },
        "framework_compatibility": {
            "compatible": True,
            "existing_schema_fields_sufficient": True,
            "record_id_support": True,
            "source_locator_support": True,
            "structure_signature_support": True,
            "resolve_record_landing_support": True,
            "supplemental_route_support": True,
            "required_framework_changes": [],
        },
        "parser_recommendation": {
            "parser_id": "memory_structured_parser",
            "entity_count": 1,
            "source_pages": 2,
            "expected_records": total,
            "approach": "One parameterized parser with five strict section contracts; preserve one entity identity while each record lands on its real source page.",
            "semantic_parsing": False,
        },
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/reports/local-wiki/memory-structured-dom-audit-v1.json"),
    )
    args = parser.parse_args()
    repo = args.repo.resolve()
    output = args.output if args.output.is_absolute() else repo / args.output
    report = build_report(repo)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
