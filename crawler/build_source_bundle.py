from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Build a manifest source bundle ZIP")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--raw", required=True, type=Path)
    parser.add_argument("--structured", type=Path)
    parser.add_argument("--reports", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--bundle-id", default="source-bundle")
    parser.add_argument("--season", default="ss13")
    parser.add_argument("--entity-type", default="unknown")
    return parser.parse_args(argv)


def add_file(archive: ZipFile, source: Path, archive_name: str, hashes: dict[str, str]) -> None:
    body = source.read_bytes()
    archive.writestr(archive_name, body)
    hashes[archive_name] = hashlib.sha256(body).hexdigest()


def add_tree(
    archive: ZipFile,
    source: Path,
    prefix: str,
    hashes: dict[str, str],
) -> int:
    count = 0
    archive.writestr(prefix.rstrip("/") + "/", "")
    if source.is_dir():
        for path in sorted(item for item in source.rglob("*") if item.is_file()):
            add_file(
                archive,
                path,
                f"{prefix.rstrip('/')}/{path.relative_to(source).as_posix()}",
                hashes,
            )
            count += 1
    return count


def main(argv=None) -> int:
    args = parse_args(argv)
    manifest_path = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    raw_path = args.raw if args.raw.is_absolute() else ROOT / args.raw
    structured_path = None
    if args.structured:
        structured_path = args.structured if args.structured.is_absolute() else ROOT / args.structured
    reports_path = raw_path / "reports"
    if args.reports:
        reports_path = args.reports if args.reports.is_absolute() else ROOT / args.reports
    output = args.output
    if output is None:
        output = ROOT / f"data/exports/{manifest_path.stem}-source-bundle.zip"
    elif not output.is_absolute():
        output = ROOT / output

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest.get("entries"), list):
        raise ValueError("manifest entries must be a list")
    output.parent.mkdir(parents=True, exist_ok=True)
    parse_report = {}
    parse_report_path = reports_path / "parse-report.json"
    if parse_report_path.is_file():
        parse_report = json.loads(parse_report_path.read_text(encoding="utf-8"))
    file_hashes: dict[str, str] = {}
    bundle_meta = {
        "schema_version": 1,
        "bundle_id": args.bundle_id,
        "season": args.season,
        "entity_type": args.entity_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "manifest_name": manifest_path.name,
        "manifest_count": len(manifest["entries"]),
        "raw_count": 0,
        "structured_count": 0,
        "success_count": parse_report.get("parse_success_count", 0),
        "failure_count": parse_report.get("parse_failure_count", 0),
    }
    bundle_readme = f"""# Torchlight Build 英雄 Source Bundle

这是忠实采集的网页数据，不是知识建模结果。

- 赛季：{args.season}
- 实体类型：{args.entity_type}
- Manifest 条目数：{len(manifest['entries'])}
- `structured/` 只表示网页可识别的结构，不包含游戏语义分类。
- `effect_id` 规则：`<season>.hero.<slug>.node.<node_index>.level.<level_key>.effect.<effect_index>`。
- 没有明确等级时，`level_key` 使用 `unspecified`。
- 采集、解析失败和警告请查看 `reports/`。
"""
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        add_file(archive, manifest_path, "manifest.json", file_hashes)
        bundle_meta["raw_count"] = add_tree(
            archive, raw_path / "raw_html", "raw_html", file_hashes
        )
        bundle_meta["meta_count"] = add_tree(
            archive, raw_path / "meta", "meta", file_hashes
        )
        bundle_meta["report_count"] = add_tree(
            archive, reports_path, "reports", file_hashes
        )
        if structured_path:
            bundle_meta["structured_count"] = add_tree(
                archive, structured_path, "structured", file_hashes
            )
        readme_body = bundle_readme.encode("utf-8")
        archive.writestr("README.md", readme_body)
        file_hashes["README.md"] = hashlib.sha256(readme_body).hexdigest()
        bundle_meta["file_sha256"] = file_hashes
        archive.writestr(
            "bundle_meta.json",
            json.dumps(bundle_meta, ensure_ascii=False, indent=2) + "\n",
        )
    print("Source bundle built")
    print(f"- output: {output.relative_to(ROOT) if output.is_relative_to(ROOT) else output}")
    print(f"- manifest entries: {len(manifest['entries'])}")
    print(f"- raw HTML files: {bundle_meta['raw_count']}")
    print(f"- structured files: {bundle_meta['structured_count']}")
    print(f"- failures: {bundle_meta['failure_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
