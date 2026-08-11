from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from crawler.extract_tooltips import ROOT
from crawler.merge_tooltips import load_occurrences


README_TEXT = """# Tooltip Source Bundle

Tooltip Source Bundle 是忠实采集结果。

- Definition 仅为内容去重候选，不是正式 Concept。
- 重复 occurrence 不会丢失。
- `conflicts.json` 需要人工审核。
- 正式 Knowledge ID 由后续 Knowledge Review 生成。
"""


def add_bytes(archive: ZipFile, name: str, body: bytes, hashes: dict[str, str]) -> None:
    archive.writestr(name, body)
    hashes[name] = hashlib.sha256(body).hexdigest()


def build_bundle(
    *, season: str, merged_dir: Path, occurrence_dirs: list[Path], output: Path
) -> dict:
    required = ["definitions.json", "conflicts.json", "merge-report.json"]
    missing = [name for name in required if not (merged_dir / name).is_file()]
    if missing:
        raise ValueError(f"missing required merged files: {', '.join(missing)}")
    definitions = json.loads((merged_dir / "definitions.json").read_text(encoding="utf-8"))
    conflicts = json.loads((merged_dir / "conflicts.json").read_text(encoding="utf-8"))
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in load_occurrences(occurrence_dirs) if occurrence_dirs else []:
        grouped[str(row.get("source_type") or "unknown")].append(row)
    output.parent.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    meta = {
        "schema_version": 1,
        "bundle_id": f"tooltip-source-bundle-{season}",
        "season": season,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "definition_count": definitions.get("definition_count", 0),
        "occurrence_count": sum(len(rows) for rows in grouped.values()),
        "conflict_count": conflicts.get("conflict_count", 0),
        "source_types": sorted(grouped),
    }
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        add_bytes(archive, "definitions.json", (merged_dir / "definitions.json").read_bytes(), hashes)
        add_bytes(archive, "conflicts.json", (merged_dir / "conflicts.json").read_bytes(), hashes)
        for source_type, rows in sorted(grouped.items()):
            body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8")
            add_bytes(archive, f"occurrences/{source_type}.jsonl", body, hashes)
        add_bytes(archive, "reports/merge-report.json", (merged_dir / "merge-report.json").read_bytes(), hashes)
        for directory in occurrence_dirs:
            report_path = directory / "report.json"
            if report_path.is_file():
                rows = load_occurrences([directory])
                source_type = str(rows[0].get("source_type") if rows else directory.name)
                add_bytes(archive, f"reports/{source_type}-extract-report.json", report_path.read_bytes(), hashes)
        add_bytes(archive, "README.md", README_TEXT.encode("utf-8"), hashes)
        meta["file_sha256"] = hashes
        archive.writestr("bundle_meta.json", json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    return meta


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Build a Tooltip Source Bundle ZIP")
    parser.add_argument("--season", required=True)
    parser.add_argument("--merged-dir", required=True, type=Path)
    parser.add_argument("--occurrence-dir", action="append", default=[], type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args(argv)


def rooted(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        meta = build_bundle(
            season=args.season,
            merged_dir=rooted(args.merged_dir),
            occurrence_dirs=[rooted(path) for path in args.occurrence_dir],
            output=rooted(args.output),
        )
        print("Tooltip source bundle")
        print(f"- definitions: {meta['definition_count']}")
        print(f"- occurrences: {meta['occurrence_count']}")
        print(f"- conflicts: {meta['conflict_count']}")
        print(f"- output: {args.output}")
        return 0
    except Exception as exc:
        if args.debug:
            raise
        print(f"Tooltip bundle failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
