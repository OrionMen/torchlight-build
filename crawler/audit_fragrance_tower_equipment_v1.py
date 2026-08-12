"""Audit fragrance ritual and tower sequence pages as equipment Entity sources."""

from __future__ import annotations

import argparse
import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote


VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


class EquipmentSystemPageInspector(HTMLParser):
    """Collect only records inside the named active content tab."""

    def __init__(self, section_id: str, row_tag: str) -> None:
        super().__init__(convert_charrefs=True)
        self.section_id = section_id
        self.row_tag = row_tag
        self.stack: list[dict[str, Any]] = []
        self.row: dict[str, Any] | None = None
        self.records: list[dict[str, Any]] = []
        self.anchor: dict[str, Any] | None = None
        self.current_item_cards = 0
        self.section_found = False

    def _section(self) -> str | None:
        return next(
            (frame["section"] for frame in reversed(self.stack) if frame["section"]),
            None,
        )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        section = attributes.get("id") or self._section()
        if attributes.get("id") == self.section_id:
            self.section_found = True
        frame = {"tag": tag, "section": section}
        if tag not in VOID_ELEMENTS:
            self.stack.append(frame)

        if (
            self.row is None
            and section == self.section_id
            and tag == self.row_tag
            and (tag != "div" or "col" in classes)
        ):
            self.row = {
                "frame": frame,
                "text": [],
                "modifier_ids": [],
                "record_ids": [],
                "chips": [],
                "links": [],
            }

        if self.row is not None:
            for attribute, key in (
                ("data-modifier-id", "modifier_ids"),
                ("data-id", "record_ids"),
                ("data-chip", "chips"),
            ):
                value = attributes.get(attribute)
                if value:
                    self.row[key].append(value)
            if tag == "a" and attributes.get("href"):
                self.anchor = {
                    "frame": frame,
                    "href": attributes["href"],
                    "text": [],
                }

        if (
            tag == "div"
            and "popupItem" in classes
            and "previousItem" not in classes
            and section == self.section_id
        ):
            self.current_item_cards += 1

    def handle_data(self, data: str) -> None:
        if self.row is not None:
            self.row["text"].append(data)
        if self.anchor is not None:
            self.anchor["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] != tag:
                continue
            removed = self.stack[index:]
            del self.stack[index:]
            if self.anchor and any(
                frame is self.anchor["frame"] for frame in removed
            ):
                self.row["links"].append({
                    "href": self.anchor["href"],
                    "name_zh": " ".join(" ".join(self.anchor["text"]).split()),
                })
                self.anchor = None
            if self.row and any(frame is self.row["frame"] for frame in removed):
                if self.row["modifier_ids"]:
                    self.records.append({
                        "text": " ".join(" ".join(self.row["text"]).split()),
                        "modifier_ids": list(dict.fromkeys(self.row["modifier_ids"])),
                        "record_ids": list(dict.fromkeys(self.row["record_ids"])),
                        "chips": list(dict.fromkeys(self.row["chips"])),
                        "links": self.row["links"],
                    })
                self.row = None
            break


class ItemPageInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.current_item_cards = 0
        self.headings: list[str] = []
        self.heading: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "h1":
            self.heading = []
        if tag == "div" and "popupItem" in classes and "previousItem" not in classes:
            self.current_item_cards += 1

    def handle_data(self, data: str) -> None:
        if self.heading is not None:
            self.heading.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1" and self.heading is not None:
            value = " ".join(" ".join(self.heading).split())
            if value:
                self.headings.append(value)
            self.heading = None


def inspect_system_html(html: str, section_id: str, row_tag: str) -> dict[str, Any]:
    parser = EquipmentSystemPageInspector(section_id, row_tag)
    parser.feed(html)
    material_links: dict[str, str] = {}
    for record in parser.records:
        for link in record["links"]:
            href = link["href"]
            if href and not href.startswith(("/", "http", "#", "javascript:")):
                material_links.setdefault(href, link["name_zh"])
    return {
        "section_found": parser.section_found,
        "record_count": len(parser.records),
        "modifier_id_count": len({
            modifier_id
            for record in parser.records
            for modifier_id in record["modifier_ids"]
        }),
        "canonical_record_page_count": 0,
        "current_item_card_count": parser.current_item_cards,
        "material_links": [
            {"slug": slug, "name_zh": name}
            for slug, name in material_links.items()
        ],
        "record_examples": [{
            "text": record["text"],
            "modifier_ids": record["modifier_ids"],
            "record_ids": record["record_ids"],
            "chips": record["chips"],
            "materials": record["links"],
        } for record in parser.records[:3]],
    }


def _material_pages(repo: Path, links: list[dict[str, str]]) -> list[dict[str, Any]]:
    raw_root = repo / "data/raw/manifests/recovered_internal_pages/raw_html"
    result = []
    for link in links:
        slug = link["slug"]
        path = raw_root / f"{quote(slug, safe='-_.')}.html"
        inspector = ItemPageInspector()
        if path.is_file():
            inspector.feed(path.read_text(encoding="utf-8", errors="replace"))
        result.append({
            "id": slug,
            "title": link["name_zh"] or slug,
            "route": f"/cn/{slug}/",
            "classification": "material_page",
            "raw_status": "available" if path.is_file() else "missing",
            "current_item_card_count": inspector.current_item_cards,
            "headings": inspector.headings,
            "entity_recommendation": "exclude_from_equipment_entity",
        })
    return result


def build_audit(repo: Path) -> dict[str, Any]:
    help_root = repo / "data/raw/manifests/help/raw_html"
    fragrance = inspect_system_html(
        (help_root / "Blending_Rituals.html").read_text(encoding="utf-8", errors="replace"),
        "调香秘仪",
        "div",
    )
    tower = inspect_system_html(
        (help_root / "TOWER_Sequence.html").read_text(encoding="utf-8", errors="replace"),
        "高塔序列",
        "tr",
    )
    materials = _material_pages(repo, fragrance["material_links"])
    fragrance_categories = [
        {
            "id": "Blending_Rituals",
            "route": "/cn/Blending_Rituals/",
            "classification": "category_page",
            "role": "ritual_recipe_index",
        },
        {
            "id": "Aromatic_Material",
            "route": "/cn/Aromatic_Material/",
            "classification": "category_page",
            "role": "material_index",
        },
    ]
    tower_categories = [{
        "id": "TOWER_Sequence",
        "route": "/cn/TOWER_Sequence/",
        "classification": "category_page",
        "role": "sequence_modifier_index",
    }]
    include = ["装备名称", "固有效果", "属性", "特殊词条"]
    exclude = ["导航", "内部 ID", "Tier", "Weight", "材料列表", "赛季说明"]
    return {
        "schema_version": 1,
        "fragrance_ritual": {
            "total_pages": len(fragrance_categories) + len(materials),
            "entity_count": 0,
            "non_entity_page_count": len(fragrance_categories) + len(materials),
            "entities": [],
            "category_pages": fragrance_categories,
            "material_pages": materials,
            "noise_pages": [{
                "id": "Blending_Rituals#embedded_recipe_records",
                "classification": "noise_page",
                "record_count": fragrance["record_count"],
                "reason": "embedded modifier/recipe rows have no canonical entity page",
            }],
            "embedded_recipe_count": fragrance["record_count"],
            "modifier_id_count": fragrance["modifier_id_count"],
            "one_page_one_equipment_entity": False,
            "recommendation": "Do not create equipment Entities from the current page set. Treat 97 ritual rows as recipe/modifier data and the linked pages as materials.",
            "evidence": fragrance,
        },
        "tower_sequence": {
            "total_pages": len(tower_categories),
            "entity_count": 0,
            "non_entity_page_count": len(tower_categories),
            "entities": [],
            "category_pages": tower_categories,
            "material_pages": [],
            "noise_pages": [{
                "id": "TOWER_Sequence#embedded_sequence_records",
                "classification": "noise_page",
                "record_count": tower["record_count"],
                "reason": "embedded modifier rows have no canonical entity page",
            }],
            "embedded_sequence_count": tower["record_count"],
            "modifier_id_count": tower["modifier_id_count"],
            "one_page_one_equipment_entity": False,
            "recommendation": "Do not create standalone equipment Entities. The 408 rows are sequence modifier data associated with equipment types.",
            "evidence": tower,
        },
        "search_recommendation": {
            "include_for_future_confirmed_equipment_entities": include,
            "exclude": exclude,
            "current_category_page_visibility": "hidden",
            "current_material_page_entity_visibility": "not_equipment_entity",
            "current_embedded_record_visibility": "not_standalone_entity",
        },
        "conclusion": {
            "fragrance_entity_model_confirmed": False,
            "tower_entity_model_confirmed": False,
            "reason": "Neither system exposes one canonical detail page per equipment object in the audited local snapshots.",
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
        default=Path(
            "data/reports/local-wiki/fragrance-tower-equipment-audit-v1.json"
        ),
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
