"""Audit local Vorax equipment pages without changing Entity or Search data."""

from __future__ import annotations

import argparse
import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote


VORAX_ENTITY_IDS = (
    "Vorax_Limb:_Head",
    "Vorax_Limb:_Chest",
    "Vorax_Limb:_Hands",
    "Vorax_Limb:_Legs",
    "Vorax_Aberrant_Limb:_Legs",
    "Vorax_Limb:_Neck",
    "Vorax_Limb:_Digits",
    "Vorax_Aberrant_Limb:_Digits",
    "Vorax_Limb:_Waist",
    "Vorax_Aberrant_Limb:_Waist",
)
SECTION_IDS = ("打造", "传奇品质", "基础词缀")
VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


class VoraxPageInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, Any]] = []
        self.headings: list[dict[str, str | None]] = []
        self.heading: dict[str, Any] | None = None
        self.modifier_ids: dict[str, set[str]] = {section: set() for section in SECTION_IDS}
        self.table_counts: dict[str, int] = {section: 0 for section in SECTION_IDS}
        self.legendary_links: set[str] = set()
        self.current_entity_cards = 0

    def _section(self) -> str | None:
        return next((frame["section"] for frame in reversed(self.stack) if frame["section"]), None)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        section = self._section()
        if tag == "div" and "tab-pane" in classes and attributes.get("id"):
            section = attributes["id"]
        frame = {"tag": tag, "section": section}
        if tag not in VOID_ELEMENTS:
            self.stack.append(frame)
        if tag == "h1":
            self.heading = {"text": [], "section": section}
        modifier_id = attributes.get("data-modifier-id")
        if modifier_id and section in self.modifier_ids:
            self.modifier_ids[section].add(modifier_id)
        if tag == "table" and section in self.table_counts:
            self.table_counts[section] += 1
        if tag == "a" and section == "传奇品质" and attributes.get("data-hover"):
            href = attributes.get("href")
            if href:
                self.legendary_links.add(href)
        if (
            tag == "div"
            and "popupItem" in classes
            and "previousItem" not in classes
            and section
            and section.startswith("渴瘾")
        ):
            self.current_entity_cards += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1" and self.heading is not None:
            text = " ".join(" ".join(self.heading["text"]).split())
            if text:
                self.headings.append({"text": text, "section": self.heading["section"]})
            self.heading = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if self.heading is not None:
            self.heading["text"].append(data)


class InventoryDirectoryInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.item_type_links = 0
        self.vorax_links = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attributes = dict(attrs)
        if (attributes.get("data-i18n") or "").startswith("item_type_list|name|"):
            self.item_type_links += 1
            if "Vorax_" in (attributes.get("href") or ""):
                self.vorax_links += 1


def inspect_vorax_html(html: str) -> dict[str, Any]:
    parser = VoraxPageInspector()
    parser.feed(html)
    entity_headings = [
        item["text"] for item in parser.headings if str(item["text"]).startswith("渴瘾")
    ]
    return {
        "entity_title": entity_headings[-1] if entity_headings else None,
        "current_entity_card_count": parser.current_entity_cards,
        "base_affix_modifier_count": len(parser.modifier_ids["基础词缀"]),
        "base_affix_table_count": parser.table_counts["基础词缀"],
        "craft_affix_modifier_count": len(parser.modifier_ids["打造"]),
        "craft_affix_table_count": parser.table_counts["打造"],
        "legendary_quality_item_count": len(parser.legendary_links),
        "legendary_quality_section_count": int(
            any(item["section"] == "传奇品质" for item in parser.headings)
            or parser.table_counts["传奇品质"] > 0
            or bool(parser.legendary_links)
        ),
    }


def build_audit(repo: Path) -> dict[str, Any]:
    manifest = json.loads((repo / "sources/inventory_manifest.json").read_text(encoding="utf-8"))
    by_id = {entry["id"]: entry for entry in manifest.get("entries", [])}
    raw_root = repo / "data/raw/manifests/inventory/raw_html"
    entities = []
    for entity_id in VORAX_ENTITY_IDS:
        entry = by_id[entity_id]
        path = raw_root / f"{quote(entry['slug'], safe='-_.')}.html"
        evidence = inspect_vorax_html(path.read_text(encoding="utf-8", errors="replace"))
        confirmed = bool(
            evidence["entity_title"]
            and evidence["current_entity_card_count"]
            and evidence["base_affix_table_count"]
            and evidence["craft_affix_table_count"]
            and evidence["legendary_quality_section_count"]
        )
        entities.append({
            "id": entity_id,
            "slug": entry["slug"],
            "url": entry["url"],
            "title": evidence["entity_title"] or entry.get("name_zh") or entity_id,
            "classification": "vorax_entity" if confirmed else "unknown",
            "entity_confirmed": confirmed,
            **evidence,
        })

    directory_path = repo / "local_wiki/ss13/site/cn/Inventory/index.html"
    directory = InventoryDirectoryInspector()
    if directory_path.is_file():
        directory.feed(directory_path.read_text(encoding="utf-8", errors="replace"))

    def section_rows(kind: str, count_field: str) -> list[dict[str, Any]]:
        return [{
            "entity_id": item["id"],
            "section": kind,
            "detected": item[count_field] > 0,
            "item_count": item[count_field],
        } for item in entities]

    return {
        "schema_version": 1,
        "entities": entities,
        "base_affix_sections": section_rows("基础词缀", "base_affix_modifier_count"),
        "craft_affix_sections": section_rows("打造", "craft_affix_modifier_count"),
        "legendary_quality_sections": section_rows(
            "传奇品质", "legendary_quality_item_count"
        ),
        "category_pages": [{
            "id": "Inventory",
            "route": "/cn/Inventory/",
            "display_role": "装备类型",
            "classification": "category_page",
            "item_type_link_count": directory.item_type_links,
            "vorax_link_count": directory.vorax_links,
            "search_visibility_recommendation": "hidden",
        }],
        "summary": {
            "expected_entities": len(VORAX_ENTITY_IDS),
            "confirmed_entities": sum(item["entity_confirmed"] for item in entities),
            "with_base_affixes": sum(item["base_affix_modifier_count"] > 0 for item in entities),
            "with_craft_affixes": sum(item["craft_affix_modifier_count"] > 0 for item in entities),
            "with_legendary_quality": sum(item["legendary_quality_item_count"] > 0 for item in entities),
        },
        "search_recommendation": {
            "include": ["装备名称", "基础词缀", "打造词条", "传奇品质"],
            "exclude": ["装备类型目录", "导航", "内部 ID", "Tier/Weight", "数据表"],
            "category_page_visibility": "hidden",
            "entity_page_visibility": "visible",
            "note": "Only modifier text is searchable; Tier, Weight, and table metadata are excluded.",
        },
        "warnings": [],
        "errors": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/reports/local-wiki/vorax-equipment-audit-v1.json"),
    )
    args = parser.parse_args()
    repo = args.repo.resolve()
    output = args.output if args.output.is_absolute() else repo / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(build_audit(repo), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
