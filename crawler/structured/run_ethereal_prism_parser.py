"""Generate Ethereal Prism sidecar records and merge Structured Search."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

from .parser_base import ParserInput
from .parsers.ethereal_prism_parser import ENTITY_ID, EtherealPrismParser
from .schema import resolve_record_landing
from .runner_context import runner_context
from crawler.season_context import DEFAULT_SEASON


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "data/generated/structured/ss13"
DEFAULT_REPORT = ROOT / "data/reports/local-wiki/ethereal-prism-structured-parser-v1-report.json"


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def generate(
    repo: Path = ROOT,
    output_root: Path = DEFAULT_OUTPUT,
    report_path: Path = DEFAULT_REPORT,
    season: str = DEFAULT_SEASON,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    context, output_root, report_path = runner_context(
        repo, season, output_root, report_path, DEFAULT_OUTPUT, DEFAULT_REPORT
    )
    parser = EtherealPrismParser()
    result = parser.parse(ParserInput(
        season_id=season,
        system_id="inventory",
        canonical_id="Ethereal_Prism",
        canonical_route="/cn/Ethereal_Prism/",
        raw_html_path=context.readable_raw_manifest_root() / "inventory/raw_html/Ethereal_Prism.html",
    ))
    _write(output_root / "ethereal_prism/Ethereal_Prism.json", result)

    documents = []
    for record in result["records"]:
        document = {
            "record_id": record["record_id"],
            "entity_id": ENTITY_ID,
            "entity_title": "异度棱镜",
            "record_type": record["record_type"],
            "section_name": record["section_name"],
            "text": record["text"],
            "search_text": f'{record["text"]} {record["section_name"]}',
            "route": record["route"],
            "source_system": record["source_system"],
            "source_page_id": record["source_page_id"],
            "source_locator": record["source_locator"],
            "landing": resolve_record_landing(record),
            "entity_type": "talent_system",
            "content_category_id": "talent_board",
            "content_category_name_zh": "天赋系统",
            "content_subcategory_id": "talent_ethereal_prism",
            "content_subcategory_name_zh": "异度棱镜",
            "nested_modifier_ids": record["nested_modifier_ids"],
        }
        if "occurrence_location_text" in record:
            document["occurrence_location_text"] = record["occurrence_location_text"]
        documents.append(document)

    records = result["records"]
    counts = Counter(record["record_type"] for record in records)
    ids = [record["record_id"] for record in records]
    base = [record for record in records if record["record_type"] == "ethereal_prism_base_affix"]
    random = [record for record in records if record["record_type"] == "ethereal_prism_random_affix"]
    text_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in random:
        text_groups[record["text"]].append(record)
    duplicate_group = next(group for group in text_groups.values() if len(group) > 1)

    def sample(items: list[dict[str, Any]], predicate) -> dict[str, Any]:
        record = next(item for item in items if predicate(item))
        return {
            "record_id": record["record_id"],
            "stable_key": record["source_locator"]["stable_key"],
            "nested_modifier_ids": record["nested_modifier_ids"],
            "text": record["text"],
            "landing": resolve_record_landing(record),
        }

    mismatch = result["structure_validation"]["status"] != "matched"
    forbidden = ("Calibrate_Ethereal_Prism", "DataTables_Table", "UI_", "<script", "<style", "footer")
    report = {
        "entity": ENTITY_ID,
        "parser_id": parser.parser_id,
        "parser_version": parser.parser_version,
        "structure_matched": int(not mismatch),
        "structure_mismatches": int(mismatch),
        "record_counts": {
            "ethereal_prism_base_affix": counts["ethereal_prism_base_affix"],
            "ethereal_prism_random_affix": counts["ethereal_prism_random_affix"],
            "total": len(records),
        },
        "unique_record_ids": len(set(ids)),
        "outer_stable_key_coverage": sum(record["source_locator"]["locator_level"] == "record" for record in records) / len(records) if records else 0,
        "nested_modifier_rows": {
            "base": sum(bool(record["nested_modifier_ids"]) for record in base),
            "random": sum(bool(record["nested_modifier_ids"]) for record in random),
        },
        "nested_modifier_records_emitted": 0,
        "structured_search": {
            "previous_total": 0,
            "added": len(documents),
            "new_total": len(documents),
        },
        "classification_errors": sum(
            item["content_category_id"] != "talent_board"
            or item["content_subcategory_id"] != "talent_ethereal_prism"
            for item in documents
        ),
        "landing": {
            "base_record_level": sum(record["source_locator"]["locator_level"] == "record" for record in base),
            "random_record_level": sum(record["source_locator"]["locator_level"] == "record" for record in random),
            "nested_modifier_protection": "within selected tbody, find the tr whose first data-modifier-id equals the outer stable key",
            "datatable_ready": sum(record["source_locator"]["view_state"].get("datatable_ready") is True for record in records),
            "filter_reset": 0,
            "fallback": ["record", "section", "page"],
        },
        "noise_validation": {
            "forbidden_text_records": sum(any(token in record["text"] for token in forbidden) for record in records),
            "item_tab_records": 0,
            "calibrate_records": 0,
            "occurrence_location_in_search_text": sum(
                bool(item.get("occurrence_location_text")) and item["occurrence_location_text"] in item["search_text"]
                for item in documents
            ),
            "nested_modifier_records": 0,
        },
        "case_studies": {
            "base_plain": sample(base, lambda item: not item["nested_modifier_ids"]),
            "base_nested": sample(base, lambda item: bool(item["nested_modifier_ids"])),
            "random_plain": sample(random, lambda item: not item["nested_modifier_ids"]),
            "random_nested": sample(random, lambda item: bool(item["nested_modifier_ids"])),
            "same_text_different_outer_modifier": {
                "text": duplicate_group[0]["text"],
                "record_count": len(duplicate_group),
                "record_ids": [item["record_id"] for item in duplicate_group],
                "outer_stable_keys": [item["source_locator"]["stable_key"] for item in duplicate_group],
            },
        },
        "errors": (["structure_mismatch"] if mismatch else [])
        + (["record_id collision"] if len(ids) != len(set(ids)) else []),
    }
    index = {
        "schema_version": 1,
        "season_id": season,
        "entity_count": 1,
        "entity_id": ENTITY_ID,
        "record_count": len(records),
        "parser_id": parser.parser_id,
        "parser_version": parser.parser_version,
        "structure_status": result["structure_validation"]["status"],
        "structure_signature": result["structure_signature"],
        "records": documents,
    }
    _write(output_root / "ethereal-prism-structured-index.json", index)
    _write(report_path, report)
    return result, index, report


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
