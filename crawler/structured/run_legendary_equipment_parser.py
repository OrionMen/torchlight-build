"""Generate the season-scoped Legendary Equipment Structured module."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote

from crawler.audit_legendary_structured_dom_v1 import build_audit
from crawler.recover_legendary_refetch_v1 import NON_EQUIPMENT_IDS
from crawler.season_context import DEFAULT_SEASON

from .parser_base import ParserInput
from .parsers import LegendaryDefinition, LegendaryEquipmentParser
from .runner_context import runner_context
from .schema import resolve_record_landing


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "data/generated/structured/ss13"
DEFAULT_REPORT = ROOT / "data/reports/local-wiki/legendary-structured-parser-v1-report.json"


class LegendaryStructuredGenerationError(RuntimeError):
    """Raised before publishing an invalid Legendary module index."""


def write_atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        json.loads(temporary.read_text(encoding="utf-8"))
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _validate_entity_coverage(context, definitions: list[LegendaryDefinition]) -> dict[str, Any]:
    if not definitions:
        raise LegendaryStructuredGenerationError(
            "Legendary source manifest contains no equipment definitions"
        )
    entity_path = context.readable_entity_output()
    entity_index = json.loads(entity_path.read_text(encoding="utf-8"))
    entities = {
        item["entity_id"]: item for item in entity_index.get("entities", [])
        if item.get("entity_type") == "legendary_equipment"
    }
    expected = {f"tlidb:cn:{item.canonical_id}" for item in definitions}
    actual = set(entities)
    classification_errors = sorted(
        entity_id for entity_id, item in entities.items()
        if item.get("content_category_id") != "equipment"
        or item.get("content_subcategory_id") != "equipment_legendary"
    )
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra or classification_errors:
        raise LegendaryStructuredGenerationError(
            "Legendary Entity coverage mismatch: "
            f"missing={len(missing)}, extra={len(extra)}, "
            f"classification_errors={len(classification_errors)}"
        )
    return {
        "entity_index": str(entity_path),
        "entity_count": len(entities),
        "classification_errors": classification_errors,
    }


def generate(
    repo: Path = ROOT,
    output_root: Path = DEFAULT_OUTPUT,
    report_path: Path = DEFAULT_REPORT,
    season: str = DEFAULT_SEASON,
):
    context, output_root, report_path = runner_context(
        repo, season, output_root, report_path, DEFAULT_OUTPUT, DEFAULT_REPORT
    )
    manifest_path = context.readable_source_manifest("legendary_gear")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    definitions = [
        LegendaryDefinition(entry["id"], entry.get("name_zh") or entry["id"])
        for entry in manifest["entries"] if entry["id"] not in NON_EQUIPMENT_IDS
    ]
    entity_coverage = _validate_entity_coverage(context, definitions)
    raw_root = context.readable_raw_manifest_root() / "legendary_gear/raw_html"

    results = []
    docs = []
    for definition in definitions:
        parser = LegendaryEquipmentParser(definition)
        result = parser.parse(ParserInput(
            season,
            "legendary_gear",
            definition.canonical_id,
            definition.route,
            raw_root / f"{quote(definition.canonical_id, safe='-_.')}.html",
        ))
        result.update({
            "entity_id": f"tlidb:cn:{definition.canonical_id}",
            "entity_type": "legendary_equipment",
            "title": definition.title,
            "route": definition.route,
        })
        results.append(result)
        for record in result["records"]:
            docs.append({
                "record_id": record["record_id"],
                "entity_id": record["entity_id"],
                "entity_title": definition.title,
                "record_type": record["record_type"],
                "section_name": record["section_name"],
                "text": record["text"],
                "route": record["route"],
                "source_locator": record["source_locator"],
                "landing": resolve_record_landing(record),
                "entity_type": "legendary_equipment",
                "content_category_id": "equipment",
                "content_category_name_zh": "装备",
                "content_subcategory_id": "equipment_legendary",
                "content_subcategory_name_zh": "传奇装备",
            })

    mismatches = [
        result["entity_id"] for result in results
        if result["structure_validation"]["status"] != "matched"
    ]
    ids = [record["record_id"] for record in docs]
    duplicate_record_ids = len(ids) - len(set(ids))
    stable = sum(bool(record["source_locator"].get("stable_key")) for record in docs)
    historical_text_records = sum("SS12" in record["text"] for record in docs)
    if mismatches:
        raise LegendaryStructuredGenerationError(
            f"Legendary structure mismatch: {len(mismatches)} entities"
        )
    if duplicate_record_ids:
        raise LegendaryStructuredGenerationError(
            f"duplicate Legendary record IDs: {duplicate_record_ids}"
        )
    if stable != len(docs):
        raise LegendaryStructuredGenerationError(
            f"Legendary stable-key coverage mismatch: {stable}/{len(docs)}"
        )
    if historical_text_records:
        raise LegendaryStructuredGenerationError(
            f"historical Legendary records entered output: {historical_text_records}"
        )

    audit = None
    audit_warnings: list[str] = []
    try:
        audit = build_audit(repo, season)
        audit_warnings.extend(audit.get("warnings", []))
        audit_warnings.extend(
            f"optional DOM audit: {error}" for error in audit.get("errors", [])
        )
    except Exception as exc:  # Diagnostic enrichment must not own production.
        audit_warnings.append(
            f"optional DOM audit unavailable: {type(exc).__name__}: {exc}"
        )

    counts = Counter(record["record_type"] for record in docs)
    historical_excluded = sum(
        result["structure_validation"]["observed"].get("historical_modifier_count", 0)
        for result in results
    )
    index = {
        "schema_version": 1,
        "season_id": season,
        "entity_count": len(results),
        "entities": [{
            "entity_id": result["entity_id"],
            "route": result["route"],
            "record_count": result["record_count"],
            "structure_status": result["structure_validation"]["status"],
        } for result in results],
        "record_count": len(docs),
        "records": docs,
    }
    cases = {}
    for slug in (
        "Necklace_of_Firebird", "Enamor", "Frantic_Shadow", "Crosser", "Unholy_Prayer"
    ):
        selected = [doc for doc in docs if doc["entity_id"] == f"tlidb:cn:{slug}"]
        cases[slug] = {
            "records": len(selected),
            "record_types": dict(Counter(doc["record_type"] for doc in selected)),
            "record_ids_unique": len({doc["record_id"] for doc in selected}) == len(selected),
        }
    report = {
        "legendary_entities": len(definitions),
        "parsed_entities": len(results),
        "template_groups": audit.get("template_groups", []) if audit else [],
        "structure_matched": len(results),
        "structure_mismatches": 0,
        "record_counts": {
            "legendary_base_stat": counts["legendary_base_stat"],
            "legendary_affix": counts["legendary_affix"],
            "legendary_corruption_effect": counts["legendary_corruption_effect"],
            "total": len(docs),
        },
        "unique_record_ids": len(set(ids)),
        "stable_key_coverage": stable / len(docs) if docs else 0,
        "historical_records_excluded": historical_excluded,
        "structured_search_total": len(docs),
        "classification_errors": 0,
        "entity_coverage": entity_coverage,
        "audit": {
            "status": "available" if audit else "unavailable",
            "input_paths": audit.get("input_paths") if audit else None,
            "case_study_selection": audit.get("case_study_selection") if audit else None,
            "warnings": audit_warnings,
        },
        "landing": {
            "record_level": sum(
                doc["source_locator"]["locator_level"] == "record" for doc in docs
            ),
            "current_card": sum(
                doc["source_locator"]["legendary_state"] == "current" for doc in docs
            ),
            "corruption_card": sum(
                doc["source_locator"]["legendary_state"] == "corruption" for doc in docs
            ),
            "historical_collision_protection": "container-scoped data-modifier-id lookup",
        },
        "case_studies": cases,
        "noise_validation": {
            "ss12_text_records": historical_text_records,
            "requirement_records": sum("需求等级" in doc["text"] for doc in docs),
            "lore_records": 0,
            "drop_source_records": sum("Drop Source" in doc["text"] for doc in docs),
        },
        "warnings": audit_warnings,
        "errors": [],
    }

    # Validate everything in memory first. Sidecars are diagnostic artifacts;
    # the module index is the authoritative publication and is written last.
    for result in results:
        slug = result["entity_id"].removeprefix("tlidb:cn:")
        write_atomic_json(output_root / "legendary_equipment" / f"{slug}.json", result)
    write_atomic_json(report_path, report)
    write_atomic_json(output_root / "legendary-equipment-structured-index.json", index)
    return results, index, report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    generate(args.repo.resolve(), args.output_root, args.report, args.season)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
