"""Audit primary game objects missing from Entity Index v1."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


PRIMARY_SYSTEMS = {
    "inventory",
    "active_skill",
    "support_skill",
    "passive_skill",
    "activation_medium_skill",
    "magnificent_support_skill",
    "noble_support_skill",
    "modularization_skill",
    "talent",
    "path_of_progression",
    "nether_kings_divinity",
    "pactspirit",
    "destiny",
}
FOCUS_INVENTORY = ("Belt", "Crossbow", "DEX_Boots")


def canonical_route(value: str) -> str | None:
    if not value:
        return None
    path = urlsplit(value).path if "://" in value else value
    path = unquote(path)
    if not path.startswith("/"):
        path = "/" + path
    if path.endswith("index.html"):
        path = path[:-len("index.html")]
    route = path.rstrip("/") + "/"
    return route if route.startswith("/cn/") and route != "/cn/" else None


def load_content_tree(path: Path) -> tuple[dict[str, dict[str, str]], set[str]]:
    tree = json.loads(path.read_text(encoding="utf-8"))
    mappings: dict[str, dict[str, str]] = {}
    for category in tree.get("search_categories", []):
        if category.get("search_visibility") != "primary":
            continue
        for child in category.get("children", []):
            for system_id in child.get("systems", []):
                mappings[system_id] = {
                    "category_id": category["id"],
                    "category_name_zh": category["name_zh"],
                    "subcategory_id": child["id"],
                    "subcategory_name_zh": child["name_zh"],
                }
    hidden = {item["system_id"] for item in tree.get("hidden_systems", [])}
    return mappings, hidden


def build_audit(repo: Path) -> dict[str, Any]:
    search = json.loads(
        (repo / "local_wiki/ss13/site/search-index.json").read_text(encoding="utf-8")
    )
    entity_index = json.loads(
        (repo / "data/generated/entity-index.json").read_text(encoding="utf-8")
    )
    dedup = json.loads(
        (repo / "data/reports/local-wiki/entity-dedup-audit.json").read_text(encoding="utf-8")
    )
    tree_mapping, hidden_systems = load_content_tree(repo / "config/game_content_tree.json")
    existing_routes = {
        route
        for entity in entity_index.get("entities", [])
        if (route := canonical_route(entity.get("canonical_route", "")))
    }

    candidates: list[dict[str, Any]] = []
    seen_routes: set[str] = set()
    exclusions = Counter()
    for page in search.get("pages", []):
        system_id = page.get("system_id")
        if system_id in hidden_systems:
            exclusions["hidden_system"] += 1
            continue
        if system_id not in PRIMARY_SYSTEMS:
            exclusions["not_primary_target_system"] += 1
            continue
        mapping = tree_mapping.get(system_id)
        if mapping is None:
            exclusions["not_in_primary_content_tree"] += 1
            continue
        route = canonical_route(page.get("route") or page.get("source_url") or "")
        if route is None:
            exclusions["invalid_canonical_route"] += 1
            continue
        title = " ".join(str(page.get("title_display") or page.get("title") or "").split())
        if not title:
            exclusions["missing_title"] += 1
            continue
        if route in existing_routes:
            exclusions["existing_entity"] += 1
            continue
        if route in seen_routes:
            exclusions["duplicate_candidate_route"] += 1
            continue
        seen_routes.add(route)
        candidates.append({
            "entity_id_proposal": f"tlidb:cn:{route.removeprefix('/cn/').removesuffix('/')}",
            "title": title,
            "canonical_route": route,
            "system_id": system_id,
            **mapping,
        })

    by_category = Counter(item["category_id"] for item in candidates)
    by_system = Counter(item["system_id"] for item in candidates)
    per_system: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in candidates:
        per_system[item["system_id"]].append(item)

    examples = {
        system_id: [
            {
                "entity_id_proposal": item["entity_id_proposal"],
                "title": item["title"],
                "canonical_route": item["canonical_route"],
            }
            for item in rows[:5]
        ]
        for system_id, rows in sorted(per_system.items())
    }
    inventory_by_slug = {
        item["canonical_route"].removeprefix("/cn/").removesuffix("/"): item
        for item in per_system.get("inventory", [])
    }
    examples["inventory_focus"] = [
        {
            "entity_id_proposal": inventory_by_slug[slug]["entity_id_proposal"],
            "title": inventory_by_slug[slug]["title"],
            "canonical_route": inventory_by_slug[slug]["canonical_route"],
        }
        for slug in FOCUS_INVENTORY
        if slug in inventory_by_slug
    ]

    return {
        "schema_version": 1,
        "input_summary": {
            "search_index_schema_version": search.get("schema_version"),
            "search_index_entries": len(search.get("pages", [])),
            "dedup_audit_candidates": len(dedup.get("entity_candidates", [])),
        },
        "current_entity_count": len(entity_index.get("entities", [])),
        "new_entity_candidates": len(candidates),
        "projected_entity_count": len(entity_index.get("entities", [])) + len(candidates),
        "primary_systems": sorted(PRIMARY_SYSTEMS),
        "by_category": dict(sorted(by_category.items())),
        "by_system": dict(sorted(by_system.items())),
        "examples": examples,
        "candidate_entities": candidates,
        "exclusions": dict(sorted(exclusions.items())),
        "warnings": [],
        "errors": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/reports/local-wiki/entity-coverage-v2-audit.json"),
    )
    args = parser.parse_args()
    repo = args.repo.resolve()
    report = build_audit(repo)
    output = args.output if args.output.is_absolute() else repo / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
