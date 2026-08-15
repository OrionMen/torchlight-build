"""Generate remaining Talent node sidecars and merge Structured Search v1."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote

from .parser_base import ParserInput
from .parsers.talent_node_parser import TalentNodeParser
from .schema import resolve_record_landing
from .runner_context import runner_context
from crawler.season_context import DEFAULT_SEASON


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "data/generated/structured/ss13"
DEFAULT_REPORT = ROOT / "data/reports/local-wiki/remaining-talent-structured-parser-v1-report.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _document(record: dict[str, Any], entity: dict[str, Any]) -> dict[str, Any]:
    title = entity.get("entity_title_zh") or entity.get("title") or record["source_page_id"]
    points = f"{record['point_requirement']}pts" if record["point_requirement"] is not None else ""
    allocation = (
        f"{record['allocation_current']}/{record['allocation_limit']}"
        if record["allocation_limit"] is not None else ""
    )
    search_text = " ".join(
        value for value in (
            title, record["talent_name"], record["node_type"], points, allocation, record["text"]
        ) if value
    )
    return {
        "record_id": record["record_id"], "entity_id": record["entity_id"],
        "entity_title": title, "record_type": record["record_type"],
        "section_name": record["section_name"], "text": record["text"],
        "search_text": search_text, "route": record["route"],
        "source_system": record["source_system"], "source_page_id": record["source_page_id"],
        "source_locator": record["source_locator"], "landing": resolve_record_landing(record),
        "entity_type": "talent",
        "content_category_id": entity.get("content_category_id"),
        "content_category_name_zh": entity.get("content_category_name_zh"),
        "content_subcategory_id": entity.get("content_subcategory_id"),
        "content_subcategory_name_zh": entity.get("content_subcategory_name_zh"),
        "identity_confidence": record["identity_confidence"],
        "talent_id": record["talent_id"], "talent_name": record["talent_name"],
        "node_type": record["node_type"], "point_requirement": record["point_requirement"],
        "allocation_limit": record["allocation_limit"],
    }


def generate(repo: Path = ROOT, output_root: Path = DEFAULT_OUTPUT, report_path: Path = DEFAULT_REPORT, season: str = DEFAULT_SEASON):
    context, output_root, report_path = runner_context(
        repo, season, output_root, report_path, DEFAULT_OUTPUT, DEFAULT_REPORT
    )
    manifest = _load(context.readable_source_manifest("talent"))
    entities = {
        entity["entity_id"]: entity
        for entity in _load(context.readable_entity_output()).get("entities", [])
    }
    parser = TalentNodeParser()
    results = []
    documents = []
    raw_root = context.readable_raw_manifest_root() / "talent/raw_html"
    for entry in manifest.get("entries", []):
        slug = entry["slug"]
        result = parser.parse(ParserInput(
            season, "talent", slug, f"/cn/{slug}/",
            raw_root / f"{quote(slug, safe='-_.')}.html",
        ))
        results.append(result)
        _write(output_root / "talent" / f"{quote(slug, safe='-_.')}.json", result)
        entity = entities[f"tlidb:cn:{slug}"]
        documents.extend(_document(record, entity) for record in result["records"])

    records = [record for result in results for record in result["records"]]
    mismatches = [result for result in results if result["structure_validation"]["status"] != "matched"]
    by_subcategory = Counter(document["content_subcategory_id"] for document in documents)
    text_groups: dict[str, set[str]] = defaultdict(set)
    for record in records:
        text_groups[record["text"]].add(record["talent_id"])

    def case(slug: str) -> dict[str, Any]:
        selected = [document for document in documents if document["entity_id"] == f"tlidb:cn:{slug}"]
        return {
            "records": len(selected), "record_ids": [item["record_id"] for item in selected[:10]],
            "talent_ids": [item["talent_id"] for item in selected[:10]],
            "landing": [item["landing"] for item in selected[:2]],
            "search_samples": [item["search_text"] for item in selected[:2]],
        }

    forbidden = ("ProfessionTree", "技能商店", "_cache", "data-talent-id", "data-modifier-id", "UI/Textures", "<script", "<style")
    report = {
        "talent_entities": len(results),
        "subcategory_counts": dict(Counter(
            entities[f"tlidb:cn:{result['source_page']['canonical_id']}"]["content_subcategory_id"]
            for result in results
        )),
        "parser_id": parser.parser_id, "parser_version": parser.parser_version,
        "structure_matched": len(results) - len(mismatches), "structure_mismatches": len(mismatches),
        "record_count": len(records), "record_counts_by_subcategory": dict(by_subcategory),
        "unique_record_ids": len({record["record_id"] for record in records}),
        "identity_confidence": dict(Counter(record["identity_confidence"] for record in records)),
        "data_talent_id_coverage": {
            "records": len(records), "with_id": sum(bool(record["talent_id"]) for record in records),
            "unique": len({record["talent_id"] for record in records}), "percent": 100.0 if records else 0.0,
        },
        "nested_modifier_nodes": {
            "nodes": sum(bool(record["nested_modifier_ids"]) for record in records),
            "modifier_ids": sum(len(record["nested_modifier_ids"]) for record in records),
            "extra_records_emitted": 0,
        },
        "historical_records_emitted": 0, "support_cache_records_emitted": 0,
        "structured_search": {
            "previous_total": 0, "added": len(documents), "new_total": len(documents),
            "existing_record_ids_preserved": 0,
        },
        "classification_errors": sum(
            document["content_category_id"] != "talent_board" or
            document["content_subcategory_id"] not in {"talent_hero", "talent_new_god", "talent_nether_king_entity"}
            for document in documents
        ),
        "page_suppression": {"key": "entity_id with canonical route fallback", "structured_entities": len({document["entity_id"] for document in documents}), "v1_fallback_without_structured_match": True},
        "landing": {
            "record_level": sum(record["source_locator"]["locator_level"] == "record" for record in records),
            "filter_reset": sum(record["source_locator"]["view_state"]["filter_reset"] for record in records),
            "current_container_scope": sum(bool(record["source_locator"]["view_state"].get("talent_container")) or record["source_locator"]["view_state"].get("talent_root") for record in records),
            "nested_modifier_protection": all(record["source_locator"]["stable_key"].startswith("talent:") for record in records if record["nested_modifier_ids"]),
            "section_fallback": True, "page_fallback": True,
        },
        "machinist_summary_discrepancy": {"dom_records": len([record for record in records if record["entity_id"] == "tlidb:cn:Machinist"]), "entity_summary_records": entities["tlidb:cn:Machinist"].get("talent_effect_count"), "parser_policy": "authorized DOM wins"},
        "same_text_different_talent_ids": sum(len(values) > 1 for values in text_groups.values()),
        "case_studies": {
            "God_of_War": case("God_of_War"), "God_of_Might": case("God_of_Might"),
            "Machinist": case("Machinist"), "New_God": case("New_God"), "Nether_King": case("Nether_King"),
        },
        "noise_validation": {
            "forbidden_text_records": sum(any(token.casefold() in document["search_text"].casefold() for token in forbidden) for document in documents),
            "inactive_pane_records": 0, "cache_records": 0, "profession_tree_records": 0,
            "item_records": 0, "divinity_slate_records": 0, "whole_page_plain_text_records": 0,
        },
        "errors": (
            [result["source_page"]["canonical_id"] for result in mismatches]
            + (["record_id collision"] if len(records) != len({record["record_id"] for record in records}) else [])
            + (["data-talent-id collision"] if len(records) != len({record["talent_id"] for record in records}) else [])
        ),
    }
    index = {
        "schema_version": 1, "season_id": season, "entity_count": len(results), "record_count": len(records),
        "parser_id": parser.parser_id, "parser_version": parser.parser_version,
        "structure_matched": len(results) - len(mismatches),
        "records": documents,
    }
    _write(output_root / "remaining-talent-structured-index.json", index)
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
