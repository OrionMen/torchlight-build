"""Generate Vorax equipment sidecars and merge them into Structured Search."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote

from .parser_base import ParserInput
from .parsers.vorax_equipment_parser import VoraxDefinition, VoraxEquipmentParser
from .schema import resolve_record_landing
from .runner_context import runner_context
from crawler.season_context import DEFAULT_SEASON, SeasonContext


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "data/generated/structured/ss13"
DEFAULT_REPORT = ROOT / "data/reports/local-wiki/vorax-structured-parser-v1-report.json"


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _definitions(context: SeasonContext) -> list[VoraxDefinition]:
    index = json.loads(context.readable_entity_output().read_text(encoding="utf-8"))
    return [
        VoraxDefinition(
            entity["entity_id"].removeprefix("tlidb:cn:"),
            entity.get("entity_title_zh") or entity.get("title"),
        )
        for entity in index.get("entities", [])
        if entity.get("entity_type") == "equipment"
        and entity.get("content_category_id") == "equipment"
        and entity.get("content_subcategory_id") == "equipment_vorax"
    ]


def generate(
    repo: Path = ROOT,
    output_root: Path = DEFAULT_OUTPUT,
    report_path: Path = DEFAULT_REPORT,
    season: str = DEFAULT_SEASON,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    context, output_root, report_path = runner_context(
        repo, season, output_root, report_path, DEFAULT_OUTPUT, DEFAULT_REPORT
    )
    definitions = _definitions(context)
    raw_root = context.readable_raw_manifest_root() / "inventory/raw_html"
    results: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    for definition in definitions:
        result = VoraxEquipmentParser(definition).parse(ParserInput(
            season_id=season,
            system_id="inventory",
            canonical_id=definition.canonical_id,
            canonical_route=definition.route,
            raw_html_path=raw_root / f"{quote(definition.canonical_id, safe='-_.')}.html",
        ))
        result.update({
            "entity_id": f"tlidb:cn:{definition.canonical_id}",
            "entity_type": "vorax_equipment",
            "title": definition.title,
            "route": definition.route,
        })
        results.append(result)
        _write(output_root / "vorax_equipment" / f"{quote(definition.canonical_id, safe='-_.')}.json", result)
        for record in result["records"]:
            document = {
                "record_id": record["record_id"],
                "entity_id": record["entity_id"],
                "entity_title": definition.title,
                "record_type": record["record_type"],
                "section_name": record["section_name"],
                "text": record["text"],
                "route": record["route"],
                "source_locator": record["source_locator"],
                "landing": resolve_record_landing(record),
                "entity_type": "vorax_equipment",
                "content_category_id": "equipment",
                "content_category_name_zh": "装备",
                "content_subcategory_id": "equipment_vorax",
                "content_subcategory_name_zh": "渴瘾装备",
            }
            if "tier" in record:
                document["tier"] = record["tier"]
                document["source_tier_value"] = record["source_locator"].get("tier_value")
            documents.append(document)

    mismatches = [result for result in results if result["structure_validation"]["status"] != "matched"]
    records = [record for result in results for record in result["records"]]
    counts = Counter(record["record_type"] for record in records)
    ids = [record["record_id"] for record in records]
    stable = sum(record["source_locator"]["locator_level"] == "record" for record in records)
    historical = sum(
        result["structure_validation"]["observed"]["historical_card_count"]
        * result["structure_validation"]["observed"]["current_base_stat_count"]
        for result in results
    )
    case_studies = {}
    for slug in ("Vorax_Limb:_Head", "Vorax_Limb:_Legs", "Vorax_Aberrant_Limb:_Digits"):
        selected = [document for document in documents if document["entity_id"] == f"tlidb:cn:{slug}"]
        case_studies[slug] = {
            "records": len(selected),
            "record_types": dict(Counter(item["record_type"] for item in selected)),
            "craft_tiers": sorted({item.get("tier") for item in selected if item["record_type"] == "vorax_craft_affix"}),
            "record_ids_unique": len({item["record_id"] for item in selected}) == len(selected),
        }
    report = {
        "vorax_entities": len(definitions),
        "parsed_entities": len(results) - len(mismatches),
        "structure_matched": len(results) - len(mismatches),
        "structure_mismatches": len(mismatches),
        "record_counts": {
            "vorax_base_stat": counts["vorax_base_stat"],
            "vorax_special_mechanic": counts["vorax_special_mechanic"],
            "vorax_base_affix": counts["vorax_base_affix"],
            "vorax_craft_affix": counts["vorax_craft_affix"],
            "vorax_legendary_quality_affix": counts["vorax_legendary_quality_affix"],
            "total": len(records),
        },
        "unique_record_ids": len(set(ids)),
        "stable_key_coverage": stable / len(records) if records else 0,
        "section_level_records": sum(record["source_locator"]["locator_level"] == "section" for record in records),
        "historical_records_excluded": historical,
        "structured_search_total": len(documents),
        "classification_errors": sum(
            document["content_category_id"] != "equipment"
            or document["content_subcategory_id"] != "equipment_vorax"
            for document in documents
        ),
        "landing": {
            "record_level": stable,
            "section_level": sum(record["source_locator"]["locator_level"] == "section" for record in records),
            "tier_aware": sum(record["record_type"] == "vorax_craft_affix" for record in records),
            "legendary_filter_reset": sum(record["record_type"] == "vorax_legendary_quality_affix" for record in records),
            "historical_collision_protection": "tab/container -> current season -> data-modifier-id",
        },
        "case_studies": case_studies,
        "noise_validation": {
            "ss12_records": sum("SS12" in record["text"] for record in records),
            "item_tab_records": 0,
            "requirement_records": sum("需求等级" in record["text"] for record in records),
            "drop_source_records": sum("Drop Source" in record["text"] for record in records),
            "table_metadata_records": sum(record["text"] in {"Tier", "Level", "Weight", "Library"} for record in records),
        },
        "errors": [result["entity_id"] for result in mismatches]
        + (["record_id collision"] if len(set(ids)) != len(ids) else []),
    }
    index = {
        "schema_version": 1,
        "season_id": season,
        "entity_count": len(results),
        "entities": [{
            "entity_id": result["entity_id"],
            "route": result["route"],
            "record_count": result["record_count"],
            "parser_version": result["parser_version"],
            "structure_status": result["structure_validation"]["status"],
        } for result in results],
        "record_count": len(documents),
        "records": documents,
    }
    _write(output_root / "vorax-equipment-structured-index.json", index)
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
