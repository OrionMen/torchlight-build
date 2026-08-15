"""Refresh Legendary Entity/Search ownership after zero-byte snapshot recovery."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from crawler.build_full_wiki_mirror import entity_fields_for_route, entity_route_key


ROOT = Path(__file__).resolve().parents[1]
NON_EQUIPMENT_IDS = {
    "Sparks_of_Moth_Fire",
    "Fallen_Starlight",
    "A_Corner_of_Divinity",
    "Space_Rift",
    "Pedigree_of_Gods",
    "Residence_of_Stars",
    "When_Sparks_Set_the_Prairie_Ablaze",
}


def source_health(repo: Path) -> dict[str, Any]:
    manifest = json.loads(
        (repo / "sources/legendary_gear_manifest.json").read_text(encoding="utf-8")
    )
    raw_root = repo / "data/raw/manifests/legendary_gear/raw_html"
    present = nonempty = zero = missing = 0
    for entry in manifest.get("entries", []):
        path = raw_root / f"{entry['slug']}.html"
        if not path.is_file():
            missing += 1
        else:
            present += 1
            if path.stat().st_size:
                nonempty += 1
            else:
                zero += 1
    return {
        "manifest_pages": len(manifest.get("entries", [])),
        "raw_present": present,
        "nonempty_raw": nonempty,
        "zero_byte_raw": zero,
        "missing_raw": missing,
    }


def refresh_search_ownership(
    search_index: dict[str, Any], entity_index: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, int]]:
    if search_index.get("schema_version") != 8:
        raise ValueError(f"Search schema must remain 8, got {search_index.get('schema_version')}")
    legendary = {
        entity_route_key(entity["canonical_route"]): entity
        for entity in entity_index.get("entities", [])
        if entity.get("entity_type") == "legendary_equipment"
        and entity.get("content_category_id") == "equipment"
        and entity.get("content_subcategory_id") == "equipment_legendary"
    }
    refreshed = []
    seen_legendary_routes: set[str] = set()
    ownership_updates = duplicate_suppressed = 0
    for original in search_index.get("pages", []):
        page = dict(original)
        route = entity_route_key(page.get("route") or page.get("source_url") or "")
        entity = legendary.get(route)
        if entity is None:
            refreshed.append(page)
            continue
        if route in seen_legendary_routes:
            duplicate_suppressed += 1
            continue
        seen_legendary_routes.add(route)
        ownership_updates += int(page.get("system_id") != "legendary_gear")
        title = entity.get("entity_title_zh") or entity.get("title") or page.get("title")
        summary = entity.get("clean_summary") or page.get("plain_text") or ""
        page.update(
            {
                "system_id": "legendary_gear",
                "system_name_zh": "传奇装备",
                "game_category": "equipment",
                "game_category_name_zh": "装备",
                "game_category_visibility": "primary",
                "title": title,
                "title_display": title,
                "source_type": "official_system",
                "source_url": f"https://tlidb.com{route.rstrip('/')}",
                "plain_text": summary,
                "summary_display": summary,
                "content_category_id": "equipment",
                "content_category_name_zh": "装备",
                "content_subcategory_id": "equipment_legendary",
                "content_subcategory_name_zh": "传奇装备",
            }
        )
        page.update(entity_fields_for_route(route, legendary))
        refreshed.append(page)
    result = dict(search_index)
    result["pages"] = refreshed
    result["page_count"] = len(refreshed)
    return result, {
        "legendary_routes": len(legendary),
        "ownership_updates": ownership_updates,
        "duplicate_search_entries_suppressed": duplicate_suppressed,
    }


def build_recovery_report(
    repo: Path, entity_index: dict[str, Any], search_index: dict[str, Any]
) -> dict[str, Any]:
    health = source_health(repo)
    entities = [
        entity
        for entity in entity_index.get("entities", [])
        if entity.get("entity_type") == "legendary_equipment"
    ]
    by_id = {entity["entity_id"]: entity for entity in entities}
    legendary_routes = {entity_route_key(entity["canonical_route"]) for entity in entities}
    legendary_pages = [
        page
        for page in search_index.get("pages", [])
        if entity_route_key(page.get("route") or page.get("source_url") or "")
        in legendary_routes
    ]
    classification_errors = [
        entity["entity_id"]
        for entity in entities
        if entity.get("content_category_id") != "equipment"
        or entity.get("content_subcategory_id") != "equipment_legendary"
    ]
    fetch_report = json.loads(
        (repo / "data/raw/manifests/legendary_gear/reports/fetch-report.json").read_text(
            encoding="utf-8"
        )
    )
    recovered_ids = {
        entry["id"] for entry in fetch_report.get("entries", []) if entry.get("status") == "downloaded"
    }
    recovered_entities = recovered_ids & {
        entity_id.removeprefix("tlidb:cn:") for entity_id in by_id
    }
    case_id = "tlidb:cn:Necklace_of_Firebird"
    case_entity = by_id.get(case_id)
    case_pages = [page for page in legendary_pages if page.get("entity_id") == case_id]
    case_page = case_pages[0] if case_pages else None
    raw = repo / "data/raw/manifests/legendary_gear/raw_html/Necklace_of_Firebird.html"
    html = raw.read_text(encoding="utf-8", errors="replace") if raw.is_file() else ""
    errors = []
    if health != {
        "manifest_pages": 339,
        "raw_present": 339,
        "nonempty_raw": 339,
        "zero_byte_raw": 0,
        "missing_raw": 0,
    }:
        errors.append("legendary source recovery is incomplete")
    if len(entities) != 332:
        errors.append(f"expected 332 legendary entities, got {len(entities)}")
    if classification_errors:
        errors.append(f"legendary classification errors: {len(classification_errors)}")
    if len(legendary_pages) != 332:
        errors.append(f"expected 332 legendary search entries, got {len(legendary_pages)}")
    return {
        "source": health,
        "legendary_entities": {
            "expected": 332,
            "actual": len(entities),
            "recovered_from_empty_raw": len(recovered_entities),
            "classification_errors": len(classification_errors),
            "excluded_non_equipment": len(NON_EQUIPMENT_IDS),
        },
        "case_study": {
            "name": "淬火之鸟的颈链",
            "raw_nonempty": bool(html),
            "ss13_present": "SS13赛季" in html,
            "ss12_history_present": "SS12赛季" in html,
            "entity_present": case_entity is not None,
            "entity_type": (case_entity or {}).get("entity_type"),
            "classification_correct": bool(
                case_entity
                and case_entity.get("content_category_id") == "equipment"
                and case_entity.get("content_subcategory_id") == "equipment_legendary"
            ),
            "search_present": case_page is not None,
            "search_system_id": (case_page or {}).get("system_id"),
            "legendary_filter_match": bool(
                case_page
                and case_page.get("content_category_id") == "equipment"
                and case_page.get("content_subcategory_id") == "equipment_legendary"
            ),
            "craft_duplicate_suppressed": len(case_pages) == 1
            and (case_page or {}).get("system_id") == "legendary_gear",
        },
        "search": {
            "legendary_entries": len(legendary_pages),
            "unique_legendary_routes": len(
                {entity_route_key(page.get("route") or "") for page in legendary_pages}
            ),
            "craft_owned_legendary_entries": sum(
                page.get("system_id") == "craft" for page in legendary_pages
            ),
        },
        "search_schema": search_index.get("schema_version"),
        "errors": errors,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument(
        "--entity-index", type=Path, default=Path("data/generated/entity-index-v3.json")
    )
    parser.add_argument(
        "--search-index", type=Path, default=Path("local_wiki/ss13/site/search-index.json")
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/reports/local-wiki/legendary-refetch-recovery-v1-report.json"),
    )
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    entity_path = args.entity_index if args.entity_index.is_absolute() else repo / args.entity_index
    search_path = args.search_index if args.search_index.is_absolute() else repo / args.search_index
    report_path = args.report if args.report.is_absolute() else repo / args.report
    entity_index = json.loads(entity_path.read_text(encoding="utf-8"))
    search_index = json.loads(search_path.read_text(encoding="utf-8"))
    refreshed, _ = refresh_search_ownership(search_index, entity_index)
    search_path.write_text(json.dumps(refreshed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = build_recovery_report(repo, entity_index, refreshed)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
