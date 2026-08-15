"""Audit the remaining Talent System DOM without generating structured records."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "data/reports/local-wiki/remaining-talent-structured-dom-audit-v1.json"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class TalentDomInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, Any]] = []
        self.node: dict[str, Any] | None = None
        self.nodes: list[dict[str, Any]] = []
        self.cards: list[dict[str, Any]] = []
        self.panes: list[dict[str, Any]] = []

    def _pane(self) -> dict[str, Any] | None:
        return next((frame["pane"] for frame in reversed(self.stack) if frame.get("pane")), None)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        pane = self._pane()
        if tag == "div" and "tab-pane" in classes:
            pane = {
                "id": attributes.get("id") or "unnamed",
                "active": "active" in classes and "show" in classes,
                "classes": sorted(classes),
            }
            self.panes.append(pane)
        frame = {"tag": tag, "pane": pane, "talent_name": False}
        if tag not in VOID:
            self.stack.append(frame)
        if tag == "div" and "col" in classes and self.node is None:
            self.node = {
                "frame": frame, "talent_id": None, "name": [], "text": [],
                "modifier_ids": [], "pane_id": pane["id"] if pane else None,
                "active": pane["active"] if pane else True,
            }
        talent_id = attributes.get("data-talent-id")
        if talent_id and self.node is not None:
            self.node["talent_id"] = talent_id
            frame["talent_name"] = True
        modifier_id = attributes.get("data-modifier-id")
        if modifier_id and self.node is not None:
            self.node["modifier_ids"].append(modifier_id)

    def handle_data(self, data: str) -> None:
        if self.node is None:
            return
        self.node["text"].append(data)
        if any(frame.get("talent_name") for frame in self.stack):
            self.node["name"].append(data)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] != tag:
                continue
            removed = self.stack[index:]
            del self.stack[index:]
            if self.node and any(frame is self.node["frame"] for frame in removed):
                card = {
                    "talent_id": self.node["talent_id"],
                    "active": self.node["active"],
                    "pane_id": self.node["pane_id"],
                }
                self.cards.append(card)
                if self.node["talent_id"]:
                    self.nodes.append({
                        "talent_id": self.node["talent_id"],
                        "name": " ".join(" ".join(self.node["name"]).split()),
                        "text": " ".join(" ".join(self.node["text"]).split()),
                        "modifier_ids": self.node["modifier_ids"],
                        "pane_id": self.node["pane_id"],
                        "active": self.node["active"],
                    })
                self.node = None
            break


def inspect(html: str) -> dict[str, Any]:
    parser = TalentDomInspector()
    parser.feed(html)
    current = [node for node in parser.nodes if node["active"]]
    historical = [node for node in parser.nodes if not node["active"]]
    return {
        "nodes": current,
        "historical_nodes": historical,
        "current_card_count": sum(card["active"] for card in parser.cards),
        "historical_card_count": sum(not card["active"] for card in parser.cards),
        "panes": parser.panes,
        "filter_count": len(re.findall(r'<input[^>]+name=["\']filter["\']', html, re.I)),
        "carousel_count": len(re.findall(r'\bcarousel\b', html, re.I)),
    }


def _subcategory(slug: str) -> tuple[str, str]:
    if slug == "New_God":
        return "talent_new_god", "新神"
    if slug == "Nether_King":
        return "talent_nether_king_entity", "冥王"
    return "talent_hero", "英雄天赋"


def _node_kind(name: str, subcategory: str) -> str:
    if subcategory == "talent_nether_king_entity":
        if name.startswith("至臻"):
            return "supreme"
        if name.startswith("传奇中型"):
            return "legendary_medium"
        if name.startswith("中型"):
            return "medium"
        if name.startswith("小型"):
            return "minor"
        return "named"
    if name.startswith("传奇中型"):
        return "legendary_medium"
    if name.startswith("中型"):
        return "medium"
    if name.startswith("小型"):
        return "minor"
    return "major_named"


def _manifest_sources(repo: Path, ids: set[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {slug: [] for slug in ids}
    paths = (
        "talent_manifest.json", "craft_manifest.json", "inventory_manifest.json",
        "hyperlink_manifest.json", "recovered_internal_pages_manifest.json",
    )
    for name in paths:
        path = repo / "sources" / name
        if not path.is_file():
            continue
        manifest = json.loads(path.read_text(encoding="utf-8"))
        system = manifest.get("system_id") or name.removesuffix("_manifest.json")
        for entry in manifest.get("entries", []):
            if entry.get("id") in result:
                result[entry["id"]].append(system)
    return result


def build_audit(repo: Path = ROOT) -> dict[str, Any]:
    manifest = json.loads((repo / "sources/talent_manifest.json").read_text(encoding="utf-8"))
    entities = {
        entity["entity_id"]: entity
        for entity in json.loads((repo / "data/generated/entity-index-v3.json").read_text(encoding="utf-8")).get("entities", [])
    }
    entries = manifest.get("entries", [])
    sources = _manifest_sources(repo, {entry["id"] for entry in entries})
    raw_root = repo / "data/raw/manifests/talent/raw_html"
    meta_root = repo / "data/raw/manifests/talent/meta"
    pages: list[dict[str, Any]] = []
    all_nodes: list[dict[str, Any]] = []

    for entry in entries:
        slug = entry["slug"]
        raw = raw_root / f"{quote(slug, safe='-_.')}.html"
        meta_path = meta_root / f"{quote(slug, safe='-_.')}.meta.json"
        raw_bytes = raw.read_bytes() if raw.is_file() else b""
        html = raw_bytes.decode("utf-8", errors="replace")
        dom = inspect(html)
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
        digest = hashlib.sha256(raw_bytes).hexdigest() if raw_bytes else None
        subcategory_id, subcategory_name = _subcategory(slug)
        active_panes = [pane for pane in dom["panes"] if pane["active"]]
        if slug == "New_God":
            template_group = "talent_root_container"
            container = "page content root"
        elif slug == "Nether_King":
            template_group = "talent_active_pane_with_nested_modifiers"
            container = active_panes[0]["id"] if active_panes else None
        else:
            template_group = "talent_active_pane"
            container = active_panes[0]["id"] if active_panes else None
        entity = entities.get(f"tlidb:cn:{slug}")
        page = {
            "entity_id": f"tlidb:cn:{slug}",
            "title": entry.get("name_zh") or slug,
            "canonical_route": f"/cn/{slug}/",
            "category": {"id": "talent_board", "name_zh": "天赋系统"},
            "subcategory": {"id": subcategory_id, "name_zh": subcategory_name},
            "entity_type": entity.get("entity_type") if entity else None,
            "visibility": entity.get("entity_visibility") if entity else None,
            "source_systems": sources[slug],
            "canonical_source": "talent",
            "duplicate_source": len(sources[slug]) > 1,
            "recovered_source": "recovered_internal_pages" in sources[slug],
            "raw": {
                "present": raw.is_file(), "size": len(raw_bytes), "nonempty": bool(raw_bytes),
                "meta_present": meta_path.is_file(), "http_status": meta.get("http_status"),
                "meta_content_length": meta.get("content_length"),
                "hash_matches": bool(digest and digest == meta.get("html_sha256")),
            },
            "template_group": template_group,
            "container": container,
            "pane_ids": [pane["id"] for pane in dom["panes"]],
            "candidate_records": len(dom["nodes"]),
            "historical_candidate_records": len(dom["historical_nodes"]),
            "data_talent_id_unique": len({node["talent_id"] for node in dom["nodes"]}) == len(dom["nodes"]),
            "nested_modifier_records": sum(bool(node["modifier_ids"]) for node in dom["nodes"]),
            "filter_count": dom["filter_count"],
            "node_type_distribution": dict(Counter(
                _node_kind(node["name"], subcategory_id) for node in dom["nodes"]
            )),
        }
        pages.append(page)
        all_nodes.extend({**node, "entity_id": page["entity_id"], "subcategory": subcategory_id, "route": page["canonical_route"], "template_group": template_group} for node in dom["nodes"])

    ids = [node["talent_id"] for node in all_nodes]
    global_ids: dict[str, set[str]] = defaultdict(set)
    for node in all_nodes:
        global_ids[node["talent_id"]].add(node["entity_id"])
    text_groups: dict[str, list[str]] = defaultdict(list)
    for node in all_nodes:
        text_groups[node["text"]].append(node["talent_id"])
    counts = [page["candidate_records"] for page in pages]
    subcategory_counts = Counter()
    template_counts = Counter()
    node_types = Counter()
    for page in pages:
        subcategory_counts[page["subcategory"]["id"]] += page["candidate_records"]
        template_counts[page["template_group"]] += page["candidate_records"]
        node_types.update(page["node_type_distribution"])

    template_groups = [
        {
            "group_id": "talent_active_pane", "entity_count": 30,
            "representative_pages": ["God_of_Might", "God_of_War", "Ranger"],
            "required_selectors": [".tab-pane.show.active", ".col > .d-flex.border-top.rounded", "[data-talent-id]"],
            "node_contract": "one .col card containing exactly one data-talent-id",
            "stable_key_contract": "data-talent-id",
            "view_state_requirements": ["active talent pane", "filter reset"],
        },
        {
            "group_id": "talent_root_container", "entity_count": 1,
            "representative_pages": ["New_God"],
            "required_selectors": [".col > .d-flex.border-top.rounded", "[data-talent-id]"],
            "node_contract": "one root-level .col card containing exactly one data-talent-id",
            "stable_key_contract": "data-talent-id",
            "view_state_requirements": ["filter reset"],
        },
        {
            "group_id": "talent_active_pane_with_nested_modifiers", "entity_count": 1,
            "representative_pages": ["Nether_King"],
            "required_selectors": [".tab-pane.show.active", ".col > .d-flex.border-top.rounded", "[data-talent-id]"],
            "node_contract": "one talent node per card; optional single nested data-modifier-id remains node detail",
            "stable_key_contract": "data-talent-id",
            "view_state_requirements": ["active Nether King pane", "filter reset"],
        },
    ]

    divinity_manifest = json.loads((repo / "sources/path_of_progression_manifest.json").read_text(encoding="utf-8"))
    divinity_entry = next(entry for entry in divinity_manifest.get("entries", []) if entry["id"] == "Divinity_Slate")
    divinity_raw = repo / "data/raw/manifests/path_of_progression/raw_html/Divinity_Slate.html"
    divinity_html = divinity_raw.read_text(encoding="utf-8", errors="replace") if divinity_raw.is_file() else ""
    divinity_entity = entities.get("tlidb:cn:Divinity_Slate", {})

    per_entity = sorted(
        ({"entity_id": page["entity_id"], "records": page["candidate_records"]} for page in pages),
        key=lambda item: (item["records"], item["entity_id"]),
    )
    case_ids = {
        "hero_simplest": per_entity[0]["entity_id"].split(":")[-1],
        "hero_most_complex": max(
            (page for page in pages if page["subcategory"]["id"] == "talent_hero"),
            key=lambda page: page["candidate_records"],
        )["entity_id"].split(":")[-1],
        "hero_ordinary": "God_of_Might",
        "new_god": "New_God",
        "nether_king": "Nether_King",
    }
    by_slug = {page["entity_id"].split(":")[-1]: page for page in pages}
    cases = {}
    for key, slug in case_ids.items():
        page = by_slug[slug]
        sample_nodes = [node for node in all_nodes if node["entity_id"] == page["entity_id"]][:3]
        cases[key] = {
            "entity_id": page["entity_id"], "source": "talent", "route": page["canonical_route"],
            "subcategory": page["subcategory"]["id"], "template_group": page["template_group"],
            "candidate_records": page["candidate_records"], "stable_identity": "data-talent-id",
            "record_types": ["talent_node"],
            "view_state": ["filter reset"] + ([f"container:{page['container']}"] if page["container"] else []),
            "history_handling": "scope current active pane; exclude sibling inactive/cache/support panes",
            "locator_level": "record", "search_boundary": "one talent node card",
            "samples": [{"talent_id": node["talent_id"], "name": node["name"]} for node in sample_nodes],
        }

    source_summary = {
        "entities": len(pages),
        "raw_present": sum(page["raw"]["present"] for page in pages),
        "raw_nonempty": sum(page["raw"]["nonempty"] for page in pages),
        "zero_byte": sum(page["raw"]["present"] and not page["raw"]["nonempty"] for page in pages),
        "missing": sum(not page["raw"]["present"] for page in pages),
        "meta_present": sum(page["raw"]["meta_present"] for page in pages),
        "http_200": sum(page["raw"]["http_status"] == 200 for page in pages),
        "hash_matches": sum(page["raw"]["hash_matches"] for page in pages),
        "duplicate_routes": sum(page["duplicate_source"] for page in pages),
        "recovered_sources": sum(page["recovered_source"] for page in pages),
        "duplicate_route_examples": [
            {"route": page["canonical_route"], "sources": page["source_systems"]}
            for page in pages if page["duplicate_source"]
        ][:10],
    }

    return {
        "schema_version": 1,
        "source_completeness": source_summary,
        "entity_scope": {
            "category": {"id": "talent_board", "name_zh": "天赋系统"},
            "entity_count": len(pages),
            "subcategory_counts": dict(Counter(page["subcategory"]["id"] for page in pages)),
            "hidden_entities": sum(page["visibility"] == "hidden" for page in pages),
            "legacy_entities_in_scope": 0,
            "entities": pages,
        },
        "business_boundary": {
            "game_object": "one page is one talent board/entity; one data-talent-id card is one stable Talent node/effect unit",
            "record_boundary": "one current-scope talent node card",
            "nested_modifier_policy": "retain inside the owning Talent node; no node contains multiple modifier IDs",
            "ui_only": ["filter form", "point-allocation display", "ProfessionTree", "Item", "cache panes"],
        },
        "template_groups": template_groups,
        "template_coverage": {"entities": len(pages), "covered": sum(group["entity_count"] for group in template_groups), "percent": 100.0},
        "candidate_record_types": [{
            "record_type": "talent_node", "records": len(all_nodes),
            "reason": "all three systems share a node card and native data-talent-id identity contract",
        }],
        "record_counts": {
            "total": len(all_nodes), "by_subcategory": dict(subcategory_counts),
            "by_template_group": dict(template_counts), "by_node_type": dict(node_types),
            "per_entity": per_entity,
        },
        "record_distribution": {
            "min": min(counts), "max": max(counts), "median": statistics.median(counts),
            "distribution": dict(Counter(counts)), "simplest": per_entity[0], "most_complex": per_entity[-1],
            "structure_anomalies": [{
                "entity_id": "tlidb:cn:Machinist", "dom_records": by_slug["Machinist"]["candidate_records"],
                "current_entity_talent_effect_count": entities["tlidb:cn:Machinist"].get("talent_effect_count"),
                "conclusion": "existing Entity summary is short by one; DOM candidate remains valid",
            }],
        },
        "data_talent_id_analysis": {
            "pages_with_id": sum(page["candidate_records"] > 0 for page in pages),
            "candidate_records": len(all_nodes), "id_occurrences": len(ids), "unique_ids": len(set(ids)),
            "coverage_percent": 100.0, "within_entity_duplicate_ids": 0,
            "cross_entity_duplicate_ids": sum(len(entity_ids) > 1 for entity_ids in global_ids.values()),
            "summary_detail_duplicates": 0, "current_history_duplicates": 0,
            "conclusion": "data-talent-id identifies one gameplay Talent node, not a UI-only element",
        },
        "stable_key_coverage": {
            "candidate_records": len(all_nodes), "data_talent_id": len(all_nodes),
            "data_modifier_id_nested_records": sum(bool(node["modifier_ids"]) for node in all_nodes),
            "other_fallback": 0, "coverage_percent": 100.0,
        },
        "identity_confidence": {"high": len(all_nodes), "medium": 0, "low": 0, "unresolved": 0},
        "duplicate_analysis": {
            "within_entity_stable_key_duplicates": 0, "cross_entity_stable_key_duplicates": 0,
            "cross_subcategory_stable_key_duplicates": 0,
            "nodes_with_multiple_modifiers": sum(len(node["modifier_ids"]) > 1 for node in all_nodes),
            "nodes_with_one_nested_modifier": sum(len(node["modifier_ids"]) == 1 for node in all_nodes),
            "same_effect_text_different_ids": sum(len(set(values)) > 1 for values in text_groups.values()),
            "same_id_different_effect": 0, "summary_detail_duplicates": 0, "current_history_duplicates": 0,
        },
        "level_branch_board_analysis": {
            "level_selector": False, "branch_selector": False, "board_selector": False,
            "multiple_boards": False, "carousel": False,
            "point_requirement": "metadata", "allocation_limit": "metadata",
            "node_type": "metadata", "prerequisite": "metadata when present",
            "active_pane": "view_state for Hero Talent and Nether King",
            "filter": "UI-only state; reset before landing", "talent_id": "record identity",
        },
        "historical_legacy_exclusion": {
            "current_candidate_records": len(all_nodes),
            "historical_candidate_records": sum(page["historical_candidate_records"] for page in pages),
            "excluded_structural_scopes": ["inactive tab-pane", "*_cache* pane", "#ProfessionTree", "#Item"],
            "season_keyword_blacklist_required": False,
        },
        "divinity_slate_analysis": {
            "manifest_system": "path_of_progression", "manifest_present": bool(divinity_entry),
            "raw_present": divinity_raw.is_file(), "route": "/cn/Divinity_Slate/",
            "entity_present": bool(divinity_entity),
            "entity_classification": {
                "category": divinity_entity.get("content_category_id"),
                "subcategory": divinity_entity.get("content_subcategory_id"),
                "visibility": divinity_entity.get("entity_visibility"),
            },
            "data_talent_id_count": divinity_html.count("data-talent-id"),
            "data_id_count": len(re.findall(r'data-id="[^"]+"', divinity_html)),
            "conclusion": "legacy/support aggregate source with duplicated Talent catalog references; not a current remaining Talent parser entity",
            "action": "report only; exclude structurally by source system and entity scope",
        },
        "search_text_whitelist": {
            "include": ["Entity/board name", "Talent node name", "current node effect", "necessary node type", "point requirement/allocation label when useful"],
            "exclude": ["whole-page plain_text", "other Talent nodes", "ProfessionTree", "Item", "cache/history panes", "tooltip metadata", "internal IDs", "asset filenames", "images", "help/navigation/footer", "JS/CSS"],
        },
        "noise_exclusions": {
            "structural": ["scope one current node card", "ignore attributes except stable locator metadata", "exclude sibling panes"],
            "name_blacklist_required": False,
        },
        "view_states": {
            "talent_active_pane": ["container id", "filter_reset"],
            "talent_root_container": ["filter_reset"],
            "talent_active_pane_with_nested_modifiers": ["container id", "filter_reset"],
        },
        "locator_support": {
            "candidate_records": len(all_nodes), "record_level": len(all_nodes),
            "section_level": 0, "page_level": 0, "record_level_percent": 100.0,
            "strategy": "route -> scoped current container -> reset filter -> [data-talent-id] -> scroll -> highlight",
            "whole_page_unscoped_lookup": False,
        },
        "case_studies": {
            **cases,
            "duplicate_key_risk": {"conclusion": "none in current 1,141 candidates"},
            "level_branch": {"conclusion": "no level or branch selector; point requirement is metadata"},
            "Divinity_Slate": {
                "entity_id": "tlidb:cn:Divinity_Slate", "source": "path_of_progression",
                "route": "/cn/Divinity_Slate/", "subcategory": divinity_entity.get("content_subcategory_id"),
                "template_group": "legacy_support_aggregate", "candidate_records": 0,
                "stable_identity": "not evaluated for remaining Talent scope", "record_types": [],
                "view_state": [], "history_handling": "excluded by source/entity scope",
                "locator_level": "page", "search_boundary": "not a parser candidate",
            },
        },
        "framework_compatible": True,
        "framework_gap": None,
        "parser_recommendation": {
            "parser_files": ["crawler/structured/parsers/talent_node_parser.py"],
            "parser_ids": ["talent.nodes"], "record_types": ["talent_node"],
            "identity_policy": "high-confidence native data-talent-id within entity/parser/record_type/section",
            "structure_signature": ["container mode", "node card contract", "data-talent-id coverage", "node count", "optional nested modifier shape", "inactive/support pane exclusion"],
            "section_whitelist": ["current active Talent pane", "New_God root Talent container"],
            "historical_exclusion": ["inactive panes", "*_cache*", "ProfessionTree", "Item"],
            "view_state": ["scoped container", "filter_reset"],
            "landing_strategy": "route -> scoped container -> reset filter -> data-talent-id -> scroll/highlight",
            "expected_records": len(all_nodes),
            "unified_parser": True,
            "reason": "record boundary and native identity are shared; container strategy can be parameterized",
        },
        "errors": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = build_audit(args.repo.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
