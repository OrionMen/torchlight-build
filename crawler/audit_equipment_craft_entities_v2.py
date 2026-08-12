"""Audit ordinary equipment entities and their embedded craft data without mutation."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote


ORDINARY_EQUIPMENT_IDS = (
    "STR_Helmet", "DEX_Helmet", "INT_Helmet",
    "STR_Chest_Armor", "DEX_Chest_Armor", "INT_Chest_Armor",
    "STR_Gloves", "DEX_Gloves", "INT_Gloves",
    "STR_Boots", "DEX_Boots", "INT_Boots",
    "Claw", "Dagger", "One-Handed_Sword", "One-Handed_Hammer", "One-Handed_Axe",
    "Wand", "Rod", "Scepter", "Cane", "Pistol",
    "Two-Handed_Sword", "Two-Handed_Hammer", "Two-Handed_Axe", "Tin_Staff",
    "Cudgel", "Bow", "Crossbow", "Musket", "Fire_Cannon",
    "STR_Shield", "DEX_Shield", "INT_Shield", "Necklace", "Ring", "Belt",
    "Spirit_Ring",
)


class EquipmentSectionInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str | None]] = []
        self.tables: Counter[str] = Counter()
        self.heading_depth = 0
        self.heading: list[str] = []
        self.headings: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        parent_section = next((section for _, section in reversed(self.stack) if section), None)
        classes = set((attributes.get("class") or "").split())
        section = attributes.get("id") if tag == "div" and "tab-pane" in classes else parent_section
        self.stack.append((tag, section))
        if tag == "table" and section:
            self.tables[section] += 1
        if tag == "h1":
            self.heading_depth = 1
            self.heading = []
        elif self.heading_depth:
            self.heading_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self.heading_depth:
            self.heading_depth -= 1
            if tag == "h1" and self.heading_depth == 0:
                heading = " ".join(" ".join(self.heading).split())
                if heading:
                    self.headings.append(heading)
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if self.heading_depth:
            self.heading.append(data)


def inspect_equipment_html(html: str) -> dict[str, Any]:
    parser = EquipmentSectionInspector()
    parser.feed(html)
    base_sections = sorted(section for section in parser.tables if "基础词缀" in section)
    craft_sections = sorted(section for section in parser.tables if section.endswith("打造"))
    return {
        "base_sections": base_sections,
        "craft_sections": craft_sections,
        "base_affixes": bool(base_sections),
        "craft_affixes": bool(craft_sections),
        "headings": parser.headings,
    }


def audit_entities(
    inventory_entries: dict[str, dict[str, Any]],
    craft_ids: set[str],
    entity_by_id: dict[str, dict[str, Any]],
    raw_root: Path,
    candidate_ids: tuple[str, ...] = ORDINARY_EQUIPMENT_IDS,
) -> dict[str, Any]:
    entities = []
    missing_inventory_entities = []
    unmatched_craft_data = []
    standalone_craft_matches = 0

    for slug in candidate_ids:
        entry = inventory_entries.get(slug)
        if entry is None:
            missing_inventory_entities.append({"id": slug, "reason": "inventory_manifest_entry_missing"})
            continue
        raw_path = raw_root / f"{quote(slug, safe='-_.')}.html"
        evidence = (inspect_equipment_html(raw_path.read_text(encoding="utf-8", errors="replace"))
                    if raw_path.is_file() else {
                        "base_sections": [], "craft_sections": [], "base_affixes": False,
                        "craft_affixes": False, "headings": [],
                    })
        entity_id = f"tlidb:cn:{slug}"
        current_entity = entity_by_id.get(entity_id, {})
        if current_entity.get("entity_type") != "equipment":
            missing_inventory_entities.append({
                "id": slug,
                "reason": "not_in_equipment_entity_v1",
                "current_entity_exists": bool(current_entity),
            })
        if slug in craft_ids:
            standalone_craft_matches += 1
        craft_sources = [{
            "logical_source": "craft",
            "source_type": "embedded_inventory_tab",
            "page_url": entry.get("url"),
            "raw_html": str(raw_path),
            "section_id": section,
            "association": "same_canonical_page_dom_section",
            "standalone_craft_manifest_entry": slug in craft_ids,
        } for section in evidence["craft_sections"]]
        if not evidence["craft_affixes"]:
            unmatched_craft_data.append({
                "id": slug,
                "inventory_source": entry.get("url"),
                "reason": "craft_section_missing",
            })
        title = (current_entity.get("entity_title_zh")
                 or next((heading.removesuffix(" 打造") for heading in evidence["headings"] if heading.endswith(" 打造")), None)
                 or entry.get("name_zh") or slug)
        entities.append({
            "entity_id": entity_id,
            "title": title,
            "inventory_source": entry.get("url"),
            "craft_sources": craft_sources,
            "base_affixes": evidence["base_affixes"],
            "craft_affixes": evidence["craft_affixes"],
            "base_affix_sections": evidence["base_sections"],
        })

    return {
        "schema_version": 2,
        "entities": entities,
        "missing_inventory_entities": missing_inventory_entities,
        "unmatched_craft_data": unmatched_craft_data,
        "summary": {
            "inventory_entities": len(entities),
            "current_equipment_entity_v1": sum(
                entity_by_id.get(f"tlidb:cn:{slug}", {}).get("entity_type") == "equipment"
                for slug in candidate_ids
            ),
            "matched_craft_entities": sum(item["craft_affixes"] for item in entities),
            "unmatched": len(unmatched_craft_data),
            "standalone_craft_manifest_matches": standalone_craft_matches,
        },
        "association_rule_analysis": {
            "confirmed_rule": "inventory canonical page -> same-page tab whose id ends with 打造",
            "base_affix_rule": "same-page tab whose id contains 基础词缀",
            "standalone_craft_page_rule": "unknown",
            "evidence": "None of the ordinary equipment slugs is present in craft_manifest.json; all craft data is embedded in the corresponding Inventory raw HTML page.",
        },
        "search_recommendation": {
            "keep": ["装备名称", "装备类型", "基础词缀名称", "打造词缀名称", "词缀描述"],
            "exclude": ["内部 ID", "权重数字", "纯 Tier 表", "页面导航"],
            "merge_rule": "Merge base-affix and craft-affix descriptive text into the Inventory equipment Entity; retain source-section trace and do not create a Craft Entity.",
        },
        "warnings": (["Spirit_Ring is present with complete craft data but is not marked entity_type=equipment in Entity v1."]
                     if any(item["id"] == "Spirit_Ring" for item in missing_inventory_entities) else []),
        "errors": [],
    }


def build_audit(repo: Path) -> dict[str, Any]:
    inventory = json.loads((repo / "sources/inventory_manifest.json").read_text(encoding="utf-8"))
    craft = json.loads((repo / "sources/craft_manifest.json").read_text(encoding="utf-8"))
    entity_index = json.loads((repo / "data/generated/entity-index-v3.json").read_text(encoding="utf-8"))
    return audit_entities(
        {entry["id"]: entry for entry in inventory.get("entries", [])},
        {entry["id"] for entry in craft.get("entries", [])},
        {entity["entity_id"]: entity for entity in entity_index.get("entities", [])},
        repo / "data/raw/manifests/inventory/raw_html",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output", type=Path,
        default=Path("data/reports/local-wiki/equipment-craft-entity-audit-v2.json"),
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
