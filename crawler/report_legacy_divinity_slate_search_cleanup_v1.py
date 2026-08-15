from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from crawler.build_full_wiki_mirror import (
    LEGACY_DIVINITY_SLATE_SUBCATEGORY,
    apply_search_visibility_policy,
    local_assets,
)


CURRENT_TALENT_SUBCATEGORIES = (
    "talent_hero",
    "talent_new_god",
    "talent_nether_king_entity",
    "talent_ethereal_prism",
)
POLLUTION_QUERIES = ("全部", "技能等级", "中型天赋", "异界", "奖励", "累计击败")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def is_visible(page: dict) -> bool:
    return page.get("entity_visibility") != "hidden"


def case_study(page: dict | None) -> dict:
    if page is None:
        return {"present": False}
    return {
        "present": True,
        "id": page.get("id"),
        "title": page.get("entity_title_zh") or page.get("title"),
        "system_id": page.get("system_id"),
        "entity_id": page.get("entity_id"),
        "entity_type": page.get("entity_type"),
        "visibility_before": page.get("entity_visibility"),
        "category": page.get("content_category_id"),
        "subcategory": page.get("content_subcategory_id"),
        "route": page.get("route"),
        "search_ownership": "legacy/support page result",
        "plain_text_source": "v1 page HTML extraction / retained generated search document",
        "visible_after_policy": is_visible(apply_search_visibility_policy(dict(page))),
    }


def build_report(root: Path) -> dict:
    search = load_json(root / "local_wiki/ss13/site/search-index.json")
    entities = load_json(root / "data/generated/entity-index-v3.json").get("entities", [])
    structured = load_json(
        root / "data/generated/structured/ss13/structured-search-index.json"
    )
    tree = load_json(root / "config/game_content_tree.json")
    pages = search.get("pages", [])
    legacy = [
        page for page in pages
        if page.get("content_subcategory_id") == LEGACY_DIVINITY_SLATE_SUBCATEGORY
    ]
    legacy_entities = [
        entity for entity in entities
        if entity.get("content_subcategory_id") == LEGACY_DIVINITY_SLATE_SUBCATEGORY
    ]
    structured_records = structured.get("records", [])
    legacy_structured = [
        record for record in structured_records
        if record.get("content_subcategory_id") == LEGACY_DIVINITY_SLATE_SUBCATEGORY
    ]
    after = [apply_search_visibility_policy(dict(page)) for page in legacy]
    visible_tree_children = {
        child.get("id")
        for category in tree.get("search_categories", [])
        if category.get("search_visibility") == "primary"
        for child in category.get("children", [])
        if child.get("search_visibility") != "hidden"
    }
    source_app = local_assets()["_local/search/app.js"]
    deployed_app_path = root / "local_wiki/ss13/site/_local/search/app.js"
    deployed_app = deployed_app_path.read_text(encoding="utf-8")
    pollution = {}
    for query in POLLUTION_QUERIES:
        matches = [
            page.get("id") for page in legacy
            if query.casefold() in f"{page.get('title', '')} {page.get('plain_text', '')}".casefold()
        ]
        pollution[query] = {"count": len(matches), "examples": matches[:5]}

    current_regression = {}
    structured_distribution = Counter(
        record.get("content_subcategory_id") for record in structured_records
    )
    for subcategory in CURRENT_TALENT_SUBCATEGORIES:
        relevant = [page for page in pages if page.get("content_subcategory_id") == subcategory]
        current_regression[subcategory] = {
            "page_results": len(relevant),
            "visible_page_results": sum(is_visible(page) for page in relevant),
            "structured_records": structured_distribution[subcategory],
        }

    manifest_paths = (
        root / "sources/inventory_manifest.json",
        root / "sources/path_of_progression_manifest.json",
    )
    raw_paths = (
        root / "data/raw/manifests/inventory/raw_html/Divinity_Slate.html",
        root / "data/raw/manifests/path_of_progression/raw_html/Divinity_Slate.html",
    )
    report = {
        "schema_version": 1,
        "root_cause": {
            "generation": "search visibility policy only guarded legacy inventory fallbacks, not the stable talent_divinity_slate classification",
            "runtime": "old generated Search Index entries were visible and runtime accepted them in the unfiltered All view",
            "grouping": "result grouping preferred content_subcategory_name_zh, producing the 神格石板 group",
        },
        "legacy_scope": {
            "entries": len(legacy),
            "entities": len(legacy_entities),
            "routes": sorted({page.get("route") for page in legacy}),
            "source_systems": sorted({page.get("system_id") for page in legacy}),
        },
        "before": {
            "visible_page_results": sum(is_visible(page) for page in legacy),
            "category_group": sorted({page.get("content_subcategory_name_zh") for page in legacy}),
            "plain_text_pollution": pollution,
        },
        "cleanup": {
            "generation_guard": "content_subcategory_id == talent_divinity_slate sets entity_visibility=hidden",
            "runtime_guard": "isLegacyDivinitySlate excludes v1 and structured results and entity-source aggregation",
            "raw_preserved": all(path.is_file() and path.stat().st_size > 0 for path in raw_paths),
            "manifest_preserved": all(path.is_file() for path in manifest_paths),
            "entity_preserved": len(legacy_entities) == len(legacy),
        },
        "after": {
            "visible_divinity_slate_results": sum(is_visible(page) for page in after),
            "structured_records": len(legacy_structured),
        },
        "current_talent_regression": current_regression,
        "content_tree_status": {
            "legacy_primary_entry_present": LEGACY_DIVINITY_SLATE_SUBCATEGORY in visible_tree_children,
            "current_talent_children": sorted(
                visible_tree_children.intersection(CURRENT_TALENT_SUBCATEGORIES)
            ),
            "modified": False,
        },
        "case_studies": {
            "Divinity_Slate": case_study(next((p for p in legacy if p.get("id") == "Divinity_Slate"), None)),
            "Jagged_Primocryst": case_study(next((p for p in legacy if p.get("id") == "Jagged_Primocryst"), None)),
        },
        "search_schema": search.get("schema_version"),
        "structured_total": structured.get("record_count", len(structured_records)),
        "runtime_status": {
            "source_guard": "const isLegacyDivinitySlate=" in source_app,
            "deployed_guard": "const isLegacyDivinitySlate=" in deployed_app,
        },
        "errors": [],
    }
    if report["after"]["visible_divinity_slate_results"]:
        report["errors"].append("legacy Divinity Slate results remain visible after policy")
    if report["after"]["structured_records"]:
        report["errors"].append("legacy Divinity Slate structured records exist")
    if report["content_tree_status"]["legacy_primary_entry_present"]:
        report["errors"].append("legacy Divinity Slate remains in the primary Content Tree")
    if report["search_schema"] != 8:
        report["errors"].append("Search schema changed")
    if report["structured_total"] != 28780:
        report["errors"].append("Structured Search total changed")
    if not all(report["runtime_status"].values()):
        report["errors"].append("runtime guard is missing")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    report = build_report(args.root)
    output = args.root / "data/reports/local-wiki/legacy-divinity-slate-search-cleanup-v1.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "legacy_entries": report["legacy_scope"]["entries"],
        "visible_before": report["before"]["visible_page_results"],
        "visible_after": report["after"]["visible_divinity_slate_results"],
        "structured_records": report["after"]["structured_records"],
        "errors": report["errors"],
    }, ensure_ascii=False))
    return int(bool(report["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
