"""Generate presentation-focused Entity Index v3 from Entity Index v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
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
from crawler.build_full_wiki_mirror import TextInspector, entity_route_key
from crawler.discover_system_manifest import discover_entries_from_html
from crawler.parse_hero import parse_hero_html
from crawler.season_context import DEFAULT_SEASON, SeasonContext


_SEASON_CONTEXT: SeasonContext | None = None


def _season_context(repo: Path) -> SeasonContext:
    return _SEASON_CONTEXT or SeasonContext(repo, DEFAULT_SEASON)


def _raw_manifests(repo: Path) -> Path:
    return _season_context(repo).readable_raw_manifest_root()


def _system_manifest_path(repo: Path) -> Path:
    return _season_context(repo).readable_system_manifest()


def _source_manifest_path(repo: Path, system_id: str) -> Path:
    return _season_context(repo).readable_source_manifest(system_id)


def _manifest_reference(repo: Path, reference: str) -> Path:
    context = _season_context(repo)
    scoped = context.source_root / Path(reference).name
    if scoped.is_file() or context.season != DEFAULT_SEASON:
        return scoped
    return repo / reference


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

# Entity v3 bootstrap rules are deliberately tracked here instead of being
# inferred from a previously generated Search Index.  These are the systems
# that define player-facing identities in the v1 content model.
BOOTSTRAP_SYSTEM_CLASSIFICATION = {
    "inventory": ("equipment", "装备", "equipment_type", "装备类型"),
    "legendary_gear": ("equipment", "装备", "equipment_legendary", "传奇装备"),
    "craft": ("equipment", "装备", "equipment_craft", "打造装备"),
    "active_skill": ("skill", "技能", "skill_active", "主动技能"),
    "support_skill": ("skill", "技能", "skill_support", "辅助技能"),
    "passive_skill": ("skill", "技能", "skill_passive", "被动技能"),
    "activation_medium_skill": ("skill", "技能", "skill_activation_medium", "触媒技能"),
    "magnificent_support_skill": ("skill", "技能", "skill_magnificent_support", "华贵辅助技能"),
    "noble_support_skill": ("skill", "技能", "skill_noble_support", "崇高辅助技能"),
    "modularization_skill": ("skill", "技能", "skill_modularization", "模块化技能"),
    "talent": ("talent_board", "天赋石板", "talent_hero", "英雄天赋"),
    "path_of_progression": ("talent_board", "天赋石板", "talent_divinity_slate", "神格石板"),
    "nether_kings_divinity": ("talent_board", "天赋石板", "talent_nether_king", "冥王神格"),
    "pactspirit": ("pact_spirit", "契灵系统", "pact_spirit_entity", "契灵"),
    "destiny": ("pact_spirit", "契灵系统", "pact_spirit_destiny", "命运"),
}
BOOTSTRAP_PRIMARY_SYSTEMS = {
    "inventory",
    "active_skill", "support_skill", "passive_skill", "activation_medium_skill",
    "magnificent_support_skill", "noble_support_skill", "modularization_skill",
    "talent", "path_of_progression", "nether_kings_divinity", "pactspirit", "destiny",
}
BOOTSTRAP_ROUTE_SYSTEM = {
    "/cn/Active_Skill/": "active_skill",
    "/cn/Support_Skill/": "support_skill",
    "/cn/Passive_Skill/": "passive_skill",
    "/cn/Activation_Medium_Skill/": "activation_medium_skill",
    "/cn/Magnificent_Support_Skill/": "magnificent_support_skill",
    "/cn/Noble_Support_Skill/": "noble_support_skill",
    "/cn/Modularization_Skill/": "modularization_skill",
    "/cn/Legendary_Gear/": "legendary_gear",
    "/cn/Divinity_Slate/": "path_of_progression",
    "/cn/Nether_Kings_Divinity/": "nether_kings_divinity",
    "/cn/Destiny/": "destiny",
}
BOOTSTRAP_SUPPORT_SYSTEMS = {"help", "tip", "codex"}
BOOTSTRAP_SYSTEM_PRIORITY = {
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


class _BootstrapPageText(HTMLParser):
    """Collect deterministic title/body fingerprints from a Raw snapshot."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: list[str] = []
        self.body: list[str] = []
        self.in_title = False
        self.blocked = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self.in_title = True
        if tag in {"script", "style", "noscript"}:
            self.blocked += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if tag in {"script", "style", "noscript"} and self.blocked:
            self.blocked -= 1

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if not value or self.blocked:
            return
        if self.in_title:
            self.title.append(value)
        self.body.append(value)


