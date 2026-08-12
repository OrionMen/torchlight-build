"""Generate presentation-focused Entity Index v3 from Entity Index v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from crawler.audit_legendary_gear_v1 import LegendaryPageInspector
from crawler.audit_ethereal_prism_v1 import EtherealPrismInspector
from crawler.audit_fragrance_tower_equipment_v1 import EquipmentSystemPageInspector
from crawler.audit_vorax_equipment_v1 import VORAX_ENTITY_IDS, inspect_vorax_html
from crawler.audit_talent_system_entity_v1 import TalentPageInspector
from crawler.build_full_wiki_mirror import entity_route_key
from crawler.parse_hero import parse_hero_html


CHINESE = re.compile(r"[\u3400-\u9fff]")
NOISE_PATTERNS = (
    re.compile(r"\bInfo\s+id\s*:\s*[^\s]+", re.I),
    re.compile(r"\bShow\s+Description\b", re.I),
    re.compile(r"\bTier\s+name\b", re.I),
    re.compile(r"\b(?:Details|Simple|Alts)\b", re.I),
    re.compile(r"\bID\s*:\s*[^\s]+", re.I),
    re.compile(r"\bUpdate\s+cookie\s+preferences\b", re.I),
)
ORDINARY_EQUIPMENT_IDS = {
    "STR_Helmet", "DEX_Helmet", "INT_Helmet",
    "STR_Chest_Armor", "DEX_Chest_Armor", "INT_Chest_Armor",
    "STR_Gloves", "DEX_Gloves", "INT_Gloves",
    "STR_Boots", "DEX_Boots", "INT_Boots",
    "Claw", "Dagger", "One-Handed_Sword", "One-Handed_Hammer", "One-Handed_Axe",
    "Wand", "Rod", "Scepter", "Cane", "Pistol",
    "Two-Handed_Sword", "Two-Handed_Hammer", "Two-Handed_Axe", "Tin_Staff",
    "Cudgel", "Bow", "Crossbow", "Musket", "Fire_Cannon",
    "STR_Shield", "DEX_Shield", "INT_Shield", "Necklace", "Ring", "Belt", "Spirit_Ring",
}


class _LegendaryEntityParser(LegendaryPageInspector):
    def __init__(self) -> None:
        super().__init__()
        self.corrosion_visible_text: list[str] = []

    def handle_data(self, data: str) -> None:
        card = self.current_card()
        if card and card.get("kind") == "corrosion":
            value = " ".join(data.split())
            if value and value.casefold() != "corroded":
                self.corrosion_visible_text.append(value)
        super().handle_data(data)


class _VoraxSummaryParser(HTMLParser):
    """Extract modifier text and visible legendary cards from the three Vorax tabs."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, Any]] = []
        self.capture: dict[str, Any] | None = None
        self.base_affixes: list[str] = []
        self.craft_affixes: list[str] = []
        self.legendary_quality: list[str] = []

    def _section(self) -> str | None:
        return next((frame["section"] for frame in reversed(self.stack) if frame["section"]), None)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        section = self._section()
        if tag == "div" and "tab-pane" in classes and attributes.get("id"):
            section = attributes["id"]
        frame = {"tag": tag, "section": section}
        if tag not in {
            "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "param", "source", "track", "wbr",
        }:
            self.stack.append(frame)
        if self.capture is not None:
            return
        if attributes.get("data-modifier-id") and section in {"基础词缀", "打造"}:
            self.capture = {"kind": section, "frame": frame, "text": []}
        elif tag == "div" and section == "传奇品质" and "flex-grow-1" in classes:
            self.capture = {"kind": section, "frame": frame, "text": []}

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] != tag:
                continue
            removed = self.stack[index:]
            del self.stack[index:]
            if self.capture and any(frame is self.capture["frame"] for frame in removed):
                value = " ".join(" ".join(self.capture["text"]).split())
                if value:
                    target = {
                        "基础词缀": self.base_affixes,
                        "打造": self.craft_affixes,
                        "传奇品质": self.legendary_quality,
                    }[self.capture["kind"]]
                    target.append(value)
                self.capture = None
            break

    def handle_data(self, data: str) -> None:
        if self.capture is not None:
            self.capture["text"].append(data)


class _HeadingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.h1_depth = 0
        self.blocked_depth = 0
        self.current: list[str] = []
        self.headings: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "h1":
            self.h1_depth = 1
            self.current = []
        elif self.h1_depth:
            self.h1_depth += 1
            if tag in {"a", "button", "small", "svg", "script", "style"}:
                self.blocked_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if not self.h1_depth:
            return
        if tag in {"a", "button", "small", "svg", "script", "style"} and self.blocked_depth:
            self.blocked_depth -= 1
        self.h1_depth -= 1
        if tag == "h1" and self.h1_depth == 0:
            heading = " ".join(" ".join(self.current).split())
            if heading:
                self.headings.append(heading)

    def handle_data(self, data: str) -> None:
        if self.h1_depth and not self.blocked_depth:
            self.current.append(data)


class _PactFateSummaryParser(HTMLParser):
    """Extract only visible entity-card content from Pact/Fate pages."""

    def __init__(self, entity_kind: str) -> None:
        super().__init__(convert_charrefs=True)
        if entity_kind not in {"pact_spirit", "fate"}:
            raise ValueError(f"unsupported Pact/Fate entity kind: {entity_kind}")
        self.entity_kind = entity_kind
        self.stack: list[dict[str, Any]] = []
        self.capture_depth = 0
        self.blocked_depth = 0
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        capture = tag == "h1"
        blocked = tag in {"script", "style", "nav", "footer", "table"}
        if self.entity_kind == "pact_spirit":
            capture = capture or "popupItem" in classes or (
                tag == "div" and {"flex-grow-1", "ms-2"} <= classes
            )
        else:
            if "previousItem" in classes or "item_ver" in classes:
                blocked = True
            capture = capture or (
                tag == "div"
                and {"ui_item", "popupItem"} <= classes
                and "previousItem" not in classes
            )
        frame = {"tag": tag, "capture": capture, "blocked": blocked}
        if tag not in {
            "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "param", "source", "track", "wbr",
        }:
            self.stack.append(frame)
            self.capture_depth += int(capture)
            self.blocked_depth += int(blocked)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] != tag:
                continue
            removed = self.stack[index:]
            del self.stack[index:]
            self.capture_depth -= sum(frame["capture"] for frame in removed)
            self.blocked_depth -= sum(frame["blocked"] for frame in removed)
            break

    def handle_data(self, data: str) -> None:
        if self.capture_depth and not self.blocked_depth:
            value = " ".join(data.split())
            if value:
                self.text.append(value)

    def summary(self, title: str) -> str:
        return " ".join(_unique_text([title, *self.text]))


