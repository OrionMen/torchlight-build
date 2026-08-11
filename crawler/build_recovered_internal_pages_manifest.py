from __future__ import annotations

import argparse
import json
from collections import OrderedDict
from pathlib import Path

from crawler.fetch_manifest import request_url_for, write_json


ROOT = Path(__file__).resolve().parents[1]


def build_manifest(discovery_report):
    candidates = discovery_report.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("discovery report candidates must be a list")
    available = [item for item in candidates
                 if item.get("validation", {}).get("status") == "available"]
    unique = OrderedDict()
    duplicate_removed = 0
    for item in available:
        canonical_url = item["canonical_url"]
        if canonical_url in unique:
            duplicate_removed += 1
            sources = unique[canonical_url]["source_examples"]
            for source in item.get("source_examples", []):
                compact = {"source_url": source.get("source_url"), "raw_href": source.get("raw_href")}
                if compact not in sources:
                    sources.append(compact)
            continue
        slug = item.get("slug") or item["canonical_path"].rstrip("/").rsplit("/", 1)[-1]
        unique[canonical_url] = {
            "id": slug,
            "slug": slug,
            "path": item["canonical_path"],
            "url": canonical_url,
            "request_url": item.get("request_url") or request_url_for(canonical_url),
            "validation": {"status": "available", "http_status": 200},
            "source_examples": [
                {"source_url": source.get("source_url"), "raw_href": source.get("raw_href")}
                for source in item.get("source_examples", [])
            ],
        }
    return {
        "schema_version": 1,
        "system_id": "recovered_internal_pages",
        "entity_type": "recovered_page",
        "source": {"type": "internal_link_recovery"},
        "entry_count": len(unique),
        "duplicate_removed": duplicate_removed,
        "entries": list(unique.values()),
    }


def build_validation_report(discovery_report):
    candidates = discovery_report.get("candidates", [])
    counts = {name: 0 for name in ("available", "not_found", "network_error", "redirected", "invalid")}
    entries = []
    for item in candidates:
        validation = item.get("validation", {"status": "not_run"})
        status = validation.get("status", "not_run")
        if status in counts:
            counts[status] += 1
        entries.append({
            "canonical_url": item.get("canonical_url"),
            "request_url": item.get("request_url"),
            "validation": validation,
        })
    return {"schema_version": 1, "candidate_count": len(candidates), **counts, "entries": entries}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Build the validated Recovered Internal Pages manifest")
    parser.add_argument("--discovery-report", type=Path,
                        default=Path("data/reports/local-wiki/missing-internal-pages.json"))
    parser.add_argument("--output", type=Path,
                        default=Path("sources/recovered_internal_pages_manifest.json"))
    parser.add_argument("--validation-report", type=Path,
                        default=Path("data/reports/local-wiki/recovered-internal-pages-validation.json"))
    return parser.parse_args(argv)


def resolve(path):
    return path if path.is_absolute() else ROOT / path


def main(argv=None):
    args = parse_args(argv)
    discovery = json.loads(resolve(args.discovery_report).read_text(encoding="utf-8"))
    manifest = build_manifest(discovery)
    write_json(resolve(args.validation_report), build_validation_report(discovery))
    write_json(resolve(args.output), manifest)
    print(f"Recovered entries: {manifest['entry_count']}")
    print(f"Duplicate removed: {manifest['duplicate_removed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