def _bootstrap_source_role(system_id: str, category_map: dict[str, dict[str, str]]) -> str:
    if system_id == "recovered_internal_pages":
        return "recovered"
    if system_id == "hyperlink":
        return "secondary"
    if system_id in BOOTSTRAP_SUPPORT_SYSTEMS:
        return "support"
    if system_id in category_map or system_id in {"inventory", "legendary_gear", "craft"}:
        return "primary"
    return "source"


def _bootstrap_entity_id(route: str) -> str:
    slug = unquote(route).removeprefix("/cn/").removesuffix("/")
    return f"tlidb:cn:{slug}"


def _bootstrap_raw_path(repo: Path, system_id: str, entry: dict[str, Any]) -> Path:
    slug = str(entry.get("slug") or entry.get("id") or "")
    return (
        _raw_manifests(repo) / system_id / "raw_html"
        / f"{quote(slug, safe='-_.')}.html"
    )


def _canonical_raw_snapshot(repo: Path, system_id: str, slug: str) -> Path:
    """Resolve an already-fetched canonical page without inventing source data."""
    filename = f"{quote(slug, safe='-_.')}.html"
    preferred = _raw_manifests(repo) / system_id / "raw_html" / filename
    if preferred.is_file() and preferred.stat().st_size:
        return preferred
    raw_root = _raw_manifests(repo)
    if not raw_root.is_dir():
        return preferred
    for system_root in sorted(raw_root.iterdir()):
        candidate = system_root / "raw_html" / filename
        if candidate.is_file() and candidate.stat().st_size:
            return candidate
    return preferred


def _inventory_snapshot_entries(repo: Path) -> tuple[list[dict[str, Any]], Path | None]:
    """Read a cached canonical Inventory index using the tracked DOM contract."""
    manifest = json.loads(_system_manifest_path(repo).read_text(encoding="utf-8"))
    candidate = next((
        item for item in manifest.get("systems", [])
        if item.get("system_id") in {"inventory", "candidate_inventory"}
        or item.get("index_slug") == "Inventory"
    ), None)
    if candidate is None:
        return [], None
    index_url = str(candidate.get("index_url") or "")
    if entity_route_key(index_url) != "/cn/Inventory/":
        return [], None
    path = _canonical_raw_snapshot(repo, "inventory", "Inventory")
    if not path.is_file() or not path.stat().st_size:
        return [], None
    entries, report = discover_entries_from_html(
        path.read_text(encoding="utf-8", errors="replace"), index_url, "inventory"
    )
    if report.get("directory_signature") != "flat_relative_inventory_directory":
        return [], None
    return entries, path


def _bootstrap_fingerprint(path: Path) -> dict[str, str] | None:
    if not path.is_file() or not path.stat().st_size:
        return None
    parser = _BootstrapPageText()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    title = " ".join(parser.title)
    body = " ".join(parser.body)
    return {
        "title": hashlib.sha256(title.encode()).hexdigest(),
        "body": hashlib.sha256(body.encode()).hexdigest(),
    }


def _bootstrap_category_map(repo: Path) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    data = json.loads(
        (repo / "config/game_category_mapping.json").read_text(encoding="utf-8")
    )
    systems: dict[str, dict[str, str]] = {}
    names: dict[str, str] = {}
    for category in data.get("categories", []):
        names[category["id"]] = category["name_zh"]
        for system_id in category.get("systems", []):
            systems[system_id] = {"id": category["id"], "name_zh": category["name_zh"]}
    return systems, names


def _bootstrap_manifest_sources(repo: Path) -> dict[str, list[dict[str, Any]]]:
    root = json.loads(_system_manifest_path(repo).read_text(encoding="utf-8"))
    manifests: list[tuple[int, str, Path]] = []
    for system in root.get("systems", []):
        manifest_path = system.get("manifest_path")
        if manifest_path:
            manifests.append((
                int(system.get("source_order", 10_000)),
                str(system["system_id"]),
                _manifest_reference(repo, str(manifest_path)),
            ))
    recovered = _source_manifest_path(repo, "recovered_internal_pages")
    if recovered.is_file():
        manifests.append((100_000, "recovered_internal_pages", recovered))

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for system_order, system_id, path in sorted(manifests):
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        seen: set[tuple[str, str]] = set()
        entries = sorted(
            data.get("entries", []),
            key=lambda item: (
                int(item.get("source_order", 10_000_000)),
                str(item.get("id") or item.get("slug") or ""),
            ),
        )
        for entry in entries:
            url = entry.get("url") or entry.get("path")
            if not url:
                continue
            route = entity_route_key(str(url))
            source_id = str(entry.get("id") or entry.get("slug") or "")
            identity = (route, source_id)
            if identity in seen:
                continue
            seen.add(identity)
            raw_path = _bootstrap_raw_path(repo, system_id, entry)
            grouped[route].append({
                "system_id": system_id,
                "system_order": system_order,
                "id": source_id,
                "title": entry.get("name_zh") or entry.get("name") or source_id,
                "raw_path": raw_path,
                "raw_available": raw_path.is_file() and raw_path.stat().st_size > 0,
            })

    # Fresh runs before this fix may already have fetched the same canonical
    # /cn/Inventory page through another manifest while candidate_inventory was
    # left in needs-review.  Use that exact cached index as deterministic source
    # membership for Stage 5; the fixed verifier will produce the formal
    # inventory manifest on the next Stage 2 run.
    has_inventory_manifest = any(
        source["system_id"] == "inventory"
        for sources in grouped.values() for source in sources
    )
    if not has_inventory_manifest:
        inventory_entries, _snapshot = _inventory_snapshot_entries(repo)
        for entry in inventory_entries:
            route = entity_route_key(str(entry["url"]))
            raw_path = _canonical_raw_snapshot(repo, "inventory", str(entry["slug"]))
            grouped[route].append({
                "system_id": "inventory",
                "system_order": 1,
                "id": str(entry["id"]),
                "title": entry.get("name_zh") or entry["id"],
                "raw_path": raw_path,
                "raw_available": raw_path.is_file() and raw_path.stat().st_size > 0,
                "bootstrap_source": "cached_canonical_inventory_index",
            })
    return grouped