class _EquipmentSummaryParser(HTMLParser):
    """Extract Item text plus only the Modifier column from base/craft tables."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str | None, bool]] = []
        self.item_text: list[str] = []
        self.base_modifiers: list[str] = []
        self.craft_modifiers: list[str] = []
        self.table: dict[str, Any] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def _finish_cell(self) -> None:
        if self.cell is not None:
            if self.row is None:
                self.row = []
            self.row.append(" ".join(" ".join(self.cell).split()))
            self.cell = None

    def _finish_row(self) -> None:
        self._finish_cell()
        if self.table is None or self.row is None:
            return
        normalized = [value.casefold() for value in self.row]
        if "modifier" in normalized:
            self.table["modifier_index"] = normalized.index("modifier")
        else:
            index = self.table.get("modifier_index")
            if index is not None and index < len(self.row) and self.row[index]:
                target = (self.base_modifiers if "基础词缀" in self.table["section"]
                          else self.craft_modifiers)
                target.append(self.row[index])
        self.row = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        parent_section = next((section for _, section, _ in reversed(self.stack) if section), None)
        classes = set((attributes.get("class") or "").split())
        section = (attributes.get("id") if tag == "div" and "tab-pane" in classes
                   else parent_section)
        blocked = tag in {"script", "style", "form", "nav", "footer"}
        void_element = tag in {
            "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "param", "source", "track", "wbr",
        }
        if void_element:
            return
        self.stack.append((tag, section, blocked))
        if tag == "table" and section and ("基础词缀" in section or section.endswith("打造")):
            self.table = {"section": section, "modifier_index": None}
        elif self.table is not None and tag == "tr":
            self._finish_row()
            self.row = []
        elif self.table is not None and tag in {"td", "th"}:
            self._finish_cell()
            self.cell = []

    def handle_endtag(self, tag: str) -> None:
        if self.table is not None and tag in {"td", "th"}:
            self._finish_cell()
        elif self.table is not None and tag in {"tr", "thead", "tbody"}:
            self._finish_row()
        elif self.table is not None and tag == "table":
            self._finish_row()
            self.table = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if any(blocked for _, _, blocked in self.stack):
            return
        if self.table is not None and self.cell is not None:
            self.cell.append(data)
        elif any(section == "Item" for _, section, _ in self.stack):
            self.item_text.append(data)


class _MemoryAffixParser(HTMLParser):
    """Extract only Modifier cells from the five verified memory affix tabs."""

    SECTIONS = ("基础属性", "固有词缀", "随机词缀", "复苏词缀", "复苏词缀（月相）")

    def __init__(self, allowed_sections: tuple[str, ...]) -> None:
        super().__init__(convert_charrefs=True)
        unknown = set(allowed_sections) - set(self.SECTIONS)
        if unknown:
            raise ValueError(f"unknown memory sections: {sorted(unknown)}")
        self.allowed_sections = set(allowed_sections)
        self.stack: list[tuple[str, str | None]] = []
        self.affixes: dict[str, list[str]] = {
            section: [] for section in allowed_sections
        }
        self.table: dict[str, Any] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def _finish_cell(self) -> None:
        if self.cell is not None:
            if self.row is None:
                self.row = []
            self.row.append(" ".join(" ".join(self.cell).split()))
            self.cell = None

    def _finish_row(self) -> None:
        self._finish_cell()
        if self.table is None or self.row is None:
            return
        normalized = [value.casefold() for value in self.row]
        if "modifier" in normalized:
            self.table["modifier_index"] = normalized.index("modifier")
        else:
            index = self.table.get("modifier_index")
            if index is not None and index < len(self.row) and self.row[index]:
                self.affixes[self.table["section"]].append(self.row[index])
        self.row = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        section = next((value for _, value in reversed(self.stack) if value), None)
        if tag == "div" and "tab-pane" in classes:
            section = (
                attributes.get("id")
                if attributes.get("id") in self.allowed_sections
                else None
            )
        if tag not in {
            "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "param", "source", "track", "wbr",
        }:
            self.stack.append((tag, section))
        if tag == "table" and section in self.allowed_sections:
            self.table = {"section": section, "modifier_index": None}
        elif self.table is not None and tag == "tr":
            self._finish_row()
            self.row = []
        elif self.table is not None and tag in {"td", "th"}:
            self._finish_cell()
            self.cell = []

    def handle_endtag(self, tag: str) -> None:
        if self.table is not None and tag in {"td", "th"}:
            self._finish_cell()
        elif self.table is not None and tag in {"tr", "thead", "tbody"}:
            self._finish_row()
        elif self.table is not None and tag == "table":
            self._finish_row()
            self.table = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if self.table is not None and self.cell is not None:
            self.cell.append(data)


def clean_title(value: str) -> str:
    title = " ".join((value or "").split())
    for marker in (" - 火炬编年史", " - Torchlight: Infinite Wiki"):
        if marker in title:
            title = title.split(marker, 1)[0].strip()
    return title


def clean_summary(value: str, route: str, titles: list[str]) -> str:
    text = value or ""
    slug = route.removeprefix("/cn/").removesuffix("/")
    removable = {slug, unquote(slug), quote(unquote(slug), safe="-_.")}
    removable.update(title for title in titles if title)
    for token in sorted(removable, key=len, reverse=True):
        text = re.sub(re.escape(token), " ", text, flags=re.I)
    for pattern in NOISE_PATTERNS:
        text = pattern.sub(" ", text)
    text = re.sub(r"\s+-\s+火炬编年史\s*,?\s*Torchlight:\s*Infinite\s*Wiki", " ", text, flags=re.I)
    return " ".join(text.split())


def _manifest_titles(repo: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    system_manifest = json.loads((repo / "sources/system_manifest.json").read_text(encoding="utf-8"))
    paths = [repo / item["manifest_path"] for item in system_manifest.get("systems", []) if item.get("manifest_path")]
    recovered = repo / "sources/recovered_internal_pages_manifest.json"
    if recovered.is_file():
        paths.append(recovered)
    for path in paths:
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data.get("entries", []):
            url = entry.get("url") or entry.get("path")
            title = entry.get("name_zh") or entry.get("name")
            if not url or not title or not CHINESE.search(str(title)):
                continue
            route = entity_route_key(url)
            if title not in result[route]:
                result[route].append(str(title))
    return result


def _i18n_titles(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, str] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str) and CHINESE.search(value):
                result[str(key).casefold()] = value
    return result


def _raw_heading(repo: Path, entity: dict[str, Any], search_page: dict[str, Any] | None) -> str | None:
    slug = entity["canonical_route"].removeprefix("/cn/").removesuffix("/")
    systems = [source.get("system_id") for source in entity.get("sources", [])]
    if search_page and search_page.get("system_id"):
        systems.insert(0, search_page["system_id"])
    for system_id in dict.fromkeys(system for system in systems if system):
        path = repo / "data/raw/manifests" / system_id / "raw_html" / f"{quote(slug, safe='-_.')}.html"
        if not path.is_file():
            continue
        parser = _HeadingParser()
        parser.feed(path.read_text(encoding="utf-8", errors="replace"))
        for heading in parser.headings:
            if CHINESE.search(heading):
                if (
                    entity.get("content_subcategory_id") == "equipment_type"
                    and heading.endswith(" 打造")
                ):
                    heading = heading[:-len(" 打造")].strip()
                return heading
    return None


def _equipment_summary(repo: Path, slug: str, title_zh: str) -> str:
    path = repo / "data/raw/manifests/inventory/raw_html" / f"{quote(slug, safe='-_.')}.html"
    if not path.is_file():
        return title_zh
    parser = _EquipmentSummaryParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    item_text = " ".join(" ".join(parser.item_text).split())
    item_text = re.sub(r"\bItem\s*/\s*\d+\b", " ", item_text, flags=re.I)

    def unique(values: list[str]) -> list[str]:
        seen: set[str] = set()
        return [value for value in values if value and not (value in seen or seen.add(value))]

    parts = [title_zh, item_text]
    if parser.base_modifiers:
        parts.extend(["基础词缀", " ".join(unique(parser.base_modifiers))])
    if parser.craft_modifiers:
        parts.extend(["打造词缀", " ".join(unique(parser.craft_modifiers))])
    return " ".join(" ".join(parts).split())


def _legendary_entities(repo: Path) -> tuple[set[str], dict[str, dict[str, Any]]]:
    manifest = json.loads(
        (repo / "sources/legendary_gear_manifest.json").read_text(encoding="utf-8")
    )
    ids = {entry["id"] for entry in manifest.get("entries", [])}
    result: dict[str, dict[str, Any]] = {}
    raw_root = repo / "data/raw/manifests/legendary_gear/raw_html"
    for entry in manifest.get("entries", []):
        path = raw_root / f"{quote(entry['slug'], safe='-_.')}.html"
        if not path.is_file() or not path.stat().st_size:
            continue
        parser = _LegendaryEntityParser()
        parser.feed(path.read_text(encoding="utf-8", errors="replace"))
        if not parser.current_cards or parser.talent_slate_markers:
            continue
        title = entry.get("name_zh") or entry["id"]
        parts = [title]
        if parser.current_effects:
            parts.extend(["主效果", *parser.current_effects])
        corrosion_effects = parser.corrosion_effects or parser.corrosion_visible_text
        if corrosion_effects:
            parts.extend(["已侵蚀效果", *corrosion_effects])
        result[entry["id"]] = {
            "title": title,
            "clean_summary": " ".join(" ".join(parts).split()),
            "has_corrosion": bool(corrosion_effects),
        }
    return ids, result


def _unique_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _vorax_entities(repo: Path) -> dict[str, dict[str, Any]]:
    raw_root = repo / "data/raw/manifests/inventory/raw_html"
    result: dict[str, dict[str, Any]] = {}
    for slug in VORAX_ENTITY_IDS:
        path = raw_root / f"{quote(slug, safe='-_.')}.html"
        if not path.is_file() or not path.stat().st_size:
            continue
        html = path.read_text(encoding="utf-8", errors="replace")
        evidence = inspect_vorax_html(html)
        if not evidence["entity_title"] or not evidence["current_entity_card_count"]:
            continue
        parser = _VoraxSummaryParser()
        parser.feed(html)
        base = _unique_text(parser.base_affixes)
        craft = _unique_text(parser.craft_affixes)
        legendary = _unique_text(parser.legendary_quality)
        if not base or not craft or not legendary:
            continue
        title = evidence["entity_title"]
        result[slug] = {
            "title": title,
            "base_affixes": base,
            "craft_affixes": craft,
            "legendary_quality": legendary,
            "clean_summary": " ".join([
                title,
                "基础词缀", *base,
                "打造词条", *craft,
                "传奇品质", *legendary,
            ]),
        }
    return result


def _equipment_related_system_entities(repo: Path) -> list[dict[str, Any]]:
    help_root = repo / "data/raw/manifests/help/raw_html"
    definitions = (
        {
            "slug": "Blending_Rituals",
            "title": "调香秘仪",
            "section": "调香秘仪",
            "row_tag": "div",
            "subcategory_id": "equipment_related_fragrance",
            "search_system_id": "equipment_related_fragrance",
            "source_role": "fragrance_affix_system",
        },
        {
            "slug": "TOWER_Sequence",
            "title": "高塔序列",
            "section": "高塔序列",
            "row_tag": "tr",
            "subcategory_id": "equipment_related_tower_sequence",
            "search_system_id": "equipment_related_tower_sequence",
            "source_role": "tower_sequence_affix_system",
        },
    )
    entities = []
    for definition in definitions:
        raw_path = help_root / f"{definition['slug']}.html"
        if not raw_path.is_file():
            continue
        parser = EquipmentSystemPageInspector(
            definition["section"], definition["row_tag"]
        )
        parser.feed(raw_path.read_text(encoding="utf-8", errors="replace"))
        rows = []
        for record in parser.records:
            text = record["text"]
            if definition["slug"] == "Blending_Rituals":
                material_names = [
                    link["name_zh"] for link in record["links"] if link["name_zh"]
                ]
                starts = [text.find(name) for name in material_names if name in text]
                if starts:
                    text = text[:min(starts)]
                text = re.sub(r"\s+Lv\.0\b", "", text, flags=re.I)
            else:
                text = re.sub(r"\b\d+(?:\|\d+)+\b", " ", text)
            text = " ".join(text.split())
            if text:
                rows.append(text)
        clean = " ".join([definition["title"], *dict.fromkeys(rows)])
        entities.append({
            "entity_id": f"tlidb:cn:{definition['slug']}",
            "title": definition["title"],
            "canonical_route": f"/cn/{definition['slug']}/",
            "entity_title_zh": definition["title"],
            "entity_visibility": "visible",
            "entity_type": "equipment_related_system",
            "clean_summary": clean,
            "content_category_id": "equipment_related",
            "content_category_name_zh": "装备相关",
            "content_subcategory_id": definition["subcategory_id"],
            "content_subcategory_name_zh": definition["title"],
            "search_system_id": definition["search_system_id"],
            "sources": [{
                "source_type": "help",
                "role": definition["source_role"],
            }],
            "confidence": "primary",
            "record_count": len(parser.records),
        })
    return entities


def _talent_entities(repo: Path) -> dict[str, dict[str, Any]]:
    manifest = json.loads(
        (repo / "sources/talent_manifest.json").read_text(encoding="utf-8")
    )
    raw_root = repo / "data/raw/manifests/talent/raw_html"
    result = {}
    for entry in manifest.get("entries", []):
        path = raw_root / f"{quote(entry['slug'], safe='-_.')}.html"
        if not path.is_file() or not path.stat().st_size:
            continue
        parser = TalentPageInspector()
        parser.feed(path.read_text(encoding="utf-8", errors="replace"))
        effects = list(dict.fromkeys(
            " ".join(item["text"].split())
            for item in parser.talents
            if item["active_tab"] and " ".join(item["text"].split())
        ))
        if not effects:
            continue
        if entry["id"] == "New_God":
            subcategory_id = "talent_new_god"
            subcategory_name = "新神"
        elif entry["id"] == "Nether_King":
            subcategory_id = "talent_nether_king_entity"
            subcategory_name = "冥王"
        else:
            subcategory_id = "talent_hero"
            subcategory_name = "英雄天赋"
        title = entry.get("name_zh") or entry["id"]
        result[entry["id"]] = {
            "title": title,
            "clean_summary": " ".join([title, *effects]),
            "talent_effect_count": len(effects),
            "subcategory_id": subcategory_id,
            "subcategory_name_zh": subcategory_name,
        }
    return result


def _ethereal_prism_entity(repo: Path) -> dict[str, Any] | None:
    path = repo / "data/raw/manifests/inventory/raw_html/Ethereal_Prism.html"
    if not path.is_file() or not path.stat().st_size:
        return None
    parser = EtherealPrismInspector()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    base_rows = parser.rows["基础词缀"]
    random_rows = parser.rows["随机词缀"]
    base_affixes = _unique_text(
        " ".join(row["text"].split()) for row in base_rows
    )
    random_affixes = _unique_text(
        " ".join(row["text"].split()) for row in random_rows
    )
    if not base_affixes or not random_affixes:
        return None
    return {
        "title": "异度棱镜",
        "base_affixes": base_affixes,
        "random_affixes": random_affixes,
        "base_affix_count": len(base_rows),
        "random_affix_count": len(random_rows),
        "excluded_item_pages": len(parser.item_links),
        "clean_summary": " ".join([
            "异度棱镜",
            "基础词缀", *base_affixes,
            "随机词缀", *random_affixes,
        ]),
    }


def _hero_entities(repo: Path) -> dict[str, dict[str, Any]]:
    manifest = json.loads(
        (repo / "sources/hero_manifest.json").read_text(encoding="utf-8")
    )
    raw_root = repo / "data/raw/manifests/hero/raw_html"
    result: dict[str, dict[str, Any]] = {}
    for entry in manifest.get("entries", []):
        path = raw_root / f"{quote(entry['slug'], safe='-_.')}.html"
        if not path.is_file() or not path.stat().st_size:
            continue
        raw = path.read_bytes()
        parsed = parse_hero_html(
            raw.decode("utf-8", errors="replace"),
            entity_id=entry["id"],
            name_zh=entry.get("name_zh") or entry["id"],
            page_url=entry["url"],
            raw_sha256=hashlib.sha256(raw).hexdigest(),
        )
        effects = _unique_text(
            effect["text"]
            for node in parsed["nodes"]
            for level in node["levels"]
            for effect in level["effects"]
        )
        node_names = _unique_text(node["name"] for node in parsed["nodes"])
        title = entry.get("name_zh") or parsed["name_zh"] or entry["id"]
        result[entry["id"]] = {
            "title": title,
            "clean_summary": " ".join(
                " ".join([
                    title,
                    parsed["summary"],
                    *node_names,
                    *effects,
                ]).split()
            ),
            "trait_node_count": len(parsed["nodes"]),
            "trait_effect_count": len(effects),
        }
    return result


def _memory_system_entity(repo: Path) -> dict[str, Any] | None:
    hero_path = repo / "data/raw/manifests/inventory/raw_html/Hero_Memories.html"
    revival_path = repo / "data/raw/manifests/help/raw_html/Memory_Revival.html"
    if any(
        not path.is_file() or not path.stat().st_size
        for path in (hero_path, revival_path)
    ):
        return None
    hero_parser = _MemoryAffixParser(("基础属性", "固有词缀", "随机词缀"))
    hero_parser.feed(hero_path.read_text(encoding="utf-8", errors="replace"))
    revival_parser = _MemoryAffixParser(("复苏词缀", "复苏词缀（月相）"))
    revival_parser.feed(revival_path.read_text(encoding="utf-8", errors="replace"))
    source_affixes = {**hero_parser.affixes, **revival_parser.affixes}
    row_counts = {
        section: len(values) for section, values in source_affixes.items()
    }
    affixes = {
        section: _unique_text(values) for section, values in source_affixes.items()
    }
    if any(not affixes[section] for section in _MemoryAffixParser.SECTIONS):
        return None
    return {
        "title": "英雄追忆",
        "affixes": affixes,
        "row_counts": row_counts,
        "clean_summary": " ".join([
            "英雄追忆",
            "基础属性", *affixes["基础属性"],
            "固有词缀", *affixes["固有词缀"],
            "随机词缀", *affixes["随机词缀"],
            "普通复苏词缀", *affixes["复苏词缀"],
            "复苏词缀（月相）", *affixes["复苏词缀（月相）"],
        ]),
    }


def _pact_fate_summaries(repo: Path, system_id: str, entity_kind: str) -> dict[str, str]:
    manifest = json.loads(
        (repo / f"sources/{system_id}_manifest.json").read_text(encoding="utf-8")
    )
    raw_root = repo / "data/raw/manifests" / system_id / "raw_html"
    result: dict[str, str] = {}
    for entry in manifest.get("entries", []):
        slug = entry.get("slug") or entry.get("id")
        path = raw_root / f"{quote(slug, safe='-_.')}.html"
        if not path.is_file() or not path.stat().st_size:
            continue
        parser = _PactFateSummaryParser(entity_kind)
        parser.feed(path.read_text(encoding="utf-8", errors="replace"))
        title = entry.get("name_zh") or entry.get("name") or entry.get("id") or slug
        summary = parser.summary(str(title))
        if summary:
            result[str(slug)] = summary
    return result


def _overview_routes(repo: Path) -> set[str]:
    data = json.loads((repo / "sources/system_manifest.json").read_text(encoding="utf-8"))
    return {
        entity_route_key(item["index_url"])
        for item in data.get("systems", [])
        if item.get("index_url")
    }


def build_entity_index_v3(repo: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    v2 = json.loads((repo / "data/generated/entity-index-v2.json").read_text(encoding="utf-8"))
    search = json.loads((repo / "local_wiki/ss13/site/search-index.json").read_text(encoding="utf-8"))
    search_by_route = {
        entity_route_key(page.get("route") or page.get("source_url") or ""): page
        for page in search.get("pages", [])
        if page.get("route") or page.get("source_url")
    }
    manifest_titles = _manifest_titles(repo)
    i18n_titles = _i18n_titles(repo / "data/raw/i18n/ss13/files/i18n/cn.json")
    overview_routes = _overview_routes(repo)
    legendary_ids, legendary_entities = _legendary_entities(repo)
    vorax_entities = _vorax_entities(repo)
    talent_entities = _talent_entities(repo)
    ethereal_prism = _ethereal_prism_entity(repo)
    hero_entities = _hero_entities(repo)
    memory_system = _memory_system_entity(repo)
    pact_summaries = _pact_fate_summaries(repo, "pactspirit", "pact_spirit")
    fate_summaries = _pact_fate_summaries(repo, "destiny", "fate")
    title_sources = Counter()
    visibility = Counter()
    entities = []

    for old in v2.get("entities", []):
        route = entity_route_key(old["canonical_route"])
        if route in {"/cn/Hero/", "/cn/Talent/"}:
            continue
        page = search_by_route.get(route)
        page_heading = _raw_heading(repo, old, page)
        candidates: list[tuple[str, str | None]] = [
            ("page_chinese_title", page_heading),
            ("manifest_name_zh", next(iter(manifest_titles.get(route, [])), None)),
        ]
        slug = route.removeprefix("/cn/").removesuffix("/")
        if slug in legendary_ids and slug not in legendary_entities:
            continue
        candidates.append(("i18n_cn", i18n_titles.get(slug.casefold())))
        source_title = old.get("title") if CHINESE.search(str(old.get("title") or "")) else None
        candidates.append(("source_chinese_title", source_title))
        candidates.append(("fallback", clean_title(old.get("title") or slug)))
        title_source, title_zh = next(
            (source, value) for source, value in candidates if value
        )
        title_sources[title_source] += 1
        ordinary_equipment = slug in ORDINARY_EQUIPMENT_IDS
        entity_visibility = "hidden" if route in overview_routes else "visible"
        visibility[entity_visibility] += 1
        summary_source = (page or {}).get("summary_display") or (page or {}).get("plain_text") or ""
        summary = (_equipment_summary(repo, slug, str(title_zh)) if ordinary_equipment else
                   clean_summary(
                       summary_source,
                       route,
                       [str(old.get("title") or ""), str(title_zh), str((page or {}).get("title") or "")],
                   ))
        entity = {
            **old,
            "canonical_route": route,
            "entity_title_zh": title_zh,
            "entity_visibility": entity_visibility,
            "clean_summary": summary,
        }
        source_system_ids = {
            source.get("system_id") for source in old.get("sources", [])
        }
        if "destiny" in source_system_ids:
            entity.update({
                "entity_type": "fate",
                "content_category_id": "pact_spirit",
                "content_category_name_zh": "契灵系统",
                "content_subcategory_id": "pact_spirit_destiny",
                "content_subcategory_name_zh": "命运",
                "clean_summary": fate_summaries.get(slug, summary),
            })
        elif "pactspirit" in source_system_ids:
            entity.update({
                "entity_type": "pact_spirit",
                "content_category_id": "pact_spirit",
                "content_category_name_zh": "契灵系统",
                "content_subcategory_id": "pact_spirit_entity",
                "content_subcategory_name_zh": "契灵",
                "clean_summary": pact_summaries.get(slug, summary),
            })
        elif ordinary_equipment:
            entity.update({
                "content_category_id": "equipment",
                "content_category_name_zh": "装备",
                "content_subcategory_id": "equipment_craft",
                "content_subcategory_name_zh": "打造装备",
                "sources": [
                    {"source_type": "inventory", "role": "base_equipment"},
                    {"source_type": "craft", "role": "craft_affixes"},
                ],
                "entity_type": "equipment",
            })
        elif slug in legendary_entities:
            legendary = legendary_entities[slug]
            entity.update({
                "entity_title_zh": legendary["title"],
                "entity_visibility": "visible",
                "clean_summary": legendary["clean_summary"],
                "content_category_id": "equipment",
                "content_category_name_zh": "装备",
                "content_subcategory_id": "equipment_legendary",
                "content_subcategory_name_zh": "传奇装备",
                "sources": [
                    {"source_type": "legendary_gear", "role": "main_effect"},
                    {"source_type": "corrosion", "role": "corrosion"},
                ],
                "entity_type": "equipment",
            })
        elif slug in vorax_entities:
            vorax = vorax_entities[slug]
            entity.update({
                "entity_title_zh": vorax["title"],
                "entity_visibility": "visible",
                "clean_summary": vorax["clean_summary"],
                "content_category_id": "equipment",
                "content_category_name_zh": "装备",
                "content_subcategory_id": "equipment_vorax",
                "content_subcategory_name_zh": "渴瘾装备",
                "sources": [{"source_type": "vorax", "role": "equipment_data"}],
                "entity_type": "equipment",
            })
        elif slug in talent_entities:
            talent = talent_entities[slug]
            entity.update({
                "entity_title_zh": talent["title"],
                "entity_visibility": "visible",
                "clean_summary": talent["clean_summary"],
                "content_category_id": "talent_board",
                "content_category_name_zh": "天赋系统",
                "content_subcategory_id": talent["subcategory_id"],
                "content_subcategory_name_zh": talent["subcategory_name_zh"],
                "sources": [{"source_type": "talent", "role": "talent_effects"}],
                "entity_type": "talent",
                "talent_effect_count": talent["talent_effect_count"],
            })
        elif slug == "Ethereal_Prism" and ethereal_prism:
            entity.update({
                "entity_title_zh": ethereal_prism["title"],
                "entity_visibility": "visible",
                "clean_summary": ethereal_prism["clean_summary"],
                "content_category_id": "talent_board",
                "content_category_name_zh": "天赋系统",
                "content_subcategory_id": "talent_ethereal_prism",
                "content_subcategory_name_zh": "异度棱镜",
                "sources": [{
                    "source_type": "ethereal_prism",
                    "role": "system_data",
                }],
                "entity_type": "talent_system",
                "base_affix_count": ethereal_prism["base_affix_count"],
                "random_affix_count": ethereal_prism["random_affix_count"],
            })
        elif slug in hero_entities:
            hero = hero_entities[slug]
            entity.update({
                "title": hero["title"],
                "entity_title_zh": hero["title"],
                "entity_visibility": "visible",
                "clean_summary": hero["clean_summary"],
                "content_category_id": "hero",
                "content_category_name_zh": "英雄",
                "content_subcategory_id": "hero_trait",
                "content_subcategory_name_zh": "英雄特性",
                "sources": [{"source_type": "hero", "role": "hero_trait"}],
                "entity_type": "hero",
                "trait_node_count": hero["trait_node_count"],
                "trait_effect_count": hero["trait_effect_count"],
            })
        elif slug == "Hero_Memories" and memory_system:
            affixes = memory_system["affixes"]
            row_counts = memory_system["row_counts"]
            entity.update({
                "title": memory_system["title"],
                "entity_title_zh": memory_system["title"],
                "entity_visibility": "visible",
                "clean_summary": memory_system["clean_summary"],
                "content_category_id": "memory",
                "content_category_name_zh": "追忆",
                "content_subcategory_id": "hero_memory",
                "content_subcategory_name_zh": "英雄追忆",
                "sources": [
                    {"source_type": "hero_memory", "role": "base_memory_affixes"},
                    {"source_type": "revival", "role": "revival_affixes"},
                ],
                "entity_type": "memory_system",
                "base_attribute_count": row_counts["基础属性"],
                "fixed_affix_count": row_counts["固有词缀"],
                "random_affix_count": row_counts["随机词缀"],
                "revival_affix_count": row_counts["复苏词缀"],
                "moon_affix_count": row_counts["复苏词缀（月相）"],
            })
        entities.append(entity)

    existing_routes = {entity["canonical_route"] for entity in entities}
    for entity in _equipment_related_system_entities(repo):
        if entity["canonical_route"] not in existing_routes:
            entities.append(entity)
            visibility["visible"] += 1
            title_sources["system_entity_title"] += 1

    existing_routes = {entity["canonical_route"] for entity in entities}
    for slug, hero in hero_entities.items():
        route = f"/cn/{quote(slug, safe='-_.')}/"
        if route in existing_routes:
            continue
        entities.append({
            "entity_id": f"tlidb:cn:{slug}",
            "title": hero["title"],
            "canonical_route": route,
            "entity_title_zh": hero["title"],
            "entity_visibility": "visible",
            "entity_type": "hero",
            "clean_summary": hero["clean_summary"],
            "content_category_id": "hero",
            "content_category_name_zh": "英雄",
            "content_subcategory_id": "hero_trait",
            "content_subcategory_name_zh": "英雄特性",
            "sources": [{"source_type": "hero", "role": "hero_trait"}],
            "confidence": "primary",
            "trait_node_count": hero["trait_node_count"],
            "trait_effect_count": hero["trait_effect_count"],
        })
        existing_routes.add(route)
        visibility["visible"] += 1
        title_sources["hero_manifest_name_zh"] += 1

    entities.sort(key=lambda item: item["canonical_route"])
    index = {"schema_version": 3, "entities": entities}
    report = {
        "schema_version": 1,
        "total_entities": len(entities),
        "visible_entities": visibility["visible"],
        "hidden_entities": visibility["hidden"],
        "title_source_distribution": dict(sorted(title_sources.items())),
        "empty_clean_summary_count": sum(not item["clean_summary"] for item in entities),
        "warnings": [],
        "errors": [],
    }
    return index, report


def equipment_entity_v2_report(index: dict[str, Any]) -> dict[str, Any]:
    equipment = [
        entity for entity in index.get("entities", [])
        if entity["canonical_route"].removeprefix("/cn/").removesuffix("/")
        in ORDINARY_EQUIPMENT_IDS
    ]
    by_id = {entity["entity_id"]: entity for entity in equipment}
    examples = []
    for slug in ("STR_Helmet", "Belt", "Spirit_Ring", "Crossbow", "Ring"):
        entity = by_id.get(f"tlidb:cn:{slug}")
        if entity:
            examples.append({
                "entity_id": entity["entity_id"],
                "entity_title_zh": entity["entity_title_zh"],
                "entity_type": entity["entity_type"],
                "category": entity["content_category_name_zh"],
                "subcategory": entity["content_subcategory_name_zh"],
                "sources": entity["sources"],
                "has_base_affixes": "基础词缀" in entity["clean_summary"],
                "has_craft_affixes": "打造词缀" in entity["clean_summary"],
            })
    return {
        "schema_version": 2,
        "total_entities": len(equipment),
        "updated": 37,
        "added": 1,
        "craft_enriched": sum("打造词缀" in entity["clean_summary"] for entity in equipment),
        "hidden_pages": ["Inventory", "Craft"],
        "examples": examples,
        "warnings": ([] if len(equipment) == len(ORDINARY_EQUIPMENT_IDS) else
                     [f"Expected {len(ORDINARY_EQUIPMENT_IDS)} equipment entities, got {len(equipment)}."]),
        "errors": [],
    }


def equipment_craft_enrichment_filter_v2_report(
    repo: Path, index: dict[str, Any]
) -> dict[str, Any]:
    craft = json.loads((repo / "sources/craft_manifest.json").read_text(encoding="utf-8"))
    legendary = json.loads(
        (repo / "sources/legendary_gear_manifest.json").read_text(encoding="utf-8")
    )
    legendary_ids = {entry["id"] for entry in legendary.get("entries", [])}
    equipment = [
        entity for entity in index.get("entities", [])
        if entity["canonical_route"].removeprefix("/cn/").removesuffix("/")
        in ORDINARY_EQUIPMENT_IDS
    ]
    accepted = [{
        "entity_id": entity["entity_id"],
        "title": entity["entity_title_zh"],
        "binding": "inventory canonical entity -> same-page craft tab",
        "craft_role": "craft_affixes",
    } for entity in equipment]
    rejected = [{
        "id": entry["id"],
        "title": entry.get("name_zh") or entry["id"],
        "reason": "no_matching_inventory_equipment_entity",
    } for entry in craft.get("entries", [])
        if entry["id"] not in legendary_ids and entry["id"] not in ORDINARY_EQUIPMENT_IDS]
    accepted_by_id = {item["entity_id"]: item for item in accepted}
    rejected_by_id = {item["id"]: item for item in rejected}
    return {
        "schema_version": 2,
        "total_equipment_entities": len(equipment),
        "accepted_craft_sources": accepted,
        "rejected_craft_sources": rejected,
        "examples": {
            "accepted": [accepted_by_id[f"tlidb:cn:{slug}"]
                         for slug in ("STR_Helmet", "Belt", "Crossbow")],
            "rejected": [rejected_by_id[slug] for slug in (
                "Memory_of_Origin", "Memory_of_Progress", "Memory_of_Discipline"
            )],
        },
        "summary": {
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "equipment_summaries_with_rejected_memory_text": sum(
                any(memory in entity.get("clean_summary", "") for memory in (
                    "本源的追忆", "奋进的追忆", "守己的追忆"
                )) for entity in equipment
            ),
        },
        "warnings": [],
        "errors": [],
    }


def legendary_gear_entity_v1_report(repo: Path, index: dict[str, Any]) -> dict[str, Any]:
    legendary_ids, extracted = _legendary_entities(repo)
    entities = [
        entity for entity in index.get("entities", [])
        if entity["canonical_route"].removeprefix("/cn/").removesuffix("/") in extracted
    ]
    by_slug = {
        entity["canonical_route"].removeprefix("/cn/").removesuffix("/"): entity
        for entity in entities
    }
    examples = [by_slug[slug] for slug in (
        "Thunder_Channeling_Prosthetics", "Crosser", "Frozen_Sight",
        "Glorious_Journey", "Omniscient_Prototype", "Awaiting",
    )]
    return {
        "schema_version": 1,
        "total_entities": len(entities),
        "created": len(entities),
        "excluded_non_equipment": 7,
        "skipped_empty": len(legendary_ids) - len(extracted) - 7,
        "corrosion_enriched": sum(extracted[slug]["has_corrosion"] for slug in extracted),
        "examples": [{
            "entity_id": entity["entity_id"],
            "entity_title_zh": entity["entity_title_zh"],
            "category": entity["content_category_name_zh"],
            "subcategory": entity["content_subcategory_name_zh"],
            "sources": entity["sources"],
        } for entity in examples],
        "warnings": [],
        "errors": [],
    }


def vorax_equipment_entity_v1_report(repo: Path, index: dict[str, Any]) -> dict[str, Any]:
    extracted = _vorax_entities(repo)
    by_id = {entity["entity_id"]: entity for entity in index.get("entities", [])}
    entities = [by_id[f"tlidb:cn:{slug}"] for slug in VORAX_ENTITY_IDS]
    examples = [by_id[f"tlidb:cn:{slug}"] for slug in (
        "Vorax_Limb:_Head", "Vorax_Limb:_Legs", "Vorax_Aberrant_Limb:_Digits"
    )]
    return {
        "schema_version": 1,
        "total_entities": len(entities),
        "created": 0,
        "updated": len(entities),
        "examples": [{
            "entity_id": entity["entity_id"],
            "entity_title_zh": entity["entity_title_zh"],
            "category": entity["content_category_name_zh"],
            "subcategory": entity["content_subcategory_name_zh"],
            "sources": entity["sources"],
            "has_base_affixes": bool(extracted[
                entity["canonical_route"].removeprefix("/cn/").removesuffix("/")
            ]["base_affixes"]),
            "has_craft_affixes": bool(extracted[
                entity["canonical_route"].removeprefix("/cn/").removesuffix("/")
            ]["craft_affixes"]),
            "has_legendary_quality": bool(extracted[
                entity["canonical_route"].removeprefix("/cn/").removesuffix("/")
            ]["legendary_quality"]),
        } for entity in examples],
        "excluded_pages": ["Inventory", "Vorax_Season", "Vorax_Exchange_Material"],
        "warnings": ([] if len(extracted) == len(VORAX_ENTITY_IDS)
                     else [f"Expected {len(VORAX_ENTITY_IDS)} Vorax entities, got {len(extracted)}."]),
        "errors": [],
    }


def equipment_related_system_entity_v1_report(index: dict[str, Any]) -> dict[str, Any]:
    by_route = {entity["canonical_route"]: entity for entity in index["entities"]}

    def section(route: str) -> dict[str, Any]:
        entity = by_route.get(route)
        return {
            "entity_created": entity is not None,
            "entries": entity.get("record_count", 0) if entity else 0,
            "entity_id": entity.get("entity_id") if entity else None,
            "entity_type": entity.get("entity_type") if entity else None,
            "category": entity.get("content_category_name_zh") if entity else None,
            "subcategory": entity.get("content_subcategory_name_zh") if entity else None,
            "clean_summary_length": len(entity.get("clean_summary", "")) if entity else 0,
        }

    return {
        "schema_version": 1,
        "fragrance": section("/cn/Blending_Rituals/"),
        "tower_sequence": section("/cn/TOWER_Sequence/"),
        "equipment_entities_created": 0,
        "warnings": [],
        "errors": [],
    }


def talent_system_entity_v1_report(index: dict[str, Any]) -> dict[str, Any]:
    entities = [
        entity for entity in index.get("entities", [])
        if entity.get("entity_type") == "talent"
    ]
    by_subcategory = Counter(
        entity.get("content_subcategory_id") for entity in entities
    )
    by_id = {entity["entity_id"]: entity for entity in entities}
    examples = []
    for slug in ("God_of_Might", "God_of_War", "New_God", "Nether_King"):
        entity = by_id.get(f"tlidb:cn:{slug}")
        if entity:
            examples.append({
                "entity_id": entity["entity_id"],
                "title": entity["entity_title_zh"],
                "category": entity["content_category_name_zh"],
                "subcategory": entity["content_subcategory_name_zh"],
                "canonical_route": entity["canonical_route"],
                "talent_effect_count": entity["talent_effect_count"],
                "clean_summary_length": len(entity["clean_summary"]),
            })
    return {
        "schema_version": 1,
        "total_entities": len(entities),
        "hero_talent_count": by_subcategory["talent_hero"],
        "new_god_count": by_subcategory["talent_new_god"],
        "nether_king_count": by_subcategory["talent_nether_king_entity"],
        "excluded_pages": ["/cn/Talent/"],
        "examples": examples,
        "warnings": [],
        "errors": [],
    }


def hero_entity_v1_report(index: dict[str, Any]) -> dict[str, Any]:
    entities = [
        entity for entity in index.get("entities", [])
        if entity.get("entity_type") == "hero"
    ]
    by_id = {entity["entity_id"]: entity for entity in entities}
    examples = []
    for slug in ("Anger", "Ranger_of_Glory", "Licorice_Note"):
        entity = by_id.get(f"tlidb:cn:{slug}")
        if entity:
            examples.append({
                "entity_id": entity["entity_id"],
                "title": entity["entity_title_zh"],
                "canonical_route": entity["canonical_route"],
                "source": entity["sources"],
                "clean_summary_length": len(entity["clean_summary"]),
                "trait_node_count": entity["trait_node_count"],
                "trait_effect_count": entity["trait_effect_count"],
            })
    return {
        "schema_version": 1,
        "total_entities": len(entities),
        "category": "英雄",
        "subcategory": "英雄特性",
        "excluded_pages": ["/cn/Hero/"],
        "examples": examples,
        "warnings": ([] if len(entities) == 27 else
                     [f"Expected 27 hero entities, got {len(entities)}."]),
        "errors": [],
    }


def memory_system_entity_v1_report(index: dict[str, Any]) -> dict[str, Any]:
    entity = next((
        item for item in index.get("entities", [])
        if item.get("canonical_route") == "/cn/Hero_Memories/"
        and item.get("entity_type") == "memory_system"
    ), None)
    excluded_noise = [
        "Item 列表",
        "材料与操作说明",
        "UI 图片资源",
        "modifier ID",
        "Tier/Level/Weight",
        "导航与页脚",
        "脚本与样式",
    ]
    return {
        "schema_version": 1,
        "entity_created": entity is not None,
        "entity_id": entity.get("entity_id") if entity else None,
        "category": entity.get("content_category_name_zh") if entity else None,
        "subcategory": entity.get("content_subcategory_name_zh") if entity else None,
        "base_attribute_count": entity.get("base_attribute_count", 0) if entity else 0,
        "fixed_affix_count": entity.get("fixed_affix_count", 0) if entity else 0,
        "random_affix_count": entity.get("random_affix_count", 0) if entity else 0,
        "revival_affix_count": entity.get("revival_affix_count", 0) if entity else 0,
        "moon_affix_count": entity.get("moon_affix_count", 0) if entity else 0,
        "excluded_noise": excluded_noise,
        "warnings": [],
        "errors": [] if entity else ["Hero Memories system entity was not created."],
    }


def ethereal_prism_entity_v1_report(repo: Path, index: dict[str, Any]) -> dict[str, Any]:
    extracted = _ethereal_prism_entity(repo)
    entity = next((
        item for item in index.get("entities", [])
        if item.get("canonical_route") == "/cn/Ethereal_Prism/"
        and item.get("entity_type") == "talent_system"
    ), None)
    return {
        "schema_version": 1,
        "entity_created": entity is not None,
        "category": ({
            "id": entity["content_category_id"],
            "name_zh": entity["content_category_name_zh"],
            "subcategory_id": entity["content_subcategory_id"],
            "subcategory_name_zh": entity["content_subcategory_name_zh"],
        } if entity else None),
        "base_affix_count": extracted["base_affix_count"] if extracted else 0,
        "random_affix_count": extracted["random_affix_count"] if extracted else 0,
        "excluded_item_pages": extracted["excluded_item_pages"] if extracted else 0,
        "examples": ({
            "base_affixes": extracted["base_affixes"][:3],
            "random_affixes": extracted["random_affixes"][:3],
        } if extracted else {}),
        "warnings": [],
        "errors": ([] if entity and extracted else [
            "Ethereal Prism entity or affix source data is unavailable."
        ]),
    }


def pact_fate_search_cleanup_v1_report(index: dict[str, Any]) -> dict[str, Any]:
    pact = [item for item in index.get("entities", []) if item.get("entity_type") == "pact_spirit"]
    fate = [item for item in index.get("entities", []) if item.get("entity_type") == "fate"]
    examples = []
    for entity_id in (
        "tlidb:cn:Red_Umbrella",
        "tlidb:cn:Micro_Fate:_Fire_Resistance",
        "tlidb:cn:Undetermined_Fate",
    ):
        entity = next((item for item in pact + fate if item.get("entity_id") == entity_id), None)
        if entity:
            examples.append({
                "entity_id": entity_id,
                "entity_type": entity["entity_type"],
                "clean_summary_sample": entity["clean_summary"][:240],
            })
    return {
        "schema_version": 1,
        "pact_entity_count": len(pact),
        "fate_entity_count": len(fate),
        "removed_noise_examples": {
            "pact": ["lv/name table header", "cookie UI", "script/style content"],
            "fate": ["Info id", "Show Description", "previous season cards", "cookie UI"],
        },
        "validation_examples": examples,
        "warnings": [],
        "errors": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("data/generated/entity-index-v3.json"))
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/reports/local-wiki/entity-index-v3-generation-report.json"),
    )
    parser.add_argument(
        "--equipment-report",
        type=Path,
        default=Path("data/reports/local-wiki/equipment-entity-v2-report.json"),
    )
    parser.add_argument(
        "--equipment-craft-filter-report",
        type=Path,
        default=Path("data/reports/local-wiki/equipment-craft-enrichment-filter-v2.json"),
    )
    parser.add_argument(
        "--legendary-gear-report",
        type=Path,
        default=Path("data/reports/local-wiki/legendary-gear-entity-v1-report.json"),
    )
    parser.add_argument(
        "--vorax-equipment-report",
        type=Path,
        default=Path("data/reports/local-wiki/vorax-equipment-entity-v1-report.json"),
    )
    parser.add_argument(
        "--equipment-related-system-report",
        type=Path,
        default=Path(
            "data/reports/local-wiki/equipment-related-system-entity-v1-report.json"
        ),
    )
    parser.add_argument(
        "--talent-system-report",
        type=Path,
        default=Path("data/reports/local-wiki/talent-system-entity-v1-report.json"),
    )
    parser.add_argument(
        "--ethereal-prism-report",
        type=Path,
        default=Path("data/reports/local-wiki/ethereal-prism-entity-v1-report.json"),
    )
    parser.add_argument(
        "--hero-report",
        type=Path,
        default=Path("data/reports/local-wiki/hero-entity-v1-report.json"),
    )
    parser.add_argument(
        "--memory-system-report",
        type=Path,
        default=Path("data/reports/local-wiki/memory-system-entity-v1-report.json"),
    )
    parser.add_argument(
        "--pact-fate-search-report",
        type=Path,
        default=Path("data/reports/local-wiki/pact-fate-search-cleanup-v1.json"),
    )
    args = parser.parse_args()
    repo = args.repo.resolve()
    index, report = build_entity_index_v3(repo)
    output = args.output if args.output.is_absolute() else repo / args.output
    report_path = args.report if args.report.is_absolute() else repo / args.report
    equipment_report_path = (args.equipment_report if args.equipment_report.is_absolute()
                             else repo / args.equipment_report)
    craft_filter_report_path = (
        args.equipment_craft_filter_report
        if args.equipment_craft_filter_report.is_absolute()
        else repo / args.equipment_craft_filter_report
    )
    legendary_report_path = (
        args.legendary_gear_report if args.legendary_gear_report.is_absolute()
        else repo / args.legendary_gear_report
    )
    vorax_report_path = (
        args.vorax_equipment_report if args.vorax_equipment_report.is_absolute()
        else repo / args.vorax_equipment_report
    )
    equipment_related_report_path = (
        args.equipment_related_system_report
        if args.equipment_related_system_report.is_absolute()
        else repo / args.equipment_related_system_report
    )
    talent_report_path = (
        args.talent_system_report
        if args.talent_system_report.is_absolute()
        else repo / args.talent_system_report
    )
    ethereal_prism_report_path = (
        args.ethereal_prism_report
        if args.ethereal_prism_report.is_absolute()
        else repo / args.ethereal_prism_report
    )
    hero_report_path = (
        args.hero_report if args.hero_report.is_absolute()
        else repo / args.hero_report
    )
    memory_system_report_path = (
        args.memory_system_report if args.memory_system_report.is_absolute()
        else repo / args.memory_system_report
    )
    pact_fate_report_path = (
        args.pact_fate_search_report if args.pact_fate_search_report.is_absolute()
        else repo / args.pact_fate_search_report
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    equipment_report_path.parent.mkdir(parents=True, exist_ok=True)
    craft_filter_report_path.parent.mkdir(parents=True, exist_ok=True)
    legendary_report_path.parent.mkdir(parents=True, exist_ok=True)
    vorax_report_path.parent.mkdir(parents=True, exist_ok=True)
    equipment_related_report_path.parent.mkdir(parents=True, exist_ok=True)
    talent_report_path.parent.mkdir(parents=True, exist_ok=True)
    ethereal_prism_report_path.parent.mkdir(parents=True, exist_ok=True)
    hero_report_path.parent.mkdir(parents=True, exist_ok=True)
    memory_system_report_path.parent.mkdir(parents=True, exist_ok=True)
    pact_fate_report_path.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    equipment_report_path.write_text(
        json.dumps(equipment_entity_v2_report(index), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    craft_filter_report_path.write_text(
        json.dumps(
            equipment_craft_enrichment_filter_v2_report(repo, index),
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    legendary_report_path.write_text(
        json.dumps(legendary_gear_entity_v1_report(repo, index), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    vorax_report_path.write_text(
        json.dumps(vorax_equipment_entity_v1_report(repo, index), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    equipment_related_report_path.write_text(
        json.dumps(
            equipment_related_system_entity_v1_report(index),
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    talent_report_path.write_text(
        json.dumps(
            talent_system_entity_v1_report(index), ensure_ascii=False, indent=2
        ) + "\n",
        encoding="utf-8",
    )
    ethereal_prism_report_path.write_text(
        json.dumps(
            ethereal_prism_entity_v1_report(repo, index),
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    hero_report_path.write_text(
        json.dumps(hero_entity_v1_report(index), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    memory_system_report_path.write_text(
        json.dumps(
            memory_system_entity_v1_report(index), ensure_ascii=False, indent=2
        ) + "\n",
        encoding="utf-8",
    )
    pact_fate_report_path.write_text(
        json.dumps(
            pact_fate_search_cleanup_v1_report(index), ensure_ascii=False, indent=2
        ) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
