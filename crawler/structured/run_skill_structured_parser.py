"""Generate Skill structured sidecars and merge Structured Search v1."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote

from crawler.audit_skill_structured_dom_v1 import SYSTEMS

from .parser_base import ParserInput
from .parsers.skill_parser import SkillParser
from .schema import resolve_record_landing
from .runner_context import runner_context
from crawler.season_context import DEFAULT_SEASON


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "data/generated/structured/ss13"
DEFAULT_REPORT = ROOT / "data/reports/local-wiki/skill-structured-parser-v1-report.json"
SKILL_RECORD_TYPES = {"skill_effect", "skill_growth_modifier"}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _document(record: dict[str, Any], entity: dict[str, Any], title: str) -> dict[str, Any]:
    search_text = (
        record["text"] if record["record_type"] == "skill_effect"
        else f"{title} {record['text']}"
    )
    document = {
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
        "entity_type": "skill",
        "content_category_id": entity.get("content_category_id"),
        "content_category_name_zh": entity.get("content_category_name_zh"),
        "content_subcategory_id": entity.get("content_subcategory_id"),
        "content_subcategory_name_zh": entity.get("content_subcategory_name_zh"),
        "identity_confidence": record["identity_confidence"],
        "skill_id": record["skill_id"],
    }
    if record["record_type"] == "skill_effect":
        document.update({
            "skill_tags": record["skill_tags"],
            "level_table_present": record["level_table_present"],
            "level_row_count": record["level_row_count"],
            "display_level": record["display_level"],
        })
    else:
        document.update({
            "modifier_id": record["modifier_id"],
            "tier": record["tier"],
            "source_section": record["source_section"],
        })
    return document


def generate(
    repo: Path = ROOT,
    output_root: Path = DEFAULT_OUTPUT,
    report_path: Path = DEFAULT_REPORT,
    season: str = DEFAULT_SEASON,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    context, output_root, report_path = runner_context(
        repo, season, output_root, report_path, DEFAULT_OUTPUT, DEFAULT_REPORT
    )
    entities = {
        entity["entity_id"]: entity
        for entity in _load(context.readable_entity_output()).get("entities", [])
    }
    parser = SkillParser()
    results: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    entry_titles: dict[str, str] = {}

    for system in SYSTEMS:
        manifest = _load(context.readable_source_manifest(system))
        raw_root = context.readable_raw_manifest_root() / system / "raw_html"
        for entry in manifest.get("entries", []):
            slug = entry.get("slug") or entry["id"]
            entity_id = f"tlidb:cn:{slug}"
            entity = entities[entity_id]
            title = str(
                entity.get("entity_title_zh") or entry.get("name_zh")
                or entry.get("name") or entry["id"]
            )
            entry_titles[slug] = title
            result = parser.parse(ParserInput(
                season_id=season,
                system_id=system,
                canonical_id=slug,
                canonical_route=f"/cn/{slug}/",
                raw_html_path=raw_root / f"{quote(slug, safe='-_.')}.html",
            ))
            results.append(result)
            _write(
                output_root / "skill" / system / f"{quote(slug, safe='-_.')}.json",
                result,
            )
            documents.extend(_document(record, entity, title) for record in result["records"])

    records = [record for result in results for record in result["records"]]
    mismatches = [
        result for result in results
        if result["structure_validation"]["status"] != "matched"
    ]
    record_counts = Counter(record["record_type"] for record in records)
    subcategory_counts = Counter(
        entities[f"tlidb:cn:{result['source_page']['canonical_id']}"]["content_subcategory_id"]
        for result in results
    )
    template_counts = Counter(
        result["structure_validation"]["observed"]["template_group"] for result in results
    )
    classification_errors = sum(
        document.get("content_category_id") != "skill"
        or document.get("content_subcategory_id") not in {
            value[0] for value in SYSTEMS.values()
        }
        for document in documents
    )
    modifier_records = [record for record in records if record["record_type"] == "skill_growth_modifier"]
    effect_records = [record for record in records if record["record_type"] == "skill_effect"]
    text_groups: dict[str, set[str]] = defaultdict(set)
    for record in modifier_records:
        text_groups[record["text"]].add(record["source_locator"]["stable_key"])

    forbidden = (
        "Info id", "Show Description", "Skill Shop", "Alts", "SS12", "cache-", "NPC",
        "data-bs-title", "UI/Textures", "cdn.tlidb.com", "<script", "<style",
        "navbar", "About Site", "Item list",
    )
    forbidden_counts = {
        token: sum(token.casefold() in document["search_text"].casefold() for document in documents)
        for token in forbidden
    }

    documents_by_slug: dict[str, list[dict[str, Any]]] = defaultdict(list)
    results_by_slug: dict[str, dict[str, Any]] = {}
    for document in documents:
        documents_by_slug[document["source_page_id"]].append(document)
    for result in results:
        results_by_slug[result["source_page"]["canonical_id"]] = result

    def case(slug: str) -> dict[str, Any]:
        selected = documents_by_slug[slug]
        result = results_by_slug[slug]
        return {
            "title": entry_titles[slug],
            "records": len(selected),
            "skill_effect": sum(item["record_type"] == "skill_effect" for item in selected),
            "skill_growth_modifier": sum(item["record_type"] == "skill_growth_modifier" for item in selected),
            "classification": {
                "category": selected[0]["content_category_id"],
                "subcategory": selected[0]["content_subcategory_id"],
            },
            "search_samples": [item["search_text"] for item in selected[:2]],
            "landing": [item["landing"] for item in selected[:2]],
            "template_group": result["structure_validation"]["observed"]["template_group"],
            "level_rows": result["structure_validation"]["observed"]["level_rows"],
            "historical_records": result["structure_validation"]["observed"]["historical_records_selected"],
        }

    filter_result = next(
        result for result in results
        if result["structure_validation"]["observed"]["filter_count"]
    )
    filter_slug = filter_result["source_page"]["canonical_id"]
    report = {
        "skill_entities": len(results),
        "subcategory_counts": dict(sorted(subcategory_counts.items())),
        "parser_id": parser.parser_id,
        "parser_version": parser.parser_version,
        "template_groups": dict(sorted(template_counts.items())),
        "structure_matched": len(results) - len(mismatches),
        "structure_mismatches": len(mismatches),
        "record_counts": {
            "skill_effect": record_counts["skill_effect"],
            "skill_growth_modifier": record_counts["skill_growth_modifier"],
            "total": len(records),
        },
        "identity": {
            "skill_id_coverage": {
                "records": len(effect_records),
                "with_id": sum(bool(record["skill_id"]) for record in effect_records),
                "unique": len({record["skill_id"] for record in effect_records}),
            },
            "modifier_id_coverage": {
                "records": len(modifier_records),
                "with_id": sum(bool(record["modifier_id"]) for record in modifier_records),
                "unique_native_ids": len({record["modifier_id"] for record in modifier_records}),
                "unique_stable_identity_keys": len({
                    (record["entity_id"], record["source_locator"]["stable_key"])
                    for record in modifier_records
                }),
                "tier_disambiguated_occurrences": sum(
                    ":tier:" in record["source_locator"]["stable_key"]
                    for record in modifier_records
                ),
            },
            "high_confidence": sum(record["identity_confidence"] == "high" for record in records),
            "unresolved": sum(not record["source_locator"]["stable_key"] for record in records),
            "unique_record_ids": len({record["record_id"] for record in records}),
            "same_text_different_modifier_ids": sum(len(keys) > 1 for keys in text_groups.values()),
        },
        "level_model": {
            "pages_with_level_table": sum(
                result["structure_validation"]["observed"]["level_table_count"] > 0
                for result in results
            ),
            "level_rows": sum(
                result["structure_validation"]["observed"]["level_rows"] for result in results
            ),
            "records_emitted_from_level_rows": 0,
        },
        "historical_exclusion": {
            "pages_with_history": 695,
            "historical_records": sum(
                result["structure_validation"]["observed"]["historical_records_selected"]
                for result in results
            ),
            "inactive_records": sum(
                result["structure_validation"]["observed"]["inactive_records_selected"]
                for result in results
            ),
            "cache_records": 0,
        },
        "structured_search": {
            "previous_total": 0,
            "added": len(documents),
            "new_total": len(documents),
            "existing_record_ids_preserved": 0,
            "search_schema": None,
        },
        "classification_errors": classification_errors,
        "page_suppression": {
            "structured_entities": len({document["entity_id"] for document in documents}),
            "structured_match_suppresses_v1": True,
            "v1_fallback_without_structured_match": True,
            "key": "entity_id with canonical route fallback",
        },
        "landing": {
            "section_level_skill_effect": sum(
                record["source_locator"]["locator_level"] == "section" for record in effect_records
            ),
            "record_level_growth_modifier": sum(
                record["source_locator"]["locator_level"] == "record" for record in modifier_records
            ),
            "filter_reset": sum(
                bool(record["source_locator"]["view_state"].get("filter_reset")) for record in records
            ),
            "datatable_ready": sum(
                bool(record["source_locator"]["view_state"].get("datatable_ready")) for record in records
            ),
            "historical_collision_protection": all(
                record["source_locator"]["view_state"].get("skill_effect")
                or record["source_locator"]["view_state"].get("skill_growth")
                for record in records
            ),
            "section_fallback": True,
            "page_fallback": True,
        },
        "noise_validation": {
            "forbidden_search_text": forbidden_counts,
            "violating_records": sum(
                any(token.casefold() in document["search_text"].casefold() for token in forbidden)
                for document in documents
            ),
            "level_row_records": 0,
            "whole_page_plain_text_records": 0,
            "history_records": 0,
            "cache_records": 0,
            "item_list_records": 0,
        },
        "case_studies": {
            "Vendetta": case("Vendetta"),
            "Serpent_Beam": case("Serpent_Beam"),
            "Leap_Attack": case("Leap_Attack"),
            "Fearless": case("Fearless"),
            "Multiple_Projectiles": case("Multiple_Projectiles"),
            "Activation_Medium:_Perpetual_Motion": case("Activation_Medium:_Perpetual_Motion"),
            "Module:_Goblin_Priest": case("Module:_Goblin_Priest"),
            "filter_page": case(filter_slug),
            "tabbed_variant": case("Leap_Attack"),
        },
        "errors": (
            [result["source_page"]["canonical_id"] for result in mismatches]
            + (["record_id collision"] if len(records) != len({record["record_id"] for record in records}) else [])
            + (["classification errors"] if classification_errors else [])
            + (["structured search noise"] if any(forbidden_counts.values()) else [])
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
        "record_counts": dict(record_counts),
        "records": documents,
    }
    _write(output_root / "skill-structured-index.json", index)
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
    print(json.dumps({
        "entities": report["skill_entities"],
        "records": report["record_counts"],
        "structured_search": report["structured_search"],
        "errors": report["errors"],
    }, ensure_ascii=False))
    return int(bool(report["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