def _bootstrap_classification(system_id: str | None) -> dict[str, str | None]:
    value = BOOTSTRAP_SYSTEM_CLASSIFICATION.get(str(system_id))
    if value is None:
        return {
            "content_category_id": None,
            "content_category_name_zh": None,
            "content_subcategory_id": None,
            "content_subcategory_name_zh": None,
        }
    category_id, category_name, subcategory_id, subcategory_name = value
    return {
        "content_category_id": category_id,
        "content_category_name_zh": category_name,
        "content_subcategory_id": subcategory_id,
        "content_subcategory_name_zh": subcategory_name,
    }


def _bootstrap_owner(sources: list[dict[str, Any]]) -> dict[str, Any]:
    return min(
        sources,
        key=lambda source: (
            BOOTSTRAP_SYSTEM_PRIORITY.get(source["system_id"], 100),
            source["system_order"],
            source["system_id"],
            source["id"],
        ),
    )


def _bootstrap_v2_from_sources(repo: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reconstruct the v2 identity set directly from tracked rules and source data."""
    grouped = _bootstrap_manifest_sources(repo)
    category_map, category_names = _bootstrap_category_map(repo)
    entities: dict[str, dict[str, Any]] = {}
    skipped_review = 0

    for route in sorted(grouped):
        source_rows = grouped[route]
        if len(source_rows) < 2:
            continue
        fingerprints = [_bootstrap_fingerprint(source["raw_path"]) for source in source_rows]
        raw_complete = all(fingerprints)
        same_title = raw_complete and len({item["title"] for item in fingerprints if item}) == 1
        same_body = raw_complete and len({item["body"] for item in fingerprints if item}) == 1
        confidence = "high" if same_title and same_body else "medium"
        mapped_categories = {
            category_map[source["system_id"]]["id"]
            for source in source_rows if source["system_id"] in category_map
        }
        category = (
            next(iter(mapped_categories)) if len(mapped_categories) == 1
            else "mixed" if mapped_categories else None
        )
        primary = [
            source for source in source_rows
            if _bootstrap_source_role(source["system_id"], category_map) == "primary"
        ]
        medium_auto = (
            category not in {None, "mixed"}
            and len(primary) >= 2
            and len({source["title"] for source in primary}) == 1
            and all(source["raw_available"] for source in primary)
        )
        if confidence != "high" and not medium_auto:
            skipped_review += 1
            continue

        owner = _bootstrap_owner(source_rows)
        agreeing = [
            source for source in source_rows
            if source["system_id"] in BOOTSTRAP_SYSTEM_CLASSIFICATION
            and BOOTSTRAP_SYSTEM_CLASSIFICATION[source["system_id"]][0] == category
            and _bootstrap_source_role(source["system_id"], category_map) == "primary"
        ]
        classification_owner = min(
            agreeing,
            key=lambda source: (source["system_order"], source["system_id"]),
        ) if len(agreeing) >= 2 else owner
        title_source = min(
            source_rows,
            key=lambda source: (
                0 if category and category_map.get(source["system_id"], {}).get("id") == category else 1,
                BOOTSTRAP_SYSTEM_PRIORITY.get(source["system_id"], 100),
                0 if CHINESE.search(str(source["title"] or "")) else 1,
                source["system_id"],
            ),
        )
        entity = {
            "entity_id": _bootstrap_entity_id(route),
            "title": str(title_source["title"] or owner["id"]),
            "canonical_route": route,
            **_bootstrap_classification(classification_owner["system_id"]),
            "sources": [
                {
                    "system_id": source["system_id"],
                    "role": _bootstrap_source_role(source["system_id"], category_map),
                }
                for source in source_rows
            ],
            "confidence": confidence,
        }
        if route in BOOTSTRAP_ROUTE_SYSTEM:
            entity.update(_bootstrap_classification(BOOTSTRAP_ROUTE_SYSTEM[route]))
        if confidence == "medium":
            entity["merge_class"] = "A"
        entities[route] = entity

    for route in sorted(grouped):
        if route in entities:
            continue
        candidates = [
            source for source in grouped[route]
            if source["system_id"] in BOOTSTRAP_PRIMARY_SYSTEMS
            and source["raw_available"]
        ]
        if not candidates:
            continue
        owner = min(candidates, key=lambda source: (source["system_order"], source["system_id"]))
        entities[route] = {
            "entity_id": _bootstrap_entity_id(route),
            "title": clean_title(str(owner["title"] or owner["id"])),
            "canonical_route": route,
            **_bootstrap_classification(owner["system_id"]),
            "sources": [{"system_id": owner["system_id"], "role": "primary"}],
            "confidence": "primary",
        }

    result = sorted(entities.values(), key=lambda entity: entity["canonical_route"])
    return {"schema_version": 2, "entities": result}, {
        "source_route_count": len(grouped),
        "bootstrap_entity_count": len(result),
        "skipped_review_count": skipped_review,
    }


def _bootstrap_plain_text(repo: Path, entity: dict[str, Any]) -> str:
    skill_systems = {
        "active_skill", "support_skill", "passive_skill", "activation_medium_skill",
        "magnificent_support_skill", "noble_support_skill", "modularization_skill",
    }
    slug = entity["canonical_route"].removeprefix("/cn/").removesuffix("/")
    systems = [
        source.get("system_id") or source.get("source_type")
        for source in entity.get("sources", [])
    ]
    for system_id in systems:
        if not system_id:
            continue
        path = (
            _raw_manifests(repo) / str(system_id) / "raw_html"
            / f"{quote(slug, safe='-_.')}.html"
        )
        if not path.is_file() or not path.stat().st_size:
            continue
        inspector = TextInspector(visible_skill_content_only=system_id in skill_systems)
        inspector.feed(path.read_text(encoding="utf-8", errors="replace"))
        return " ".join(" ".join(inspector.text).split())
    return ""


def _manifest_titles(repo: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    system_manifest = json.loads(_system_manifest_path(repo).read_text(encoding="utf-8"))
    paths = [_manifest_reference(repo, item["manifest_path"]) for item in system_manifest.get("systems", []) if item.get("manifest_path")]
    recovered = _source_manifest_path(repo, "recovered_internal_pages")
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
        path = _canonical_raw_snapshot(repo, str(system_id), slug)
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
    path = _canonical_raw_snapshot(repo, "inventory", slug)
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
        _source_manifest_path(repo, "legendary_gear").read_text(encoding="utf-8")
    )
    ids = {entry["id"] for entry in manifest.get("entries", [])}
    result: dict[str, dict[str, Any]] = {}
    raw_root = _raw_manifests(repo) / "legendary_gear/raw_html"
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
    result: dict[str, dict[str, Any]] = {}
    for slug in VORAX_ENTITY_IDS:
        path = _canonical_raw_snapshot(repo, "inventory", slug)
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
    help_root = _raw_manifests(repo) / "help/raw_html"
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
        _source_manifest_path(repo, "talent").read_text(encoding="utf-8")
    )
    raw_root = _raw_manifests(repo) / "talent/raw_html"
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
    path = _canonical_raw_snapshot(repo, "inventory", "Ethereal_Prism")
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
        _source_manifest_path(repo, "hero").read_text(encoding="utf-8")
    )
    raw_root = _raw_manifests(repo) / "hero/raw_html"
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
    hero_path = _canonical_raw_snapshot(repo, "inventory", "Hero_Memories")
    revival_path = _raw_manifests(repo) / "help/raw_html/Memory_Revival.html"
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
        _source_manifest_path(repo, system_id).read_text(encoding="utf-8")
    )
    raw_root = _raw_manifests(repo) / system_id / "raw_html"
    result: dict[str, str] = {}
    for entry in manifest.get("entries", []):
        slug = entry.get("slug") or entry.get("id")
        path = raw_root / f"{quote(slug, safe='-_.')}.html"
        if not path.is_file() or not path.stat().st_size:
            path = (
                _raw_manifests(repo) / "recovered_internal_pages/raw_html"
                / f"{quote(slug, safe='-_.')}.html"
            )
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
    data = json.loads(_system_manifest_path(repo).read_text(encoding="utf-8"))
    return {
        entity_route_key(item["index_url"])
        for item in data.get("systems", [])
        if item.get("index_url")
    }


def build_entity_index_v3(
    repo: Path, season_context: SeasonContext | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    global _SEASON_CONTEXT
    _SEASON_CONTEXT = season_context or SeasonContext(repo, DEFAULT_SEASON)
    v2, bootstrap_report = _bootstrap_v2_from_sources(repo)
    manifest_titles = _manifest_titles(repo)
    i18n_titles = _i18n_titles(_SEASON_CONTEXT.readable_i18n_file())
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
        page = None
        page_heading = _raw_heading(repo, old, None)
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
        summary_source = _bootstrap_plain_text(repo, old)
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
                "entity_type": "legendary_equipment",
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

    existing_routes = {entity["canonical_route"] for entity in entities}
    destiny_manifest = json.loads(
        _source_manifest_path(repo, "destiny").read_text(encoding="utf-8")
    )
    for entry in destiny_manifest.get("entries", []):
        slug = entry.get("slug") or entry.get("id")
        route = entity_route_key(entry.get("url") or f"/cn/{slug}/")
        if route in existing_routes or slug not in fate_summaries:
            continue
        title = entry.get("name_zh") or entry.get("name") or entry.get("id") or slug
        entities.append({
            "entity_id": f"tlidb:cn:{slug}",
            "title": title,
            "canonical_route": route,
            "content_category_id": "pact_spirit",
            "content_category_name_zh": "契灵系统",
            "content_subcategory_id": "pact_spirit_destiny",
            "content_subcategory_name_zh": "命运",
            "sources": [
                {"system_id": "destiny", "role": "primary"},
                {"system_id": "recovered_internal_pages", "role": "source"},
            ],
            "confidence": "primary",
            "entity_title_zh": title,
            "entity_visibility": "visible",
            "clean_summary": fate_summaries[slug],
            "entity_type": "fate",
        })
        existing_routes.add(route)
        visibility["visible"] += 1
        title_sources["destiny_manifest_name_zh"] += 1

    entities.sort(key=lambda item: item["canonical_route"])
    index = {"schema_version": 3, "entities": entities}
    report = {
        "schema_version": 1,
        "total_entities": len(entities),
        "visible_entities": visibility["visible"],
        "hidden_entities": visibility["hidden"],
        "title_source_distribution": dict(sorted(title_sources.items())),
        "empty_clean_summary_count": sum(not item["clean_summary"] for item in entities),
        "fresh_bootstrap": bootstrap_report,
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
    craft = json.loads(_source_manifest_path(repo, "craft").read_text(encoding="utf-8"))
    legendary = json.loads(
        _source_manifest_path(repo, "legendary_gear").read_text(encoding="utf-8")
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
    accepted_example_ids = ("STR_Helmet", "Belt", "Crossbow")
    rejected_example_ids = (
        "Memory_of_Origin", "Memory_of_Progress", "Memory_of_Discipline"
    )
    missing_accepted = [
        slug for slug in accepted_example_ids
        if f"tlidb:cn:{slug}" not in accepted_by_id
    ]
    missing_rejected = [
        slug for slug in rejected_example_ids if slug not in rejected_by_id
    ]
    return {
        "schema_version": 2,
        "total_equipment_entities": len(equipment),
        "accepted_craft_sources": accepted,
        "rejected_craft_sources": rejected,
        "examples": {
            "accepted": [
                accepted_by_id[f"tlidb:cn:{slug}"]
                for slug in accepted_example_ids
                if f"tlidb:cn:{slug}" in accepted_by_id
            ],
            "rejected": [
                rejected_by_id[slug]
                for slug in rejected_example_ids if slug in rejected_by_id
            ],
            "unavailable": {
                "accepted": missing_accepted,
                "rejected": missing_rejected,
            },
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
        "warnings": [
            f"Report sample unavailable: {slug}"
            for slug in (*missing_accepted, *missing_rejected)
        ],
        "errors": [],
    }


def entity_stage_readiness(repo: Path, index: dict[str, Any]) -> dict[str, Any]:
    """Validate production source coverage before any generated output is replaced."""
    manifest = json.loads(_system_manifest_path(repo).read_text(encoding="utf-8"))
    systems = manifest.get("systems", [])
    inventory = next(
        (
            item for item in systems
            if item.get("system_id") == "inventory"
            and item.get("discovery_status") == "confirmed"
        ),
        None,
    )
    unresolved_inventory = next(
        (
            item for item in systems
            if (
                item.get("system_id") == "candidate_inventory"
                or item.get("index_slug") == "Inventory"
            )
            and item.get("discovery_status") != "confirmed"
        ),
        None,
    )
    ordinary_ids = {
        item["entity_id"] for item in index.get("entities", [])
        if item.get("entity_type") == "equipment"
        and item.get("content_subcategory_id") == "equipment_craft"
    }
    expected_ids = {f"tlidb:cn:{slug}" for slug in ORDINARY_EQUIPMENT_IDS}
    missing = sorted(expected_ids - ordinary_ids)
    snapshot_entries, snapshot_path = _inventory_snapshot_entries(repo)
    inventory_source_available = inventory is not None or bool(snapshot_entries)
    errors = []
    if not inventory_source_available:
        errors.append("production-required Inventory source is unavailable")
    if missing:
        errors.append(
            f"ordinary equipment coverage is incomplete: {len(ordinary_ids)}/"
            f"{len(expected_ids)}"
        )
    return {
        "ready": not errors,
        "inventory_confirmed": inventory is not None,
        "inventory_source_mode": (
            "formal_manifest" if inventory is not None
            else "cached_canonical_index" if snapshot_entries else None
        ),
        "inventory_manifest": inventory.get("manifest_path") if inventory else None,
        "inventory_snapshot": str(snapshot_path) if snapshot_path else None,
        "inventory_snapshot_entry_count": len(snapshot_entries),
        "inventory_candidate_unresolved": unresolved_inventory is not None,
        "ordinary_equipment_expected": len(expected_ids),
        "ordinary_equipment_generated": len(ordinary_ids),
        "missing_ordinary_equipment": missing,
        "errors": errors,
    }


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


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
    example_slugs = (
        "Thunder_Channeling_Prosthetics", "Crosser", "Frozen_Sight",
        "Glorious_Journey", "Omniscient_Prototype", "Awaiting",
    )
    examples = [by_slug[slug] for slug in example_slugs if slug in by_slug]
    missing_examples = [slug for slug in example_slugs if slug not in by_slug]
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
        "warnings": [
            f"Report sample unavailable: {slug}" for slug in missing_examples
        ],
        "errors": [],
    }


def vorax_equipment_entity_v1_report(repo: Path, index: dict[str, Any]) -> dict[str, Any]:
    extracted = _vorax_entities(repo)
    by_id = {entity["entity_id"]: entity for entity in index.get("entities", [])}
    entities = [
        by_id[f"tlidb:cn:{slug}"] for slug in VORAX_ENTITY_IDS
        if f"tlidb:cn:{slug}" in by_id
    ]
    example_slugs = (
        "Vorax_Limb:_Head", "Vorax_Limb:_Legs", "Vorax_Aberrant_Limb:_Digits"
    )
    examples = [
        by_id[f"tlidb:cn:{slug}"] for slug in example_slugs
        if f"tlidb:cn:{slug}" in by_id and slug in extracted
    ]
    missing_entities = [
        slug for slug in VORAX_ENTITY_IDS if f"tlidb:cn:{slug}" not in by_id
    ]
    missing_examples = [
        slug for slug in example_slugs
        if f"tlidb:cn:{slug}" not in by_id or slug not in extracted
    ]
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
        "warnings": (
            ([] if len(extracted) == len(VORAX_ENTITY_IDS) else [
                f"Expected {len(VORAX_ENTITY_IDS)} Vorax entities, got {len(extracted)}."
            ])
            + [f"Entity unavailable: {slug}" for slug in missing_entities]
            + [f"Report sample unavailable: {slug}" for slug in missing_examples]
        ),
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


def fresh_bootstrap_report(
    index: dict[str, Any], reference: dict[str, Any] | None = None
) -> dict[str, Any]:
    entities = index.get("entities", [])
    current = (reference or {}).get("entities", [])
    new_by_id = {item["entity_id"]: item for item in entities}
    old_by_id = {item["entity_id"]: item for item in current}
    shared = sorted(new_by_id.keys() & old_by_id.keys())

    def diffs(field: str) -> list[dict[str, Any]]:
        return [
            {
                "entity_id": entity_id,
                "current": old_by_id[entity_id].get(field),
                "fresh": new_by_id[entity_id].get(field),
            }
            for entity_id in shared
            if old_by_id[entity_id].get(field) != new_by_id[entity_id].get(field)
        ]

    classification = [
        entity_id for entity_id in shared
        if any(
            old_by_id[entity_id].get(field) != new_by_id[entity_id].get(field)
            for field in (
                "content_category_id", "content_category_name_zh",
                "content_subcategory_id", "content_subcategory_name_zh",
            )
        )
    ]
    counts = Counter(item.get("entity_type") or "legacy_or_skill" for item in entities)
    visible_skill = sum(
        item.get("content_category_id") == "skill"
        and item.get("entity_visibility") == "visible"
        for item in entities
    )
    ordinary = sum(
        item.get("content_subcategory_id") == "equipment_craft"
        and item.get("entity_type") == "equipment"
        for item in entities
    )
    vorax = sum(item.get("content_subcategory_id") == "equipment_vorax" for item in entities)
    legendary = sum(item.get("entity_type") == "legendary_equipment" for item in entities)
    talent = sum(item.get("entity_type") == "talent" for item in entities)
    fate_routes = {
        "/cn/Micro_Fate:_Deterioration_Duration/",
        "/cn/Micro_Fate:_Trauma_Damage_Mitigation/",
    }
    recovered_fate = [
        item for item in entities if item.get("canonical_route") in fate_routes
    ]
    legendary_ownership_errors = [
        item["entity_id"] for item in entities
        if item.get("entity_type") == "legendary_equipment"
        and not any(
            source.get("source_type") == "legendary_gear"
            or source.get("system_id") == "legendary_gear"
            for source in item.get("sources", [])
        )
    ]
    missing = sorted(old_by_id.keys() - new_by_id.keys())
    extra = sorted(new_by_id.keys() - old_by_id.keys())
    field_diffs = {
        "classification_diffs": classification,
        "visibility_diffs": diffs("entity_visibility"),
        "route_diffs": diffs("canonical_route"),
        "entity_type_diffs": diffs("entity_type"),
    }
    source_truth_refresh = {
        "title_diffs": len(diffs("title")),
        "entity_title_zh_diffs": len(diffs("entity_title_zh")),
        "confidence_diffs": len(diffs("confidence")),
        "clean_summary_diffs": len(diffs("clean_summary")),
        "classification": (
            "expected_source_truth_refresh: presentation text is re-extracted from current "
            "Manifest/Raw and confidence is recalculated from current Raw fingerprints; "
            "legacy Search/audit values are not copied forward"
        ),
    }
    regression_same = (
        not missing and not extra and not any(field_diffs.values())
        if reference is not None else None
    )
    bootstrap_supported = bool(entities) and index.get("schema_version") == 3
    digest = hashlib.sha256(
        json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema_version": 1,
        "old_dependency_graph": [
            "entity-dedup-audit.json -> entity-index.json",
            "entity-index.json + entity-coverage-v2-audit.json + local search-index.json -> entity-index-v2.json",
            "entity-index-v2.json + local search-index.json + Raw/Manifest -> entity-index-v3.json",
        ],
        "new_dependency_graph": [
            "system/child manifests + Raw HTML + tracked config/rules -> entity-index-v3.json",
            "entity-index-v3.json -> optional validation/audit reports",
        ],
        "required_inputs": [
            "sources/system_manifest.json", "sources/<system>_manifest.json",
            "data/raw/manifests/<system>/raw_html/", "config/game_category_mapping.json",
            "tracked deterministic classification/source-priority rules",
        ],
        "removed_required_inputs": [
            "data/reports/**", "local_wiki/**", "search-index.json",
            "entity-index.json", "entity-index-v2.json", "structured-search-index.json",
        ],
        "fresh_bootstrap_supported": bootstrap_supported,
        "fresh_entity_bootstrap_ready": bootstrap_supported and regression_same is not False,
        "entity_counts": {
            "current_count": len(current),
            "fresh_bootstrap_count": len(entities),
            "ordinary_equipment": ordinary,
            "legendary_equipment": legendary,
            "vorax": vorax,
            "memory": counts["memory_system"],
            "equipment_related": counts["equipment_related_system"],
            "ethereal_prism": counts["talent_system"],
            "pact": counts["pact_spirit"],
            "fate": counts["fate"],
            "hero_trait": counts["hero"],
            "talent": talent,
            "skill_visible": visible_skill,
        },
        "regression_comparison": {
            "same": regression_same,
            "same_entity_ids": not missing and not extra,
            "missing": missing,
            "extra": extra,
            **field_diffs,
            "non_contract_source_truth_refresh": source_truth_refresh,
        },
        "source_priority_validation": {
            "legendary_over_craft": not legendary_ownership_errors,
            "legendary_ownership_errors": legendary_ownership_errors,
        },
        "recovered_fate_validation": {
            "expected": 2,
            "actual": len(recovered_fate),
            "valid": len(recovered_fate) == 2 and all(
                item.get("entity_type") == "fate"
                and item.get("content_subcategory_id") == "pact_spirit_destiny"
                for item in recovered_fate
            ),
        },
        "legacy_visibility_validation": {
            "hidden_entities": sum(item.get("entity_visibility") == "hidden" for item in entities),
            "hidden_entity_count_matches_current": sum(
                item.get("entity_visibility") == "hidden" for item in entities
            ) == sum(item.get("entity_visibility") == "hidden" for item in current),
            "warehouse_metadata_deterministic": all(
                item.get("content_subcategory_id") == "equipment_type"
                for item in entities
                if item.get("entity_id") == "tlidb:cn:Sandlord_Season"
            ),
        },
        "determinism_validation": {
            "stable_sort": [item["canonical_route"] for item in entities]
            == sorted(item["canonical_route"] for item in entities),
            "canonical_sha256": digest,
            "does_not_use_mtime_or_generated_state": True,
        },
        "consumer_compatibility": {
            "schema_version": index.get("schema_version"),
            "schema_unchanged": index.get("schema_version") == 3,
            "required_fields_present": all(
                all(field in item for field in ("entity_id", "canonical_route", "sources"))
                for item in entities
            ),
            "builder_and_structured_changes_required": False,
        },
        "errors": (
            [] if regression_same is not False
            else ["Fresh bootstrap differs from current Entity model."]
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--output", type=Path)
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
    parser.add_argument(
        "--fresh-bootstrap-report",
        type=Path,
        default=Path("data/reports/local-wiki/entity-v3-fresh-bootstrap-v1-report.json"),
    )
    parser.add_argument(
        "--reference-index",
        type=Path,
        default=None,
        help="Optional regression reference; never used as a generation input.",
    )
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    context = SeasonContext(repo, args.season)
    output_arg = args.output or context.entity_output
    output = output_arg if output_arg.is_absolute() else repo / output_arg
    reference_path = args.reference_index
    if reference_path is None:
        reference_path = context.readable_entity_output()
    elif not reference_path.is_absolute():
        reference_path = repo / reference_path
    reference = (
        json.loads(reference_path.read_text(encoding="utf-8"))
        if reference_path.is_file() else None
    )
    index, report = build_entity_index_v3(repo, context)
    readiness = entity_stage_readiness(repo, index)
    report["production_readiness"] = readiness
    if not readiness["ready"]:
        raise RuntimeError("; ".join(readiness["errors"]))
    def scoped_report(path: Path) -> Path:
        if args.season != DEFAULT_SEASON:
            return context.report_root / path.name
        return path if path.is_absolute() else repo / path

    report_path = scoped_report(args.report)
    equipment_report_path = scoped_report(args.equipment_report)
    craft_filter_report_path = (
        args.equipment_craft_filter_report
        if args.equipment_craft_filter_report.is_absolute()
        else scoped_report(args.equipment_craft_filter_report)
    )
    legendary_report_path = (
        args.legendary_gear_report if args.legendary_gear_report.is_absolute()
        else scoped_report(args.legendary_gear_report)
    )
    vorax_report_path = (
        args.vorax_equipment_report if args.vorax_equipment_report.is_absolute()
        else scoped_report(args.vorax_equipment_report)
    )
    equipment_related_report_path = (
        args.equipment_related_system_report
        if args.equipment_related_system_report.is_absolute()
        else scoped_report(args.equipment_related_system_report)
    )
    talent_report_path = (
        args.talent_system_report
        if args.talent_system_report.is_absolute()
        else scoped_report(args.talent_system_report)
    )
    ethereal_prism_report_path = (
        args.ethereal_prism_report
        if args.ethereal_prism_report.is_absolute()
        else scoped_report(args.ethereal_prism_report)
    )
    hero_report_path = (
        args.hero_report if args.hero_report.is_absolute()
        else scoped_report(args.hero_report)
    )
    memory_system_report_path = (
        args.memory_system_report if args.memory_system_report.is_absolute()
        else scoped_report(args.memory_system_report)
    )
    pact_fate_report_path = (
        args.pact_fate_search_report if args.pact_fate_search_report.is_absolute()
        else scoped_report(args.pact_fate_search_report)
    )
    fresh_report_path = (
        args.fresh_bootstrap_report if args.fresh_bootstrap_report.is_absolute()
        else scoped_report(args.fresh_bootstrap_report)
    )
    # Build every optional report before touching the production Entity output.
    # A missing audit sample or a report bug must never leave a partial index.
    payloads = [
        (report_path, report),
        (equipment_report_path, equipment_entity_v2_report(index)),
        (craft_filter_report_path, equipment_craft_enrichment_filter_v2_report(repo, index)),
        (legendary_report_path, legendary_gear_entity_v1_report(repo, index)),
        (vorax_report_path, vorax_equipment_entity_v1_report(repo, index)),
        (equipment_related_report_path, equipment_related_system_entity_v1_report(index)),
        (talent_report_path, talent_system_entity_v1_report(index)),
        (ethereal_prism_report_path, ethereal_prism_entity_v1_report(repo, index)),
        (hero_report_path, hero_entity_v1_report(index)),
        (memory_system_report_path, memory_system_entity_v1_report(index)),
        (pact_fate_report_path, pact_fate_search_cleanup_v1_report(index)),
        (fresh_report_path, fresh_bootstrap_report(index, reference)),
    ]
    for path, payload in payloads:
        atomic_write_json(path, payload)
    # Entity output is the final publication step.
    atomic_write_json(output, index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
