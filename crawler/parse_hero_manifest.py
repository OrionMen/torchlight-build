from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from shutil import copyfile
from urllib.parse import quote

from .parse_hero import parse_hero_html


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def iter_effects(document: dict):
    for node in document.get("nodes", []):
        for level in node.get("levels", []):
            yield from level.get("effects", [])


def find_effect_issues(documents: list[dict]) -> tuple[list[str], list[str]]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    empty: list[str] = []
    for document in documents:
        for effect in iter_effects(document):
            effect_id = effect.get("effect_id")
            if effect_id in seen:
                duplicates.add(effect_id)
            else:
                seen.add(effect_id)
            if not isinstance(effect.get("text"), str) or not effect["text"].strip():
                empty.append(effect_id or "<missing effect_id>")
    return sorted(duplicates), sorted(empty)


def _stem(slug: str) -> str:
    return quote(slug, safe="-_.")


def _consistency_report(manifest: dict, raw_dir: Path, structured_dir: Path) -> dict:
    entries = manifest["entries"]
    expected = {_stem(entry["slug"]): entry for entry in entries}
    raw_files = {path.stem: path for path in (raw_dir / "raw_html").glob("*.html")}
    meta_files = {
        path.name.removesuffix(".meta.json"): path
        for path in (raw_dir / "meta").glob("*.meta.json")
    }
    structured_files = {path.stem: path for path in structured_dir.glob("*.json")}
    sha_mismatches = []
    metadata_mismatches = []
    for stem, entry in expected.items():
        raw_path = raw_files.get(stem)
        meta_path = meta_files.get(stem)
        if not raw_path or not meta_path:
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
            if digest != meta.get("sha256"):
                sha_mismatches.append(entry["id"])
            if meta.get("id") != entry["id"] or meta.get("source_url") != entry["url"]:
                metadata_mismatches.append(entry["id"])
        except (OSError, json.JSONDecodeError):
            metadata_mismatches.append(entry["id"])

    report = {
        "schema_version": 1,
        "manifest_count": len(entries),
        "raw_count": len(raw_files),
        "meta_count": len(meta_files),
        "structured_count": len(structured_files),
        "missing_raw": [expected[item]["id"] for item in sorted(set(expected) - set(raw_files))],
        "missing_meta": [expected[item]["id"] for item in sorted(set(expected) - set(meta_files))],
        "missing_structured": [
            expected[item]["id"] for item in sorted(set(expected) - set(structured_files))
        ],
        "extra_raw": sorted(set(raw_files) - set(expected)),
        "extra_meta": sorted(set(meta_files) - set(expected)),
        "extra_structured": sorted(set(structured_files) - set(expected)),
        "sha256_mismatches": sorted(sha_mismatches),
        "metadata_mismatches": sorted(metadata_mismatches),
        "warnings": [],
        "errors": [],
    }
    for field in (
        "missing_raw", "missing_meta", "missing_structured", "sha256_mismatches",
        "metadata_mismatches",
    ):
        if report[field]:
            report["errors"].append(f"{field}: {len(report[field])}")
    for field in ("extra_raw", "extra_meta", "extra_structured"):
        if report[field]:
            report["warnings"].append(f"{field}: {len(report[field])}")
    return report


