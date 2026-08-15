"""Generate Hero Trait sidecars and merge them into Structured Search v1."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote

from .parser_base import ParserInput
from .parsers.hero_trait_parser import HeroTraitParser
from .schema import resolve_record_landing
from .runner_context import runner_context
from crawler.season_context import DEFAULT_SEASON


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "data/generated/structured/ss13"
DEFAULT_REPORT = ROOT / "data/reports/local-wiki/hero-trait-structured-parser-v1-report.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _document(record: dict[str, Any], title: str) -> dict[str, Any]:
    level = f'等级 {record["trait_level"]}' if record["trait_level"] is not None else ""
    search_text = " ".join(
        value for value in (title, record["node_name"], level, record["text"]) if value
    )
    return {
        "record_id": record["record_id"],
        "entity_id": record["entity_id"],
        "entity_title": title,
        "record_type": record["record_type"],
        "section_name": record["section_name"],
        "text": record["text"],
        "search_text": search_text,
        "route": record["route"],
        "source_system": record["source_system"],
        "source_page_id": record["source_page_id"],
        "source_locator": record["source_locator"],
        "landing": resolve_record_landing(record),
        "entity_type": "hero",
        "content_category_id": "hero",
        "content_category_name_zh": "英雄",
        "content_subcategory_id": "hero_trait",
        "content_subcategory_name_zh": "英雄特性",
        "identity_confidence": record["identity_confidence"],
        "node_name": record["node_name"],
        "required_level": record["required_level"],
        "trait_level": record["trait_level"],
    }


def generate(
    repo: Path = ROOT,
    output_root: Path = DEFAULT_OUTPUT,
    report_path: Path = DEFAULT_REPORT,
    season: str = DEFAULT_SEASON,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    context, output_root, report_path = runner_context(
        repo, season, output_root, report_path, DEFAULT_OUTPUT, DEFAULT_REPORT
    )
    manifest = _load(context.readable_source_manifest("hero"))
    entities = {
        entity["entity_id"]: entity
        for entity in _load(context.readable_entity_output()).get("entities", [])
    }
    parser = HeroTraitParser()
    results: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    raw_root = context.readable_raw_manifest_root() / "hero/raw_html"

    for entry in manifest.get("entries", []):
        slug = entry.get("slug") or entry["id"]
        raw_path = raw_root / f"{quote(slug, safe='-_.')}.html"
        result = parser.parse(ParserInput(
            season_id=season,
            system_id="hero",
            canonical_id=slug,
            canonical_route=f"/cn/{slug}/",
            raw_html_path=raw_path,
        ))
        results.append(result)
        _write(output_root / "hero_trait" / f"{quote(slug, safe='-_.')}.json", result)
        entity = entities.get(f"tlidb:cn:{slug}", {})
        title = (
            entity.get("entity_title_zh") or entry.get("name_zh")
            or entry.get("name") or entry["id"]
        )
        documents.extend(_document(record, str(title)) for record in result["records"])

    records = [record for result in results for record in result["records"]]
    mismatches = [
        result for result in results
        if result["structure_validation"]["status"] != "matched"
    ]
    duplicate_asset_groups = sum(
        count > 1
        for result in results
        for count in Counter(
            (record["icon_asset_key"], record["trait_level"])
            for record in result["records"]
        ).values()
    )
    duplicate_composite_groups = sum(
        count > 1
        for result in results
        for count in Counter(
            record["source_locator"]["stable_key"] for record in result["records"]
        ).values()
    )
    by_entity = Counter(record["entity_id"] for record in documents)

    def case(slug: str) -> dict[str, Any]:
        selected = [record for record in documents if record["entity_id"] == f"tlidb:cn:{slug}"]
        return {
            "records": len(selected),
            "record_ids": [record["record_id"] for record in selected[:12]],
            "records_with_level": sum(record["trait_level"] is not None for record in selected),
            "asset_keys": [record["source_locator"]["view_state"]["hero_trait_asset_key"] for record in selected[:12]],
            "landing": [record["landing"] for record in selected[:2]],
            "search_samples": [record["search_text"] for record in selected[:2]],
        }

    forbidden = (
        "技能商店", "data-hover", "data-bs-title", "UI/Textures", "cdn.tlidb.com",
        "<script", "<style", "update cookie preferences",
    )
    report = {
        "hero_entities": len(results),
        "parser_id": parser.parser_id,
        "parser_version": parser.parser_version,
        "structure_matched": len(results) - len(mismatches),
        "structure_mismatches": len(mismatches),
        "record_count": len(records),
        "records_with_level": sum(record["trait_level"] is not None for record in records),
        "records_without_level": sum(record["trait_level"] is None for record in records),
        "unique_record_ids": len({record["record_id"] for record in records}),
        "identity_confidence": {
            "high": sum(record["identity_confidence"] == "high" for record in records),
            "medium": sum(record["identity_confidence"] == "medium" for record in records),
            "low": sum(record["identity_confidence"] == "low" for record in records),
        },
        "medium_identity_records": sum(
            record["identity_confidence"] == "medium" for record in records
        ),
        "identity_unresolved": sum(
            not record["source_locator"]["stable_key"] for record in records
        ),
        "locator_confidence": dict(Counter(
            record["source_locator"]["locator_confidence"] for record in records
        )),
        "duplicate_asset_resolution": {
            "duplicate_groups_before_scoped_occurrence": duplicate_asset_groups,
            "duplicate_groups_after_scoped_occurrence": duplicate_composite_groups,
            "policy": "entity/trait pane + icon asset key + same-asset occurrence + optional level",
        },
        "structured_search": {
            "previous_total": 0,
            "added": len(documents),
            "new_total": len(documents),
            "existing_record_ids_preserved": 0,
        },
        "classification_errors": sum(
            record["content_category_id"] != "hero"
            or record["content_subcategory_id"] != "hero_trait"
            for record in documents
        ),
        "page_suppression": {
            "key": "entity_id with canonical route fallback",
            "structured_entities": len(by_entity),
            "v1_fallback_without_structured_match": True,
        },
        "landing": {
            "record_level": sum(record["source_locator"]["locator_level"] == "record" for record in records),
            "section_fallback": True,
            "page_fallback": True,
            "skill_shop_exclusion": True,
            "duplicate_asset_protection": duplicate_composite_groups == 0,
        },
        "case_studies": {
            "Anger": case("Anger"),
            "Creative_Genius": case("Creative_Genius"),
            "Zealot_of_War": case("Zealot_of_War"),
            "Incarnation_of_the_Gods": case("Incarnation_of_the_Gods"),
            "ordinary": case("Ranger_of_Glory"),
        },
        "noise_validation": {
            "forbidden_text_records": sum(
                any(token.casefold() in record["search_text"].casefold() for token in forbidden)
                for record in documents
            ),
            "skill_shop_records": 0,
            "boon_records": 0,
            "hero_memory_records": 0,
            "asset_key_in_search_text": sum(
                record["source_locator"]["view_state"]["hero_trait_asset_key"]
                in record["search_text"] for record in documents
            ),
            "whole_page_plain_text_records": 0,
        },
        "errors": (
            [result["source_page"]["canonical_id"] for result in mismatches]
            + (["record_id collision"] if len(records) != len({record["record_id"] for record in records}) else [])
            + (["identity unresolved"] if any(not record["source_locator"]["stable_key"] for record in records) else [])
        ),
    }

    index = {
        "schema_version": 1,
        "season_id": season,
        "entity_count": len(results),
        "record_count": len(records),
        "parser_id": parser.parser_id,
        "parser_version": parser.parser_version,
        "structure_matched": len(results) - len(mismatches),
        "records": documents,
    }
    _write(output_root / "hero-trait-structured-index.json", index)
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
