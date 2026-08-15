"""Report the Tier-aware landing contract for ordinary crafted equipment."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INDEX = ROOT / "data/generated/structured/ss13/structured-search-index.json"
DEFAULT_REPORT = ROOT / "data/reports/local-wiki/structured-equipment-tier-landing-v1-report.json"


def build_report(index_path: Path = DEFAULT_INDEX) -> dict[str, Any]:
    errors: list[str] = []
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        index = {"records": []}
        errors.append(f"structured index unavailable: {exc}")
    craft = [
        record for record in index.get("records", [])
        if record.get("record_type") == "equipment_craft_affix"
    ]
    distribution = Counter(record.get("tier") or "show_all" for record in craft)

    def representative(tier: str) -> dict[str, Any] | None:
        record = next((item for item in craft if item.get("tier") == tier), None)
        if record is None:
            errors.append(f"missing representative tier: {tier}")
            return None
        return {
            "record_id": record["record_id"],
            "entity_id": record["entity_id"],
            "stable_key": record["source_locator"]["stable_key"],
            "section": record["source_locator"]["dom_id"],
            "tier": record["tier"],
            "source_tier_value": record.get("source_tier_value"),
        }

    base = next(
        (record for record in index.get("records", []) if record.get("record_type") == "equipment_base_affix"),
        None,
    )
    fallback = next((record for record in craft if record.get("tier") is None), None)
    return {
        "tier_metadata_available": all(
            tier in {record.get("tier") for record in craft}
            for tier in ("t0_plus", "t0", "t1", "t2")
        ),
        "tier_distribution": dict(sorted(distribution.items())),
        "landing_mapping": {
            "t0_plus": {"control_name": "showDetail", "control_value": "0+", "control_id": "showT0pDetail"},
            "t0": {"control_name": "showDetail", "control_value": "0", "control_id": "showT0Detail"},
            "t1": {"control_name": "showDetail", "control_value": "1", "control_id": "showT1Detail"},
            "t2": {"control_name": "showDetail", "control_value": "2", "control_id": "showT2Detail"},
            "fallback": {"control_name": "showDetail", "control_value": "all", "control_id": "showAllDetail"},
        },
        "t0_plus_case": representative("t0_plus"),
        "t0_case": representative("t0"),
        "t1_case": representative("t1"),
        "t2_case": representative("t2"),
        "show_all_fallback": {
            "available": fallback is not None,
            "record_id": fallback.get("record_id") if fallback else None,
            "source_tier_value": fallback.get("source_tier_value") if fallback else None,
        },
        "base_affix_regression": {
            "record_id": base.get("record_id") if base else None,
            "tier_parameter_absent": base is not None and "tier" not in base,
        },
        "root_cause": (
            "The source page document-ready handler selects showDetail value=1 and triggers its "
            "change handler. The previous landing code never selected a Tier control, so non-T1 "
            "rows stayed hidden even after the correct craft tab and modifier were resolved."
        ),
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