def parse_manifest_batch(
    manifest_path: Path,
    raw_dir: Path,
    structured_dir: Path,
    report_dir: Path,
    season: str = "ss13",
) -> tuple[dict, dict, int]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise ValueError("manifest entries must be a list")

    report = {
        "schema_version": 1,
        "season": season,
        "manifest_count": len(entries),
        "download_success_count": 0,
        "download_failure_count": 0,
        "parse_success_count": 0,
        "parse_failure_count": 0,
        "total_node_count": 0,
        "total_effect_count": 0,
        "heroes": [],
        "missing_fields": {
            "name": [],
            "portrait": [],
            "recommended_skill": [],
            "nodes": [],
        },
        "duplicate_effect_ids": [],
        "empty_effect_texts": [],
        "warnings": [],
        "errors": [],
    }
    documents: list[dict] = []
    structured_dir.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        entity_id = entry.get("id")
        slug = entry.get("slug")
        hero_result = {
            "entity_id": entity_id,
            "status": "failed",
            "node_count": 0,
            "effect_count": 0,
            "warnings": [],
            "errors": [],
        }
        try:
            if not isinstance(slug, str) or not slug:
                raise ValueError("manifest entry has invalid slug")
            stem = _stem(slug)
            raw_path = raw_dir / f"raw_html/{stem}.html"
            meta_path = raw_dir / f"meta/{stem}.meta.json"
            if not raw_path.is_file() or not meta_path.is_file():
                report["download_failure_count"] += 1
                raise ValueError("raw HTML or meta JSON is missing")
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            raw = raw_path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest != meta.get("sha256"):
                report["download_failure_count"] += 1
                raise ValueError("raw HTML SHA-256 does not match meta")
            report["download_success_count"] += 1
            encoding = meta.get("encoding") or "utf-8"
            try:
                html = raw.decode(encoding)
            except (LookupError, UnicodeDecodeError):
                html = raw.decode("utf-8")
            document = parse_hero_html(
                html,
                entity_id=entity_id,
                name_zh=entry.get("name_zh") or "",
                page_url=entry.get("url") or meta.get("final_url") or meta.get("source_url"),
                raw_sha256=digest,
                season=season,
            )
            output_path = structured_dir / f"{stem}.json"
            temporary = output_path.with_suffix(".json.tmp")
            write_json(temporary, document)
            temporary.replace(output_path)
            node_count = len(document["nodes"])
            effect_count = sum(1 for _effect in iter_effects(document))
            hero_result.update(
                {
                    "status": "success",
                    "node_count": node_count,
                    "effect_count": effect_count,
                    "warnings": document.get("parse_warnings", []),
                }
            )
            report["parse_success_count"] += 1
            report["total_node_count"] += node_count
            report["total_effect_count"] += effect_count
            if not document.get("name_zh"):
                report["missing_fields"]["name"].append(entity_id)
            if not document.get("portrait", {}).get("url"):
                report["missing_fields"]["portrait"].append(entity_id)
            if not document.get("recommended_skill", {}).get("name"):
                report["missing_fields"]["recommended_skill"].append(entity_id)
            if not document.get("nodes"):
                report["missing_fields"]["nodes"].append(entity_id)
            documents.append(document)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            report["parse_failure_count"] += 1
            hero_result["errors"].append(str(exc))
            report["errors"].append({"entity_id": entity_id, "error": str(exc)})
        report["heroes"].append(hero_result)

    duplicates, empty = find_effect_issues(documents)
    report["duplicate_effect_ids"] = duplicates
    report["empty_effect_texts"] = empty
    if duplicates:
        report["errors"].append({"error": f"duplicate effect_id count: {len(duplicates)}"})
    if empty:
        report["errors"].append({"error": f"empty effect text count: {len(empty)}"})
    for field, ids in report["missing_fields"].items():
        if ids:
            report["warnings"].append(f"missing {field}: {len(ids)}")

    consistency = _consistency_report(manifest, raw_dir, structured_dir)
    write_json(report_dir / "parse-report.json", report)
    write_json(report_dir / "manifest-consistency-report.json", consistency)
    source_fetch_report = raw_dir / "reports/fetch-report.json"
    if source_fetch_report.is_file():
        report_dir.mkdir(parents=True, exist_ok=True)
        copyfile(source_fetch_report, report_dir / "fetch-report.json")
    status = 1 if report["errors"] or consistency["errors"] else 0
    return report, consistency, status


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Parse all heroes in a source manifest")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--raw", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reports", required=True, type=Path)
    parser.add_argument("--season", default="ss13")
    return parser.parse_args(argv)


def rooted(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def main(argv=None) -> int:
    args = parse_args(argv)
    report, consistency, status = parse_manifest_batch(
        rooted(args.manifest),
        rooted(args.raw),
        rooted(args.output),
        rooted(args.reports),
        args.season,
    )
    print("Hero manifest parse")
    print(f"- manifest: {report['manifest_count']}")
    print(f"- downloaded: {report['download_success_count']}")
    print(f"- parsed: {report['parse_success_count']}")
    print(f"- failed: {report['parse_failure_count']}")
    print(f"- nodes: {report['total_node_count']}")
    print(f"- effects: {report['total_effect_count']}")
    print(f"- consistency errors: {len(consistency['errors'])}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
