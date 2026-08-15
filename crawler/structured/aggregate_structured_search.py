"""Deterministically aggregate production Structured Search module indexes."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence
from crawler.season_context import DEFAULT_SEASON, SeasonContext


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODULE_ROOT = ROOT / "data/generated/structured/ss13"
DEFAULT_OUTPUT = DEFAULT_MODULE_ROOT / "structured-search-index.json"


class StructuredAggregationError(RuntimeError):
    """Raised when a production module cannot be safely aggregated."""


@dataclass(frozen=True)
class ModuleSpec:
    module_id: str
    filename: str
    required: bool = True


# This is the only production allowlist. Sidecars and unknown JSON files are never
# discovered implicitly.
PRODUCTION_MODULES: tuple[ModuleSpec, ...] = (
    ModuleSpec("ordinary_equipment", "equipment-structured-index.json"),
    ModuleSpec("legendary_equipment", "legendary-equipment-structured-index.json"),
    ModuleSpec("vorax_equipment", "vorax-equipment-structured-index.json"),
    ModuleSpec("memory", "memory-structured-index.json"),
    ModuleSpec("equipment_related", "equipment-related-structured-index.json"),
    ModuleSpec("ethereal_prism", "ethereal-prism-structured-index.json"),
    ModuleSpec("pact", "pact-spirit-structured-index.json"),
    ModuleSpec("fate", "fate-structured-index.json"),
    ModuleSpec("hero_trait", "hero-trait-structured-index.json"),
    ModuleSpec("remaining_talent", "remaining-talent-structured-index.json"),
    ModuleSpec("skill", "skill-structured-index.json"),
)


def _load_module(path: Path, spec: ModuleSpec, season: str = DEFAULT_SEASON) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StructuredAggregationError(
            f"missing required Structured module {spec.module_id}: {path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise StructuredAggregationError(
            f"invalid JSON in Structured module {spec.module_id}: {path}: {exc}"
        ) from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise StructuredAggregationError(
            f"invalid schema in Structured module {spec.module_id}: expected schema_version 1"
        )
    if value.get("season_id") != season:
        raise StructuredAggregationError(
            f"invalid schema in Structured module {spec.module_id}: season_id must be {season!r}"
        )
    records = value.get("records")
    if not isinstance(records, list):
        raise StructuredAggregationError(
            f"invalid schema in Structured module {spec.module_id}: records must be a list"
        )
    if not records:
        raise StructuredAggregationError(
            f"empty production Structured module {spec.module_id}: {path}"
        )
    declared_count = value.get("record_count")
    if declared_count != len(records):
        raise StructuredAggregationError(
            f"record_count mismatch in Structured module {spec.module_id}: "
            f"declared {declared_count!r}, actual {len(records)}"
        )
    for position, record in enumerate(records):
        if not isinstance(record, dict) or not isinstance(record.get("record_id"), str) or not record["record_id"]:
            raise StructuredAggregationError(
                f"invalid record at {spec.module_id}[{position}]: non-empty record_id required"
            )
    return value


def build_aggregate(
    module_root: Path,
    *,
    registry: Iterable[ModuleSpec] = PRODUCTION_MODULES,
    allow_missing: bool = False,
    season: str = DEFAULT_SEASON,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Build an aggregate in memory without consulting an existing final index."""
    records_by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    module_counts: dict[str, int] = {}
    for spec in registry:
        path = module_root / spec.filename
        if not path.is_file() and (allow_missing or not spec.required):
            continue
        module = _load_module(path, spec, season)
        records = module["records"]
        module_counts[spec.module_id] = len(records)
        for record in records:
            record_id = record["record_id"]
            previous = records_by_id.get(record_id)
            if previous is not None:
                raise StructuredAggregationError(
                    f"duplicate record_id {record_id!r} owned by modules "
                    f"{previous[0]!r} and {spec.module_id!r}"
                )
            records_by_id[record_id] = (spec.module_id, record)

    records = [records_by_id[key][1] for key in sorted(records_by_id)]
    if not records:
        raise StructuredAggregationError("no Structured Search records were aggregated")
    return {
        "schema_version": 1,
        "season_id": season,
        "record_count": len(records),
        "records": records,
    }, module_counts


def write_atomic_json(path: Path, value: dict[str, Any]) -> None:
    """Write validated JSON next to the target, then atomically replace it."""
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
        # Validate the complete temporary payload before replacing a good output.
        json.loads(temporary.read_text(encoding="utf-8"))
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def aggregate_structured_search(
    module_root: Path | None = None,
    output_path: Path | None = None,
    *,
    registry: Iterable[ModuleSpec] = PRODUCTION_MODULES,
    allow_missing: bool = False,
    season: str = DEFAULT_SEASON,
) -> tuple[dict[str, Any], dict[str, int]]:
    context = SeasonContext(ROOT, season)
    module_root = module_root or context.structured_root
    output_path = output_path or module_root / "structured-search-index.json"
    aggregate, module_counts = build_aggregate(
        module_root, registry=registry, allow_missing=allow_missing, season=season
    )
    write_atomic_json(output_path, aggregate)
    return aggregate, module_counts


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--module-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args(argv)
    context = SeasonContext(ROOT, args.season)
    module_root = (args.module_root or context.structured_root).resolve()
    output = (args.output or module_root / "structured-search-index.json").resolve()
    aggregate_structured_search(
        module_root,
        output,
        allow_missing=args.allow_missing,
        season=args.season,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
