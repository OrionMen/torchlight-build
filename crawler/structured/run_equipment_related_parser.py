"""Generate equipment-related structured sidecars and merge Structured Search."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

from .parser_base import ParserInput
from .parsers.equipment_related_parser import DEFINITIONS, EquipmentRelatedParser
from .schema import resolve_record_landing
from .runner_context import runner_context
from crawler.season_context import DEFAULT_SEASON


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "data/generated/structured/ss13"
DEFAULT_REPORT = ROOT / "data/reports/local-wiki/equipment-related-structured-parser-v1-report.json"


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"records": []}


def generate(
    repo: Path = ROOT,
    output_root: Path = DEFAULT_OUTPUT,
    report_path: Path = DEFAULT_REPORT,
    season: str = DEFAULT_SEASON,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    context, output_root, report_path = runner_context(
        repo, season, output_root, report_path, DEFAULT_OUTPUT, DEFAULT_REPORT
    )
    results: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    for definition in DEFINITIONS:
        parser = EquipmentRelatedParser(definition)
        result = parser.parse(ParserInput(
            season_id=season,
            system_id="help",
            canonical_id=definition.canonical_id,
            canonical_route=definition.route,
            raw_html_path=context.readable_raw_manifest_root() / "help/raw_html" / f"{definition.canonical_id}.html",
        ))
        results.append(result)
        _write(output_root / "equipment_related" / f"{definition.canonical_id}.json", result)
        for record in result["records"]:
            searchable = [record["text"]]
            if record["record_type"] == "fragrance_affix":
                searchable.append(record["talent_type_name_zh"])
            else:
                searchable.extend([
                    record["sequence_tier_name_zh"], record["sequence_pattern"], record["equipment_type"],
                ])
            document = {
                "record_id": record["record_id"],
                "entity_id": definition.entity_id,
                "entity_title": definition.title,
                "record_type": record["record_type"],
                "section_name": record["section_name"],
                "text": record["text"],
                "search_text": " ".join(searchable),
                "route": record["route"],
                "source_system": record["source_system"],
                "source_page_id": record["source_page_id"],
                "source_locator": record["source_locator"],
                "landing": resolve_record_landing(record),
                "entity_type": "equipment_related_system",
                "content_category_id": "equipment_related",
                "content_category_name_zh": "装备相关",
                "content_subcategory_id": definition.subcategory_id,
                "content_subcategory_name_zh": definition.subcategory_name_zh,
            }
            for field in (
                "talent_type", "talent_type_name_zh", "recipe_id", "recipe_materials",
                "sequence_tier", "sequence_tier_name_zh", "sequence_pattern", "equipment_type",
            ):
                if field in record:
                    document[field] = record[field]
            documents.append(document)

    records = [record for result in results for record in result["records"]]
    fragrance = [record for record in records if record["record_type"] == "fragrance_affix"]
    tower = [record for record in records if record["record_type"] == "tower_sequence_affix"]
    talent_types = Counter(record["talent_type"] for record in fragrance)
    sequence_tiers = Counter(record["sequence_tier"] for record in tower)
    text_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in tower:
        text_groups[record["text"]].append(record)
    duplicate_groups = {text: group for text, group in text_groups.items() if len(group) > 1}
    mismatches = [result for result in results if result["structure_validation"]["status"] != "matched"]
    ids = [record["record_id"] for record in records]

    def find(items: list[dict[str, Any]], predicate) -> dict[str, Any]:
        record = next(item for item in items if predicate(item))
        return {
            "record_id": record["record_id"],
            "text": record["text"],
            "section_name": record["section_name"],
            "stable_key": record["source_locator"]["stable_key"],
            "landing": resolve_record_landing(record),
        }

    duplicate_group = next(group for group in duplicate_groups.values() if len({item["equipment_type"] for item in group}) > 1)
    case_studies = {
        "fragrance": {
            "medium": find(fragrance, lambda item: item["talent_type"] == "medium"),
            "core": find(fragrance, lambda item: item["talent_type"] == "core"),
            "exotic": find(fragrance, lambda item: item["talent_type"] == "exotic"),
            "multi_line": find(fragrance, lambda item: len(item["text"]) > 80),
            "all_attribute_matches": sum("全属性" in item["search_text"] for item in documents if item["record_type"] == "fragrance_affix"),
        },
        "tower": {
            "intermediate": find(tower, lambda item: item["sequence_tier"] == "intermediate"),
            "advanced": find(tower, lambda item: item["sequence_tier"] == "advanced"),
            "bow": find(tower, lambda item: item["equipment_type"] == "弓"),
            "single_handed": find(tower, lambda item: item["equipment_type"] == "单手剑"),
            "shield": find(tower, lambda item: "盾" in item["equipment_type"]),
            "duplicate_text": {
                "text": duplicate_group[0]["text"],
                "records": len(duplicate_group),
                "equipment_types": sorted({item["equipment_type"] for item in duplicate_group}),
                "unique_record_ids": len({item["record_id"] for item in duplicate_group}),
            },
            "fire_penetration_matches": sum("火焰穿透" in item["search_text"] for item in documents if item["record_type"] == "tower_sequence_affix"),
            "all_attribute_matches": sum("全属性" in item["search_text"] for item in documents if item["record_type"] == "tower_sequence_affix"),
            "bow_matches": sum(item.get("equipment_type") == "弓" for item in documents),
        },
    }
    forbidden = ("帮助手册", "DataTables_Table", "UI_", "<script", "<style", "footer")
    report = {
        "fragrance": {
            "entity": "tlidb:cn:Blending_Rituals",
            "records": len(fragrance),
            "talent_type_distribution": dict(talent_types),
            "stable_key_coverage": sum(record["source_locator"]["locator_level"] == "record" for record in fragrance) / len(fragrance) if fragrance else 0,
            "recipe_metadata_coverage": sum(bool(record.get("recipe_id")) and bool(record.get("recipe_materials")) for record in fragrance) / len(fragrance) if fragrance else 0,
            "landing_record_level": sum(record["source_locator"]["locator_level"] == "record" for record in fragrance),
            "filter_reset": sum(record["source_locator"]["view_state"].get("filter_reset") is True for record in fragrance),
        },
        "tower_sequence": {
            "entity": "tlidb:cn:TOWER_Sequence",
            "records": len(tower),
            "sequence_tier_distribution": dict(sequence_tiers),
            "equipment_type_count": len({record["equipment_type"] for record in tower}),
            "stable_key_coverage": sum(record["source_locator"]["locator_level"] == "record" for record in tower) / len(tower) if tower else 0,
            "duplicate_text_groups": len(duplicate_groups),
            "landing_record_level": sum(record["source_locator"]["locator_level"] == "record" for record in tower),
            "datatable_ready": sum(record["source_locator"]["view_state"].get("datatable_ready") is True for record in tower),
        },
        "structured_search": {
            "previous_total": 0,
            "added": len(documents),
            "new_total": len(documents),
            "existing_record_ids_preserved": 0,
        },
        "classification_errors": sum(
            document["content_category_id"] != "equipment_related"
            or document["content_subcategory_id"] not in {
                "equipment_related_fragrance", "equipment_related_tower_sequence",
            }
            for document in documents
        ),
        "noise_validation": {
            "forbidden_text_records": sum(any(token in record["text"] for token in forbidden) for record in records),
            "materials_in_search_text": sum(
                any(material["name_zh"] in document["search_text"] for material in document.get("recipe_materials", []))
                for document in documents
            ),
            "internal_ids_in_search_text": sum(
                str(document.get("recipe_id")) in document["search_text"]
                for document in documents if document.get("recipe_id")
            ),
        },
        "case_studies": case_studies,
        "errors": [result["source_page"]["canonical_id"] for result in mismatches]
        + (["record_id collision"] if len(ids) != len(set(ids)) else []),
    }
    index = {
        "schema_version": 1,
        "season_id": season,
        "entity_count": 2,
        "record_count": len(records),
        "parser_id": EquipmentRelatedParser.parser_id,
        "parser_version": EquipmentRelatedParser.parser_version,
        "entities": [{
            "entity_id": definition.entity_id,
            "route": definition.route,
            "record_count": result["record_count"],
            "structure_status": result["structure_validation"]["status"],
            "structure_signature": result["structure_signature"],
        } for definition, result in zip(DEFINITIONS, results)],
        "records": documents,
    }
    _write(output_root / "equipment-related-structured-index.json", index)
    _write(report_path, report)
    return results, index, report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    _, _, report = generate(args.repo.resolve(), args.output_root, args.report, args.season)
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
