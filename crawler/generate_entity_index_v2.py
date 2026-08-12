"""Generate Entity Index v2 from v1 plus reviewed primary coverage candidates."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from crawler.build_full_wiki_mirror import (
    entity_route_key,
    load_entity_index,
    load_game_content_tree,
    resolve_content_tree_classification,
)


def clean_title(value: str) -> str:
    title = " ".join((value or "").split())
    for marker in (" - 火炬编年史", " - Torchlight: Infinite Wiki"):
        if marker in title:
            title = title.split(marker, 1)[0].strip()
    return title


def build_entity_index_v2(repo: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    v1_data = json.loads(
        (repo / "data/generated/entity-index.json").read_text(encoding="utf-8")
    )
    coverage = json.loads(
        (repo / "data/reports/local-wiki/entity-coverage-v2-audit.json").read_text(encoding="utf-8")
    )
    search = json.loads(
        (repo / "local_wiki/ss13/site/search-index.json").read_text(encoding="utf-8")
    )
    tree = load_game_content_tree(repo / "config/game_content_tree.json")
    v1_by_route = load_entity_index(repo / "data/generated/entity-index.json")
    search_by_route = {
        entity_route_key(page.get("route") or page.get("source_url") or ""): page
        for page in search.get("pages", [])
        if page.get("route") or page.get("source_url")
    }

    entities: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_routes: set[str] = set()
    for old in v1_data.get("entities", []):
        route = entity_route_key(old["canonical_route"])
        page = dict(search_by_route.get(route, {}))
        page.setdefault("route", route)
        if not page.get("system_id"):
            page["system_id"] = next(
                (source["system_id"] for source in old.get("sources", []) if source.get("system_id")),
                None,
            )
        content, _ = resolve_content_tree_classification(page, v1_by_route, tree)
        entity = {
            "entity_id": old["entity_id"],
            "title": clean_title(old.get("title") or page.get("title_display") or page.get("title") or ""),
            "canonical_route": route,
            **content,
            "sources": old.get("sources", []),
            "confidence": old.get("confidence"),
        }
        entities.append(entity)
        seen_ids.add(entity["entity_id"])
        seen_routes.add(route)

    new_primary_count = 0
    for candidate in coverage.get("candidate_entities", []):
        route = entity_route_key(candidate["canonical_route"])
        entity_id = candidate["entity_id_proposal"]
        if entity_id in seen_ids or route in seen_routes:
            continue
        entity = {
            "entity_id": entity_id,
            "title": clean_title(candidate["title"]),
            "canonical_route": route,
            "content_category_id": candidate.get("category_id"),
            "content_category_name_zh": candidate.get("category_name_zh"),
            "content_subcategory_id": candidate.get("subcategory_id"),
            "content_subcategory_name_zh": candidate.get("subcategory_name_zh"),
            "sources": [{"system_id": candidate["system_id"], "role": "primary"}],
            "confidence": "primary",
        }
        entities.append(entity)
        seen_ids.add(entity_id)
        seen_routes.add(route)
        new_primary_count += 1

    entities.sort(key=lambda entity: entity["canonical_route"])
    by_category = Counter(
        entity.get("content_category_id") or "null" for entity in entities
    )
    by_subcategory = Counter(
        entity.get("content_subcategory_id") or "null" for entity in entities
    )
    by_system = Counter(
        source["system_id"] for entity in entities for source in entity.get("sources", [])
    )
    new_primary_by_system = Counter(
        entity["sources"][0]["system_id"]
        for entity in entities
        if entity.get("confidence") == "primary"
    )
    confidence = Counter(entity.get("confidence") or "null" for entity in entities)
    index = {"schema_version": 2, "entities": entities}
    report = {
        "schema_version": 1,
        "total_entities": len(entities),
        "old_entities": len(v1_data.get("entities", [])),
        "new_primary_entities": new_primary_count,
        "by_category": dict(sorted(by_category.items())),
        "by_subcategory": dict(sorted(by_subcategory.items())),
        "by_system": dict(sorted(by_system.items())),
        "new_primary_by_system": dict(sorted(new_primary_by_system.items())),
        "confidence_distribution": dict(sorted(confidence.items())),
        "duplicate_entity_ids": len(entities) - len({item["entity_id"] for item in entities}),
        "duplicate_canonical_routes": len(entities) - len({item["canonical_route"] for item in entities}),
        "warnings": [],
        "errors": [],
    }
    return index, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output", type=Path, default=Path("data/generated/entity-index-v2.json")
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/reports/local-wiki/entity-index-v2-generation-report.json"),
    )
    args = parser.parse_args()
    repo = args.repo.resolve()
    index, report = build_entity_index_v2(repo)
    output = args.output if args.output.is_absolute() else repo / args.output
    report_path = args.report if args.report.is_absolute() else repo / args.report
    output.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
