from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from crawler.discover_manifest import write_json
from crawler.discover_system_manifest import discover_system


ROOT = Path(__file__).resolve().parents[1]


def run_batch(
    system_manifest: dict,
    output_dir: Path,
    force: bool = False,
    requested_ids: set[str] | None = None,
    timeout: float = 20.0,
    discoverer: Callable = discover_system,
) -> tuple[dict, int]:
    systems = system_manifest.get("systems")
    if not isinstance(systems, list):
        raise ValueError("system manifest must contain a systems list")
    report = {
        "schema_version": 1,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "confirmed_available": 0,
        "processed": 0,
        "generated": 0,
        "generated_with_warning": 0,
        "skipped_candidate": 0,
        "skipped_existing": 0,
        "failed": 0,
        "warning_count": 0,
        "duplicate_removed_total": 0,
        "displayed_count_mismatch_total": 0,
        "systems": [],
        "warnings": [],
        "errors": [],
    }
    failures = 0
    for system in systems:
        system_id = system.get("system_id")
        if requested_ids is not None and system_id not in requested_ids:
            continue
        if system.get("discovery_status") != "confirmed":
            report["skipped_candidate"] += 1
            report["systems"].append({"system_id": system_id, "status": "skipped_candidate"})
            continue
        report["confirmed_available"] += 1
        output = output_dir / f"{system_id}_manifest.json"
        if output.is_file() and not force:
            report["skipped_existing"] += 1
            report["systems"].append({"system_id": system_id, "status": "skipped_existing", "output": str(output)})
            continue
        report["processed"] += 1
        try:
            manifest, system_report = discoverer(system, timeout)
            unique_count = manifest.get("unique_entry_count", len(manifest.get("entries", [])))
            if system_report.get("errors"):
                raise ValueError("; ".join(system_report["errors"]))
            if unique_count == 0:
                raise ValueError("no unique entity URLs discovered")
            write_json(output, manifest)
            system_warnings = list(system_report.get("warnings", []))
            duplicate_count = manifest.get(
                "duplicate_occurrence_count",
                system_report.get("duplicate_count", 0),
            )
            displayed_count = manifest.get(
                "displayed_entry_count",
                system_report.get("displayed_count"),
            )
            mismatch = displayed_count is not None and displayed_count != unique_count
            if system_warnings:
                report["generated_with_warning"] += 1
                status = "generated_with_warning"
            else:
                report["generated"] += 1
                status = "generated"
            report["warning_count"] += len(system_warnings)
            report["duplicate_removed_total"] += duplicate_count
            report["displayed_count_mismatch_total"] += int(mismatch)
            report["warnings"].extend(f"{system_id}: {item}" for item in system_warnings)
            report["systems"].append(
                {
                    "system_id": system_id,
                    "status": status,
                    "entry_count": unique_count,
                    "warning_count": len(system_warnings),
                    "duplicate_removed": duplicate_count,
                    "displayed_count_mismatch": mismatch,
                    "discovery_confidence": manifest.get("discovery_confidence"),
                    "output": str(output),
                }
            )
        except Exception as exc:
            failures += 1
            report["failed"] += 1
            error = f"{system_id}: {exc}"
            report["errors"].append(error)
            report["systems"].append({"system_id": system_id, "status": "failed", "error": str(exc)})
    if requested_ids is not None:
        known = {item.get("system_id") for item in systems}
        missing = sorted(requested_ids - known)
        if missing:
            failures += len(missing)
            report["failed"] += len(missing)
            report["errors"].extend(f"unknown system_id: {item}" for item in missing)
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    return report, failures


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Discover manifests for confirmed TLIDB systems")
    parser.add_argument("--system-manifest", required=True, type=Path)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--system-id", action="append", dest="system_ids")
    selection.add_argument("--all", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("sources"))
    parser.add_argument("--report", type=Path, default=Path("data/reports/system-discovery/all-manifests-report.json"))
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        manifest_path = args.system_manifest if args.system_manifest.is_absolute() else ROOT / args.system_manifest
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
        requested = None if args.all else set(args.system_ids or [])
        report, failures = run_batch(
            data,
            output_dir,
            force=args.force,
            requested_ids=requested,
            timeout=args.timeout,
        )
        report_path = args.report if args.report.is_absolute() else ROOT / args.report
        write_json(report_path, report)
        print("All manifest discovery")
        print(f"- confirmed: {report['confirmed_available']}")
        print(f"- generated: {report['generated']}")
        print(f"- generated with warning: {report['generated_with_warning']}")
        print(f"- skipped existing: {report['skipped_existing']}")
        print(f"- failed: {report['failed']}")
        print(f"- report: {report_path.relative_to(ROOT) if report_path.is_relative_to(ROOT) else report_path}")
        return 1 if failures else 0
    except Exception as exc:
        if args.debug:
            traceback.print_exc()
        print(f"All manifest discovery failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
