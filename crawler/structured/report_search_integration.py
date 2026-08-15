"""Validate the Structured Search v1 overlay and write its release report."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Sequence

from crawler.build_full_wiki_mirror import local_assets


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INDEX = ROOT / "data/generated/structured/ss13/structured-search-index.json"
DEFAULT_REPORT = ROOT / "data/reports/local-wiki/structured-search-integration-v1-report.json"


def build_report(index_path: Path = DEFAULT_INDEX) -> dict:
    errors: list[str] = []
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        index = {"records": []}
        errors.append(f"structured index unavailable: {exc}")
    records = index.get("records", []) if index.get("schema_version") == 1 else []
    if index.get("schema_version") != 1:
        errors.append(f"unsupported structured index schema: {index.get('schema_version')}")
    levels = Counter(
        record.get("source_locator", {}).get("locator_level", "missing") for record in records
    )
    record_types = sorted({record.get("record_type") for record in records if record.get("record_type")})
    entity_types = sorted({record.get("entity_type") for record in records if record.get("entity_type")})
    search_script = local_assets()["_local/search/app.js"]
    landing_script = local_assets()["_local/mirror.js"]
    contracts = {
        "v1_fallback": "loadStructured" in search_script and ".catch(()=>[])" in search_script,
        "entity_grouping": "groupStructured" in search_script,
        "v1_duplicate_suppression": "structuredEntities.has(hit.x.entity_id)" in search_script,
        "classification_filtering": "matchesStructuredTree" in search_script,
        "stable_key_landing": "data-modifier-id" in landing_script,
        "section_fallback": "landing=target||" in landing_script,
        "page_fallback": "if(landing&&landing.scrollIntoView)" in landing_script,
    }
    errors.extend(name for name, supported in contracts.items() if not supported)
    return {
        "structured_documents": len(records),
        "supported_entity_types": entity_types,
        "supported_record_types": record_types,
        "search_integration": {
            "v1_fallback": contracts["v1_fallback"],
            "entity_grouping": contracts["entity_grouping"],
            "v1_duplicate_suppression": contracts["v1_duplicate_suppression"],
        },
        "landing": {
            "record_level": levels.get("record", 0),
            "section_fallback": contracts["section_fallback"],
            "page_fallback": contracts["page_fallback"],
            "stable_key_resolution": contracts["stable_key_landing"],
        },
        "classification_filtering": contracts["classification_filtering"],
        "errors": errors,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    report = build_report(args.index)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
