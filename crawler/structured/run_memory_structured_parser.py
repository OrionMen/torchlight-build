"""Generate Memory structured sidecars and merge them into Structured Search."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from .parser_base import ParserInput
from .parsers.memory_structured_parser import (
    ENTITY_ID,
    MEMORY_SOURCES,
    MemoryStructuredParser,
)
from .schema import resolve_record_landing
from .runner_context import runner_context
from crawler.season_context import DEFAULT_SEASON


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "data/generated/structured/ss13"
DEFAULT_REPORT = ROOT / "data/reports/local-wiki/memory-structured-parser-v1-report.json"


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
    for definition in MEMORY_SOURCES:
        raw = context.readable_raw_manifest_root() / definition.system_id / "raw_html" / f"{definition.canonical_id}.html"
        result = MemoryStructuredParser(definition).parse(ParserInput(
            season_id=season,
            system_id=definition.system_id,
            canonical_id=definition.canonical_id,
            canonical_route=definition.route,
            raw_html_path=raw,
        ))
        results.append(result)
        _write(output_root / "memory" / f"{definition.canonical_id}.json", result)
        for record in result["records"]:
            documents.append({
                "record_id": record["record_id"],
                "entity_id": ENTITY_ID,
                "entity_title": "英雄追忆",
                "record_type": record["record_type"],
                "section_name": record["section_name"],
                "text": record["text"],
                "route": record["route"],
                "source_system": record["source_system"],
                "source_page_id": record["source_page_id"],
                "source_locator": record["source_locator"],
                "landing": resolve_record_landing(record),
                "entity_type": "memory_system",
                "content_category_id": "memory",
                "content_category_name_zh": "追忆",
                "content_subcategory_id": "hero_memory",
                "content_subcategory_name_zh": "英雄追忆",
            })

    records = [record for result in results for record in result["records"]]
    counts = Counter(record["record_type"] for record in records)
    ids = [record["record_id"] for record in records]
    mismatches = [result for result in results if result["structure_validation"]["status"] != "matched"]
    correct_revival = sum(
        record["route"] == "/cn/Memory_Revival/"
        for record in records
        if record["record_type"] in {"memory_revival_affix", "memory_revival_moon_affix"}
    )
    forbidden = ("Info id", "Show Description", "Tier name", "Item", "Drop Source")
    case_studies = {}
    for record_type in (
        "memory_base_attribute", "memory_fixed_affix", "memory_random_affix",
        "memory_revival_affix", "memory_revival_moon_affix",
    ):
        sample = next(record for record in documents if record["record_type"] == record_type)
        case_studies[record_type] = {
            "record_id": sample["record_id"],
            "text": sample["text"],
            "route": sample["route"],
            "source_page_id": sample["source_page_id"],
            "stable_key": sample["source_locator"]["stable_key"],
            "landing": sample["landing"],
        }
    all_attribute_matches = [document for document in documents if "全属性" in document["text"]]
    report = {
        "memory_entities": 1,
        "source_pages": 2,
        "structure_matched": len(results) - len(mismatches),
        "structure_mismatches": len(mismatches),
        "record_counts": {
            "memory_base_attribute": counts["memory_base_attribute"],
            "memory_fixed_affix": counts["memory_fixed_affix"],
            "memory_random_affix": counts["memory_random_affix"],
            "memory_revival_affix": counts["memory_revival_affix"],
            "memory_revival_moon_affix": counts["memory_revival_moon_affix"],
            "total": len(records),
        },
        "unique_record_ids": len(set(ids)),
        "stable_key_coverage": sum(bool(record["source_locator"]["stable_key"]) for record in records) / len(records) if records else 0,
        "record_level_locators": sum(record["source_locator"]["locator_level"] == "record" for record in records),
        "structured_search_total": len(documents),
        "classification_errors": sum(
            document["content_category_id"] != "memory"
            or document["content_subcategory_id"] != "hero_memory"
            for document in documents
        ),
        "supplemental_source_landing": {
            "hero_memory_route": "/cn/Hero_Memories/",
            "revival_route": "/cn/Memory_Revival/",
            "correct_route_count": correct_revival,
        },
        "landing": {
            "base_attribute": counts["memory_base_attribute"],
            "fixed_affix": counts["memory_fixed_affix"],
            "random_affix": counts["memory_random_affix"],
            "revival_affix": counts["memory_revival_affix"],
            "revival_moon_affix": counts["memory_revival_moon_affix"],
            "contract": "activate tab -> wait shown.bs.tab -> section-scoped modifier lookup -> scroll -> highlight",
        },
        "noise_validation": {
            "forbidden_text_records": sum(any(token in record["text"] for token in forbidden) for record in records),
            "non_whitelisted_section_records": sum(
                record["section_id"] not in {
                    "base_attribute", "fixed_affix", "random_affix",
                    "revival_affix", "revival_moon_affix",
                }
                for record in records
            ),
            "metadata_column_records": sum(record["text"] in {"Tier", "Level", "Weight", "来源"} for record in records),
        },
        "case_studies": {
            **case_studies,
            "all_attribute_search": {
                "query": "全属性",
                "match_count": len(all_attribute_matches),
                "record_types": dict(Counter(item["record_type"] for item in all_attribute_matches)),
                "routes": sorted({item["route"] for item in all_attribute_matches}),
            },
        },
        "errors": [result["source_page"]["canonical_id"] for result in mismatches]
        + (["record_id collision"] if len(set(ids)) != len(ids) else []),
    }
    index = {
        "schema_version": 1,
        "season_id": season,
        "entity_count": 1,
        "source_page_count": len(results),
        "entity_id": ENTITY_ID,
        "record_count": len(records),
        "parser_id": MemoryStructuredParser.parser_id,
        "parser_version": MemoryStructuredParser.parser_version,
        "sources": [{
            "source_page_id": result["source_page"]["canonical_id"],
            "route": result["source_page"]["canonical_route"],
            "record_count": result["record_count"],
            "structure_status": result["structure_validation"]["status"],
            "structure_signature": result["structure_signature"],
        } for result in results],
        "records": documents,
    }
    _write(output_root / "memory-structured-index.json", index)
    _write(report_path, report)
    return results, index, report


def _load_index(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": 1, "season_id": DEFAULT_SEASON, "records": []}
    return json.loads(path.read_text(encoding="utf-8"))


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
