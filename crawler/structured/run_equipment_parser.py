"""Generate ordinary-equipment structured sidecars and their isolated search index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from .parser_base import ParserInput
from .parsers import EQUIPMENT_DEFINITIONS, EquipmentDefinition, EquipmentParser
from .schema import resolve_record_landing
from crawler.season_context import DEFAULT_SEASON, SeasonContext


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW_ROOT = ROOT / "data/raw/manifests/inventory/raw_html"
DEFAULT_OUTPUT_ROOT = ROOT / "data/generated/structured/ss13"
DEFAULT_REPORT = ROOT / "data/reports/local-wiki/equipment-structured-parser-v1-report.json"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _iter_records(result: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield from result["sections"]["base_affixes"]
    yield from result["sections"]["craft_affixes"]


def generate_equipment_structured_data(
    *,
    raw_root: Path = DEFAULT_RAW_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    report_path: Path = DEFAULT_REPORT,
    definitions: Sequence[EquipmentDefinition] = EQUIPMENT_DEFINITIONS,
    season: str = DEFAULT_SEASON,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    context = SeasonContext(ROOT, season)
    if raw_root == DEFAULT_RAW_ROOT:
        raw_root = context.readable_raw_manifest_root() / "inventory/raw_html"
    if output_root == DEFAULT_OUTPUT_ROOT:
        output_root = context.structured_root
    if report_path == DEFAULT_REPORT and season != DEFAULT_SEASON:
        report_path = context.report_root / DEFAULT_REPORT.name
    equipment_output = output_root / "equipment"
    entity_results: list[dict[str, Any]] = []
    equipment_index: list[dict[str, Any]] = []
    structured_search_records: list[dict[str, Any]] = []

    for definition in definitions:
        parser = EquipmentParser(definition)
        result = parser.parse(
            ParserInput(
                season_id=season,
                system_id="inventory",
                canonical_id=definition.canonical_id,
                canonical_route=definition.route,
                raw_html_path=raw_root / f"{definition.canonical_id}.html",
            )
        )
        entity_results.append(result)
        _write_json(equipment_output / f"{definition.canonical_id}.json", result)
        base_count = len(result["sections"]["base_affixes"])
        craft_count = len(result["sections"]["craft_affixes"])
        status = result["structure_validation"]["status"]
        equipment_index.append(
            {
                "entity_id": result["entity_id"],
                "route": result["route"],
                "base_affix_count": base_count,
                "craft_affix_count": craft_count,
                "parser_version": result["parser_version"],
                "structure_status": status,
            }
        )
        for record in _iter_records(result):
            landing = resolve_record_landing(record)
            search_record = {
                    "record_id": record["record_id"],
                    "entity_id": record["entity_id"],
                    "entity_title": result["title"],
                    "record_type": record["record_type"],
                    "section_name": record["section_name"],
                    "text": record["text"],
                    "route": record["route"],
                    "source_locator": record["source_locator"],
                    "landing": landing,
                    "entity_type": "equipment",
                    "content_category_id": "equipment",
                    "content_category_name_zh": "装备",
                    "content_subcategory_id": "equipment_craft",
                    "content_subcategory_name_zh": "打造装备",
                }
            if record["record_type"] == "equipment_craft_affix":
                search_record["tier"] = record.get("tier")
                search_record["source_tier_value"] = record["source_locator"].get("tier_value")
            structured_search_records.append(search_record)

    equipment_index_document = {
        "schema_version": 1,
        "season_id": season,
        "parser_id": EquipmentParser.parser_id,
        "entity_count": len(equipment_index),
        "entities": equipment_index,
        "record_count": len(structured_search_records),
        "records": structured_search_records,
    }
    _write_json(output_root / "equipment-structured-index.json", equipment_index_document)

    all_records = [record for result in entity_results for record in _iter_records(result)]
    report = {
        "equipment_entities": len(definitions),
        "parsed_entities": sum(
            result["structure_validation"]["status"] == "matched" for result in entity_results
        ),
        "structure_mismatches": sum(
            result["structure_validation"]["status"] == "structure_mismatch"
            for result in entity_results
        ),
        "base_affix_records": sum(
            len(result["sections"]["base_affixes"]) for result in entity_results
        ),
        "craft_affix_records": sum(
            len(result["sections"]["craft_affixes"]) for result in entity_results
        ),
        "record_level_locators": sum(
            record["source_locator"]["locator_level"] == "record" for record in all_records
        ),
        "section_level_locators": sum(
            record["source_locator"]["locator_level"] == "section" for record in all_records
        ),
        "unstable_identity_records": sum(
            record["identity_confidence"] != "high" for record in all_records
        ),
        "structured_search_records": len(structured_search_records),
        "parser_id": EquipmentParser.parser_id,
        "parser_version": EquipmentParser.parser_version,
        "mismatch_examples": [
            {
                "entity_id": result["entity_id"],
                "structure_validation": result["structure_validation"],
            }
            for result in entity_results
            if result["structure_validation"]["status"] == "structure_mismatch"
        ][:5],
    }
    _write_json(report_path, report)
    return entity_results, equipment_index_document, report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    _, _, report = generate_equipment_structured_data(
        raw_root=args.raw_root, output_root=args.output_root, report_path=args.report,
        season=args.season,
    )
    return 0 if report["structure_mismatches"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
