from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from crawler.extract_tooltips import ROOT, write_json


def normalized(value) -> str | None:
    if value is None:
        return None
    lines = [re.sub(r"\s+", " ", line).strip() for line in str(value).splitlines()]
    text = "\n".join(line for line in lines if line)
    return text or None


def definition_hash(title: str | None, text: str) -> str:
    body = json.dumps([title, text], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def load_occurrences(input_dirs: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for directory in input_dirs:
        path = directory / "occurrences.jsonl"
        if not path.is_file():
            raise ValueError(f"missing occurrences file: {path}")
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL {path}:{line_number}: {exc.msg}") from exc
    return rows


def merge_occurrences(*, season: str, occurrences: list[dict], output_dir: Path) -> tuple[dict, dict, dict]:
    definitions_by_key: dict[tuple[str | None, str], dict] = {}
    missing_text: list[dict] = []
    id_rows: dict[str, list[dict]] = defaultdict(list)
    source_types: Counter[str] = Counter()
    for row in occurrences:
        occurrence_id = row.get("occurrence_id")
        id_rows[str(occurrence_id)].append(row)
        source_types[str(row.get("source_type") or "unknown")] += 1
        title = normalized(row.get("tooltip_title_zh"))
        text = normalized(row.get("tooltip_text_zh"))
        if text is None:
            missing_text.append(row)
            continue
        key = (title, text)
        if key not in definitions_by_key:
            digest = definition_hash(title, text)
            definitions_by_key[key] = {
                "definition_id": f"tooltip.cn.{digest}",
                "title_zh": title,
                "text_zh": text,
                "lines_zh": text.splitlines(),
                "content_sha256": digest,
                "occurrence_count": 0,
                "occurrence_ids": [],
                "source_entity_ids": [],
                "source_types": [],
            }
        definition = definitions_by_key[key]
        definition["occurrence_count"] += 1
        definition["occurrence_ids"].append(occurrence_id)
        for field, value in (("source_entity_ids", row.get("source_entity_id")), ("source_types", row.get("source_type"))):
            if value is not None and value not in definition[field]:
                definition[field].append(value)

    definitions = list(definitions_by_key.values())
    conflicts: list[dict] = []
    title_groups: dict[str, list[dict]] = defaultdict(list)
    text_groups: dict[str, list[dict]] = defaultdict(list)
    for definition in definitions:
        if definition["title_zh"] is not None:
            title_groups[definition["title_zh"]].append(definition)
        text_groups[definition["text_zh"]].append(definition)
    for title, group in title_groups.items():
        if len({item["text_zh"] for item in group}) > 1:
            conflicts.append({
                "conflict_type": "same_title_different_text", "key": title,
                "definition_ids": [item["definition_id"] for item in group],
                "occurrence_ids": [oid for item in group for oid in item["occurrence_ids"]],
                "severity": "review",
            })
    for text, group in text_groups.items():
        if len({item["title_zh"] for item in group}) > 1:
            conflicts.append({
                "conflict_type": "same_text_different_title", "key": text,
                "definition_ids": [item["definition_id"] for item in group],
                "occurrence_ids": [oid for item in group for oid in item["occurrence_ids"]],
                "severity": "review",
            })
    duplicate_ids = {oid: rows for oid, rows in id_rows.items() if len(rows) > 1}
    for occurrence_id, rows in duplicate_ids.items():
        conflicts.append({
            "conflict_type": "duplicate_occurrence_id", "key": occurrence_id,
            "definition_ids": [], "occurrence_ids": [occurrence_id] * len(rows), "severity": "error",
        })
    for row in missing_text:
        conflicts.append({
            "conflict_type": "missing_tooltip_text", "key": row.get("occurrence_id"),
            "definition_ids": [], "occurrence_ids": [row.get("occurrence_id")], "severity": "review",
        })
    for row in occurrences:
        if row.get("source", {}).get("hash_match") is False:
            conflicts.append({
                "conflict_type": "source_hash_mismatch", "key": row.get("source", {}).get("html_file"),
                "definition_ids": [], "occurrence_ids": [row.get("occurrence_id")], "severity": "review",
            })

    definitions_payload = {
        "schema_version": 1, "season": season,
        "definition_count": len(definitions), "definitions": definitions,
    }
    conflicts_payload = {
        "schema_version": 1, "season": season,
        "conflict_count": len(conflicts), "conflicts": conflicts,
    }
    count_type = lambda name: sum(item["conflict_type"] == name for item in conflicts)
    report = {
        "schema_version": 1,
        "season": season,
        "input_occurrence_count": len(occurrences),
        "unique_definition_count": len(definitions),
        "duplicate_definition_occurrences": sum(max(0, item["occurrence_count"] - 1) for item in definitions),
        "same_title_different_text_count": count_type("same_title_different_text"),
        "same_text_different_title_count": count_type("same_text_different_title"),
        "duplicate_occurrence_id_count": len(duplicate_ids),
        "conflict_count": len(conflicts),
        "source_type_counts": dict(sorted(source_types.items())),
        "warnings": [item["conflict_type"] for item in conflicts if item["severity"] == "review"],
        "errors": [f"duplicate occurrence_id: {key}" for key in duplicate_ids],
    }
    write_json(output_dir / "definitions.json", definitions_payload)
    write_json(output_dir / "conflicts.json", conflicts_payload)
    write_json(output_dir / "merge-report.json", report)
    return definitions_payload, conflicts_payload, report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Merge and deduplicate extracted Tooltip occurrences")
    parser.add_argument("--season", required=True)
    parser.add_argument("--input", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args(argv)


def rooted(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        rows = load_occurrences([rooted(path) for path in args.input])
        definitions, conflicts, report = merge_occurrences(
            season=args.season, occurrences=rows, output_dir=rooted(args.output)
        )
        print("Tooltip merge")
        print(f"- occurrences: {len(rows)}")
        print(f"- definitions: {definitions['definition_count']}")
        print(f"- conflicts: {conflicts['conflict_count']}")
        print(f"- output: {args.output}")
        if report["duplicate_occurrence_id_count"]:
            return 1
        return 1 if args.strict and conflicts["conflict_count"] else 0
    except Exception as exc:
        if args.debug:
            raise
        print(f"Tooltip merge failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
