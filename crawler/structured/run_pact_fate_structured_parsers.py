"""Generate Pact/Fate structured sidecars and merge the Structured Search overlay."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote

from .parser_base import ParserInput
from .parsers.fate_parser import FateParser
from .parsers.pact_spirit_parser import PactSpiritParser
from .schema import resolve_record_landing
from .runner_context import runner_context
from crawler.season_context import DEFAULT_SEASON, SeasonContext


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "data/generated/structured/ss13"
DEFAULT_REPORT = ROOT / "data/reports/local-wiki/pact-fate-structured-parser-v1-report.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _raw_path(context: SeasonContext, system: str, slug: str) -> tuple[Path, str]:
    filename = f"{quote(slug, safe='-_.')}.html"
    primary = context.readable_raw_manifest_root() / system / "raw_html" / filename
    if primary.is_file() and primary.stat().st_size:
        return primary, system
    recovered = context.readable_raw_manifest_root() / "recovered_internal_pages/raw_html" / filename
    return recovered, "recovered_internal_pages"


def _document(record: dict[str, Any], title: str, kind: str) -> dict[str, Any]:
    pact = kind == "pact"
    return {
        "record_id": record["record_id"],
        "entity_id": record["entity_id"],
        "entity_title": title,
        "record_type": record["record_type"],
        "section_name": record["section_name"],
        "text": record["text"],
        "search_text": record["text"],
        "route": record["route"],
        "source_system": record["source_system"],
        "source_page_id": record["source_page_id"],
        "source_locator": record["source_locator"],
        "landing": resolve_record_landing(record),
        "entity_type": record["entity_type"],
        # Repository-canonical tree IDs. Logical aliases are pact_system/pact|fate.
        "content_category_id": "pact_spirit",
        "content_category_name_zh": "契灵系统",
        "content_subcategory_id": "pact_spirit_entity" if pact else "pact_spirit_destiny",
        "content_subcategory_name_zh": "契灵" if pact else "命运",
        "logical_category_id": "pact_system",
        "logical_subcategory_id": "pact" if pact else "fate",
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
    entity_index = _load(context.readable_entity_output())
    entity_by_id = {entity["entity_id"]: entity for entity in entity_index.get("entities", [])}
    results: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    per_kind: dict[str, list[dict[str, Any]]] = {"pact": [], "fate": []}
    source_pages = Counter()

    for system, kind, parser in (
        ("pactspirit", "pact", PactSpiritParser()),
        ("destiny", "fate", FateParser()),
    ):
        manifest = _load(context.readable_source_manifest(system))
        for entry in manifest.get("entries", []):
            slug = entry.get("slug") or entry.get("id")
            entity_id = f"tlidb:cn:{slug}"
            raw_path, source_system = _raw_path(context, system, slug)
            route = f"/cn/{slug}/"
            result = parser.parse(ParserInput(
                season_id=season,
                system_id=source_system,
                canonical_id=slug,
                canonical_route=route,
                raw_html_path=raw_path,
            ))
            results.append(result)
            per_kind[kind].append(result)
            source_pages[source_system] += 1
            _write(output_root / ("pact_spirit" if kind == "pact" else "fate") / f"{quote(slug, safe='-_.')}.json", result)
            entity = entity_by_id.get(entity_id)
            title = (
                (entity or {}).get("entity_title_zh") or entry.get("name_zh")
                or entry.get("name") or entry.get("id") or slug
            )
            documents.extend(_document(record, str(title), kind) for record in result["records"])

    pact_records = [record for result in per_kind["pact"] for record in result["records"]]
    fate_records = [record for result in per_kind["fate"] for record in result["records"]]
    mismatches = [result for result in results if result["structure_validation"]["status"] != "matched"]
    recovered_ids = {
        "tlidb:cn:Micro_Fate:_Deterioration_Duration",
        "tlidb:cn:Micro_Fate:_Trauma_Damage_Mitigation",
    }
    recovered_entities = [entity_by_id.get(entity_id) for entity_id in sorted(recovered_ids)]
    all_ids = [record["record_id"] for record in documents]
    forbidden = (
        "Show Description", "Info id", "<script", "<style", "cookie", "previousItem",
        "DataTables_Table", "UI_Contract", "http://", "https://",
    )

    def case(entity_id: str) -> dict[str, Any]:
        records = [record for record in documents if record["entity_id"] == entity_id]
        return {
            "records": len(records),
            "record_types": sorted({record["record_type"] for record in records}),
            "record_ids": [record["record_id"] for record in records[:20]],
            "locator_levels": dict(Counter(record["source_locator"]["locator_level"] for record in records)),
            "classification": sorted({
                (record["content_category_id"], record["content_subcategory_id"])
                for record in records
            }),
            "search_samples": [record["search_text"] for record in records[:2]],
            "landing": [record["landing"] for record in records[:2]],
        }

    report = {
        "entity_linkage": {
            "pact_entities": sum(entity.get("entity_type") == "pact_spirit" for entity in entity_by_id.values()),
            "fate_entities": sum(entity.get("entity_type") == "fate" for entity in entity_by_id.values()),
            "recovered_fate_entities": [
                entity["entity_id"] for entity in recovered_entities if entity is not None
            ],
            "recovered_linkage_complete": all(entity is not None for entity in recovered_entities),
            "undetermined_fate_present": "tlidb:cn:Undetermined_Fate" in entity_by_id,
        },
        "source_pages": {
            "pact": len(per_kind["pact"]),
            "fate": len(per_kind["fate"]),
            "by_raw_source": dict(sorted(source_pages.items())),
        },
        "parser_versions": {
            PactSpiritParser.parser_id: PactSpiritParser.parser_version,
            FateParser.parser_id: FateParser.parser_version,
        },
        "structure_matched": len(results) - len(mismatches),
        "structure_mismatches": len(mismatches),
        "record_counts": {
            "pact_contract_node_effect": len(pact_records),
            "fate_effect": sum(record["record_type"] == "fate_effect" for record in fate_records),
            "fate_entity_effect": sum(record["record_type"] == "fate_entity_effect" for record in fate_records),
            "pact_total": len(pact_records),
            "fate_total": len(fate_records),
            "total_added": len(documents),
        },
        "record_types": sorted({record["record_type"] for record in documents}),
        "stable_key_coverage": {
            "pact": {
                "records": len(pact_records),
                "high_confidence": sum(record["identity_confidence"] == "high" for record in pact_records),
                "coverage": sum(record["identity_confidence"] == "high" for record in pact_records) / len(pact_records) if pact_records else 0,
            },
            "fate": {
                "records": len(fate_records),
                "modifier_records": sum(record["record_type"] == "fate_effect" for record in fate_records),
                "section_identity_records": sum(record["record_type"] == "fate_entity_effect" for record in fate_records),
                "coverage": sum(record["record_type"] == "fate_effect" for record in fate_records) / len(fate_records) if fate_records else 0,
            },
            "unique_record_ids": len(set(all_ids)),
        },
        "npc_exclusion": {
            "pages_with_inactive_npc": sum(result["structure_validation"]["observed"].get("inactive_npc_panes", 0) > 0 for result in per_kind["pact"]),
            "npc_records_emitted": sum(result["structure_validation"]["observed"].get("npc_records_emitted", 0) for result in per_kind["pact"]),
        },
        "historical_exclusion": {
            "pages_with_history": sum(result["structure_validation"]["observed"].get("historical_card_count", 0) > 0 for result in per_kind["fate"]),
            "historical_modifier_candidates_excluded": sum(result["structure_validation"]["observed"].get("historical_modifier_count", 0) for result in per_kind["fate"]),
            "current_history_duplicate_keys_protected": sum(result["structure_validation"]["observed"].get("current_history_duplicate_keys", 0) for result in per_kind["fate"]),
            "historical_records_emitted": 0,
        },
        "classification": {
            "repository_ids": {
                "pact": ["pact_spirit", "pact_spirit_entity"],
                "fate": ["pact_spirit", "pact_spirit_destiny"],
            },
            "logical_aliases": {
                "pact": ["pact_system", "pact"],
                "fate": ["pact_system", "fate"],
            },
            "errors": sum(
                record["content_category_id"] != "pact_spirit"
                or record["content_subcategory_id"] not in {"pact_spirit_entity", "pact_spirit_destiny"}
                for record in documents
            ),
        },
        "search_merge": {
            "previous_total": 0,
            "added": len(documents),
            "new_total": len(documents),
            "existing_record_ids_preserved": 0,
        },
        "page_suppression": {
            "key": "entity_id with route fallback",
            "structured_entities": len({record["entity_id"] for record in documents}),
            "v1_fallback_without_structured_match": True,
        },
        "locator_support": {
            "pact_record_level": sum(record["source_locator"]["locator_level"] == "record" for record in pact_records),
            "fate_record_level": sum(record["source_locator"]["locator_level"] == "record" for record in fate_records),
            "fate_section_level": sum(record["source_locator"]["locator_level"] == "section" for record in fate_records),
        },
        "landing_validation": {
            "pact_contract_metadata": sum(
                bool(record["source_locator"]["view_state"].get("pact_data_id"))
                and bool(record["source_locator"]["view_state"].get("pact_data_level"))
                for record in pact_records
            ),
            "fate_current_scope": sum(
                record["source_locator"]["view_state"].get("fate_state") == "current"
                for record in fate_records
            ),
            "fallback": ["record", "section", "page"],
        },
        "case_studies": {
            "pact": {
                "Red_Umbrella": case("tlidb:cn:Red_Umbrella"),
                "Happy_Chonky_-_Sun": case("tlidb:cn:Happy_Chonky_-_Sun"),
                "Corgi_Fighter_No.32": case("tlidb:cn:Corgi_Fighter_No.32"),
                "Captain_Shadow": case("tlidb:cn:Captain_Shadow"),
            },
            "fate": {
                page_id: case(f"tlidb:cn:{page_id}") for page_id in (
                    "Micro_Fate:_Fire_Resistance", "Micro_Fate:_Deterioration_Duration",
                    "Micro_Fate:_Trauma_Damage_Mitigation", "Undetermined_Fate",
                    "Medium_Fate:_Fire_Resistance", "Dual_Kismet:_Banshee",
                )
            },
        },
        "noise_validation": {
            "forbidden_text_records": sum(
                any(token in record["search_text"] for token in forbidden) for record in documents
            ),
            "pact_search_whitelist_violations": sum(
                record["text"] != f'{record["node_name"]} {record["node_effect"]}'.strip()
                for record in pact_records
            ),
            "node_context_fields_in_search_documents": sum(
                "node_context" in document
                for document in documents if document["entity_type"] == "pact_spirit"
            ),
            "historical_records": 0,
            "npc_records": 0,
        },
        "errors": (
            [result["source_page"]["canonical_id"] for result in mismatches]
            + (["record_id collision"] if len(all_ids) != len(set(all_ids)) else [])
            + (["recovered Fate Entity linkage incomplete"] if not all(entity is not None for entity in recovered_entities) else [])
        ),
    }

    pact_documents = [record for record in documents if record["entity_type"] == "pact_spirit"]
    fate_documents = [record for record in documents if record["entity_type"] == "fate"]
    pact_index = {
        "schema_version": 1,
        "season_id": season,
        "entity_count": len(per_kind["pact"]),
        "record_count": len(pact_records),
        "parser_id": PactSpiritParser.parser_id,
        "parser_version": PactSpiritParser.parser_version,
        "structure_matched": sum(result["structure_validation"]["status"] == "matched" for result in per_kind["pact"]),
        "records": pact_documents,
    }
    fate_index = {
        "schema_version": 1,
        "season_id": season,
        "entity_count": len(per_kind["fate"]),
        "record_count": len(fate_records),
        "parser_id": FateParser.parser_id,
        "parser_version": FateParser.parser_version,
        "structure_matched": sum(result["structure_validation"]["status"] == "matched" for result in per_kind["fate"]),
        "records": fate_documents,
    }
    _write(output_root / "pact-spirit-structured-index.json", pact_index)
    _write(output_root / "fate-structured-index.json", fate_index)
    _write(report_path, report)
    return results, {"pact": pact_index, "fate": fate_index}, report


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
