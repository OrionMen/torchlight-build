"""Validate the deterministic runtime outputs of one season rebuild."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from crawler.season_context import DEFAULT_SEASON, SeasonContext
from crawler.structured.aggregate_structured_search import PRODUCTION_MODULES


ROOT = Path(__file__).resolve().parents[1]


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def validate(context: SeasonContext) -> dict:
    entity = _json(context.entity_output)
    structured_root = context.structured_root
    structured = _json(structured_root / "structured-search-index.json")
    site = context.mirror_output
    search = _json(site / "search-index.json")
    catalog = _json(site / "catalog.json")
    missing_modules = [
        spec.filename for spec in PRODUCTION_MODULES
        if not (structured_root / spec.filename).is_file()
    ]
    errors = []
    if entity.get("schema_version") != 3:
        errors.append("Entity schema must be 3")
    if structured.get("schema_version") != 1:
        errors.append("Structured schema must be 1")
    if structured.get("season_id") != context.season:
        errors.append("Structured season mismatch")
    if search.get("schema_version") != 8:
        errors.append("Search schema must be 8")
    if missing_modules:
        errors.append(f"Missing Structured modules: {', '.join(missing_modules)}")
    for relative in ("_local/search/app.js", "_local/mirror.js"):
        if not (site / relative).is_file():
            errors.append(f"Missing runtime output: {relative}")
    return {
        "season": context.season,
        "entity_schema": entity.get("schema_version"),
        "structured_schema": structured.get("schema_version"),
        "structured_modules": len(PRODUCTION_MODULES) - len(missing_modules),
        "search_schema": search.get("schema_version"),
        "catalog_valid": isinstance(catalog, dict),
        "site_exists": site.is_dir(),
        "errors": errors,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default=DEFAULT_SEASON)
    args = parser.parse_args(argv)
    report = validate(SeasonContext(ROOT, args.season))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
