"""Generate Entity Index v1 from reviewed local audit results."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from crawler.audit_entity_layer_design import classify_medium


SUPPORT_SYSTEMS = {"help", "tip", "codex"}
SYSTEM_PRIORITY = {
    "hero": 0,
    "active_skill": 0,
    "support_skill": 0,
    "passive_skill": 0,
    "activation_medium_skill": 0,
    "magnificent_support_skill": 0,
    "noble_support_skill": 0,
    "modularization_skill": 0,
    "talent": 0,
    "pactspirit": 0,
    "legendary_gear": 0,
    "inventory": 1,
    "craft": 2,
}


def load_category_map(path: Path) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    systems: dict[str, dict[str, str]] = {}
    names: dict[str, str] = {}
    for category in data.get("categories", []):
        names[category["id"]] = category["name_zh"]
        for system_id in category.get("systems", []):
            systems[system_id] = {"id": category["id"], "name_zh": category["name_zh"]}
    return systems, names


def entity_id_from_route(route: str) -> str:
    semantic = unquote(route).strip("/")
    if semantic == "cn":
        slug = ""
    elif semantic.startswith("cn/"):
        slug = semantic[3:]
    else:
        slug = semantic
    return f"tlidb:cn:{slug}"


def source_role(system_id: str, category_map: dict[str, dict[str, str]]) -> str:
    if system_id == "recovered_internal_pages":
        return "recovered"
    if system_id == "hyperlink":
        return "secondary"
    if system_id in SUPPORT_SYSTEMS:
        return "support"
    if system_id in category_map or system_id in {"inventory", "legendary_gear", "craft"}:
        return "primary"
    return "source"


def resolve_category(
    sources: list[dict[str, Any]], category_map: dict[str, dict[str, str]]
) -> str | None:
    categories = {
        category_map[source["system_id"]]["id"]
        for source in sources
        if source.get("system_id") in category_map
    }
    return next(iter(categories)) if len(categories) == 1 else None


def select_title(
    sources: list[dict[str, Any]],
    category: str | None,
    category_map: dict[str, dict[str, str]],
    fallback: str,
) -> str:
    def rank(source: dict[str, Any]) -> tuple[int, int, int, str]:
        system_id = source["system_id"]
        mapped = category_map.get(system_id, {}).get("id")
        role = source_role(system_id, category_map)
        if category and mapped == category:
            owner_rank = 0
        else:
            owner_rank = {"primary": 1, "source": 2, "secondary": 3, "support": 4, "recovered": 5}[role]
        title = str(source.get("title") or "")
        lacks_chinese = 0 if re.search(r"[\u3400-\u9fff]", title) else 1
        return owner_rank, SYSTEM_PRIORITY.get(system_id, 100), lacks_chinese, system_id

    chosen = min(sources, key=rank) if sources else None
    return str(chosen.get("title") or fallback) if chosen else fallback


def build_entity_index(
    dedup: dict[str, Any], category_map: dict[str, dict[str, str]], category_names: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    skipped_medium_b: list[dict[str, str]] = []
    high_count = 0
    medium_a_count = 0

    for candidate in dedup.get("entity_candidates", []):
        confidence = candidate.get("confidence")
        merge_class = None
        if confidence == "high":
            high_count += 1
        elif confidence == "medium":
            merge_class, _ = classify_medium(candidate)
            if merge_class != "A":
                skipped_medium_b.append({
                    "canonical_route": candidate["canonical_route"],
                    "classification": merge_class,
                })
                continue
            medium_a_count += 1
        else:
            continue

        source_rows = candidate.get("sources", [])
        category = resolve_category(source_rows, category_map)
        sources = [
            {
                "system_id": source["system_id"],
                "role": source_role(source["system_id"], category_map),
            }
            for source in source_rows
        ]
        entity = {
            "entity_id": entity_id_from_route(candidate["canonical_route"]),
            "title": select_title(source_rows, category, category_map, candidate.get("title") or ""),
            "canonical_route": candidate["canonical_route"],
            "category": category,
            "category_name_zh": category_names.get(category) if category else None,
            "sources": sources,
            "confidence": confidence,
        }
        if merge_class:
            entity["merge_class"] = merge_class
        entities.append(entity)

    entities.sort(key=lambda item: item["canonical_route"])
    category_distribution = Counter(
        entity["category"] if entity["category"] is not None else "null" for entity in entities
    )
    source_distribution = Counter(
        source["system_id"] for entity in entities for source in entity["sources"]
    )
    index = {"schema_version": 1, "entities": entities}
    report = {
        "schema_version": 1,
        "total_entities": len(entities),
        "high_confidence_count": high_count,
        "medium_a_count": medium_a_count,
        "skipped_medium_b_count": len(skipped_medium_b),
        "skipped_medium_b": skipped_medium_b,
        "category_distribution": dict(sorted(category_distribution.items())),
        "source_distribution": dict(sorted(source_distribution.items())),
        "warnings": [],
        "errors": [],
    }
    return index, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("data/generated/entity-index.json"))
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/reports/local-wiki/entity-index-generation-report.json"),
    )
    args = parser.parse_args()
    repo = args.repo.resolve()
    dedup = json.loads(
        (repo / "data/reports/local-wiki/entity-dedup-audit.json").read_text(encoding="utf-8")
    )
    category_map, category_names = load_category_map(repo / "config/game_category_mapping.json")
    index, report = build_entity_index(dedup, category_map, category_names)
    output = args.output if args.output.is_absolute() else repo / args.output
    report_path = args.report if args.report.is_absolute() else repo / args.report
    output.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
