from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import posixpath
import re
import shutil
import sys
import time
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urldefrag, urljoin, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
ASSET_ATTRS = {"img": ("src", "srcset"), "link": ("href",), "script": ("src",),
               "source": ("src", "srcset"), "video": ("poster",), "object": ("data",)}
TRACKING = ("google-analytics", "googletagmanager", "doubleclick", "facebook.net", "hotjar",
            "clarity.ms", "adservice", "analytics", "nitropay", "cloudflareinsights")
CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I)
CSS_IMPORT = re.compile(r"(@import\s+)(['\"])(.*?)\2", re.I)
ATTR = r"(?P<prefix>\b%s\s*=\s*)(?P<quote>['\"]?)(?P<value>.*?)(?P=quote)(?=\s|/?>)"
RUNTIME = re.compile(r"\bfetch\s*\(|\bXMLHttpRequest\b|\$\.(?:ajax|get|post|getJSON)\s*\(|\baxios(?:\.|\s*\()", re.I)
RUNTIME_URL = re.compile(r"(?:fetch|axios(?:\.get|\.post)?|\$\.(?:get|post|getJSON))\s*\(\s*['\"]([^'\"]+)|\.open\s*\(\s*['\"][A-Z]+['\"]\s*,\s*['\"]([^'\"]+)", re.I)
AJAX_URL = re.compile(r"\$\.ajax\s*\(\s*\{[^}]*?\burl\s*:\s*['\"]([^'\"]+)", re.I | re.S)
SYSTEM_I18N_KEYS = {
    "hero": "HeroRanking|name|1", "talent": "handbook|name|30010",
    "inventory": "function|name|115", "legendary_gear": "AuctionHouse_rough_search|description|1",
    "pactspirit": "function|name|130", "drop_source": "TextTable_GameFunc|value|Func_Tips_DropSource",
    "destiny": "manual_ruledes_filter|des|200503", "active_skill": "TextTable_GameFunc|value|Func_SkillBag_SkillType1",
    "support_skill": "TextTable_GameFunc|value|Func_SkillBag_SkillType2",
    "passive_skill": "TextTable_GameFunc|value|Func_SkillBag_SkillType3",
    "activation_medium_skill": "TextTable_GameFunc|value|Func_SkillBag_SkillType5",
    "magnificent_support_skill": "item_type_list|name|50605", "noble_support_skill": "item_type_list|name|50606",
    "modularization_skill": "item_type_list|name|50607", "craft": "function|name|128",
    "corrosion": "function|name|133", "candidate_gear_empowerment": "function|name|901",
    "nether_kings_divinity": "item_type_list|name|80201",
    "path_of_progression": "TextTable_GameFunc|value|Func_Growth_GrowPath_Title",
    "help": "function|name|122", "codex": "function|name|124",
    "tip": "TextTable_GameFunc|value|Func_Common_Mind", "netherrealm": "system_help|name|8",
    "confusion_card_library": "TextTable_GameFunc|value|Func_MysteryCard_AdditionDeck",
    "void_chart": "function|name|171", "compass": "item_type_list|name|51001",
    "probe": "TextTable_GameFunc|value|Func_FarmReference_MysticOrb",
    "season_compass": "item_type_list|name|51002", "path_of_the_brave": "function|name|137",
    "candidate_outfit": "TextTable_GameFunc|value|Func_Fashion_Type1",
    "commodity": "TextTable_GameFunc|value|Func_Pack_Currency_Tab", "boon": "function|name|132",
}
SYSTEM_NAME_ZH_FALLBACKS = {
    "hyperlink": "超链接",
    "recovered_internal_pages": "补充页面",
}
SEARCH_INFO_ID = re.compile(r"\bInfo\s+id\s*:\s*\d+\b", re.I)
SEARCH_SHOW_DESCRIPTION = re.compile(r"\bShow\s+Description\b", re.I)
SEARCH_TIER_NAME = re.compile(r"\bTier\s+name(?:\s+[-+]?\d+)?\b", re.I)
SEARCH_ENCODED_TOKEN = re.compile(r"\S*%[0-9A-Fa-f]{2}\S*")
SEARCH_SKILL_SYSTEMS = {
    "active_skill", "support_skill", "passive_skill", "activation_medium_skill",
    "magnificent_support_skill", "noble_support_skill", "modularization_skill",
}
ENTITY_CLEAN_SUMMARY_TYPES = {
    "equipment", "equipment_related_system", "memory_system", "talent",
    "pact_spirit", "fate",
}
HTML_VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


def runtime_urls(text):
    values = [(match.group(1) or match.group(2)) for match in RUNTIME_URL.finditer(text)]
    values.extend(match.group(1) for match in AJAX_URL.finditer(text))
    return values


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(path):
    return path if path.is_absolute() else ROOT / path


def normalized_url(value, base, stats=None):
    value = html.unescape(value.strip())
    if not value or value.startswith(("#", "data:", "blob:", "javascript:", "mailto:")): return None
    resolved = urldefrag(urljoin(base, value))[0]
    parsed = urlsplit(value)
    if not parsed.scheme and not parsed.netloc and not parsed.path.startswith("/"):
        if stats is not None:
            stats["relative_url_resolutions"] += 1
            legacy_directory_join = urldefrag(urljoin(base.rstrip("/") + "/", value))[0]
            stats["wrong_directory_join_prevented"] += int(legacy_directory_join != resolved)
    return resolved


def tracking_url(value):
    host = (urlsplit(value).hostname or "").lower()
    return any(part in host for part in TRACKING)


def canonical_page_key(value, base="https://tlidb.com/cn/", stats=None):
    resolved = normalized_url(value, base, stats)
    if not resolved: return None
    parsed = urlsplit(resolved)
    host = (parsed.hostname or "").lower()
    if host not in {"tlidb.com", "www.tlidb.com"} or not parsed.path.startswith("/cn/"): return None
    path = "/" + "/".join(quote(unquote(part), safe="-_.~%:") for part in parsed.path.split("/") if part)
    return "https://tlidb.com" + path.rstrip("/")


def route_for_source(source_url):
    key = canonical_page_key(source_url)
    if not key: raise ValueError(f"Unsupported page URL: {source_url}")
    parts = [unquote(part) for part in urlsplit(key).path.split("/") if part]
    if any(part in {".", ".."} or "/" in part for part in parts): raise ValueError(f"Unsafe page URL: {source_url}")
    path = "/".join(parts)
    return f"{path}/index.html"


def is_chinese_text(value):
    return bool(value and re.search(r"[\u3400-\u9fff]", value))


def system_display_name(system, translations=None, manifest=None):
    system_id = system.get("system_id")
    for candidate in (system.get("name_zh"), (manifest or {}).get("name_zh")):
        if is_chinese_text(candidate):
            return candidate
    translations = translations or {}
    return (translations.get(SYSTEM_I18N_KEYS.get(system_id))
            or SYSTEM_NAME_ZH_FALLBACKS.get(system_id)
            or system_id)


def search_title_display(title):
    return " ".join((title or "").split())


def search_summary_display(plain_text):
    text = SEARCH_INFO_ID.sub(" ", plain_text or "")
    text = SEARCH_SHOW_DESCRIPTION.sub(" ", text)
    text = SEARCH_TIER_NAME.sub(" ", text)
    text = SEARCH_ENCODED_TOKEN.sub(" ", text)
    return " ".join(text.split())


def load_native_i18n(i18n_root):
    path = i18n_root / "i18n/cn.json" if i18n_root is not None else None
    return load_json(path) if path is not None and path.is_file() else {}


def load_game_category_mapping(mapping_path):
    if mapping_path is None or not mapping_path.is_file():
        return {}
    mapping = load_json(mapping_path)
    result = {}
    for category in mapping.get("categories", []):
        value = {
            "game_category": category.get("id"),
            "game_category_name_zh": category.get("name_zh"),
            "game_category_visibility": category.get("search_visibility"),
        }
        for system_id in category.get("systems", []):
            result[system_id] = value
    return result


CONTENT_TREE_FIELD_NAMES = (
    "content_category_id",
    "content_category_name_zh",
    "content_subcategory_id",
    "content_subcategory_name_zh",
)

KNOWN_ROUTE_SYSTEM_IDS = {
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
    "/cn/Ethereal_Prism/": "Ethereal_Prism",
    "/cn/Destiny/": "destiny",
    "/cn/Micro_Fate:_Deterioration_Duration/": "destiny",
    "/cn/Micro_Fate:_Trauma_Damage_Mitigation/": "destiny",
}


def load_game_content_tree(tree_path):
    if tree_path is None or not tree_path.is_file():
        return {}
    tree = load_json(tree_path)
    result = {}
    for category in tree.get("search_categories", []):
        for child in category.get("children", []):
            value = {
                "content_category_id": category.get("id"),
                "content_category_name_zh": category.get("name_zh"),
                "content_subcategory_id": child.get("id"),
                "content_subcategory_name_zh": child.get("name_zh"),
            }
            for system_id in child.get("systems", []):
                if system_id in result:
                    raise ValueError(f"Duplicate Game Content Tree system mapping: {system_id}")
                result[system_id] = value
    return result


def content_tree_fields_for_system(system_id, content_tree):
    value = content_tree.get(system_id)
    if value is None:
        return {field: None for field in CONTENT_TREE_FIELD_NAMES}
    return dict(value)


def content_tree_index_integration_report(search_pages, classification_sources=None):
    matched = [page for page in search_pages if page.get("content_category_id") is not None]
    categories = Counter(page["content_category_id"] for page in matched)
    subcategories = Counter(page["content_subcategory_id"] for page in matched)
    sources = Counter(classification_sources or {})
    return {
        "schema_version": 1,
        "search_index_schema_version": 5,
        "total_entries": len(search_pages),
        "matched": len(matched),
        "unmatched": len(search_pages) - len(matched),
        "category_distribution": dict(sorted(categories.items())),
        "subcategory_distribution": dict(sorted(subcategories.items())),
        "entity_override_count": sources["entity_override"],
        "route_override_count": sources["route_override"],
        "system_fallback_count": sources["system_fallback"],
        "warnings": [],
        "errors": [],
    }


ENTITY_FIELD_NAMES = (
    "entity_id",
    "entity_title",
    "entity_category",
    "entity_category_name_zh",
    "entity_confidence",
    "entity_title_zh",
    "entity_visibility",
    "clean_summary",
    "entity_type",
    "entity_sources",
)


def entity_route_key(route):
    path = unquote(urlsplit(route).path if "://" in route else route)
    if not path.startswith("/"):
        path = "/" + path
    if path.endswith("index.html"):
        path = path[:-len("index.html")]
    return path.rstrip("/") + "/"


def load_entity_index(entity_index_path):
    if entity_index_path is None or not entity_index_path.is_file():
        return {}
    data = load_json(entity_index_path)
    return {
        entity_route_key(entity["canonical_route"]): entity
        for entity in data.get("entities", [])
        if entity.get("canonical_route")
    }


def entity_fields_for_route(route, entities):
    entity = entities.get(entity_route_key(route))
    if entity is None:
        return {field: None for field in ENTITY_FIELD_NAMES}
    return {
        "entity_id": entity.get("entity_id"),
        "entity_title": entity.get("entity_title_zh") or entity.get("title"),
        "entity_category": entity.get("content_category_id", entity.get("category")),
        "entity_category_name_zh": entity.get(
            "content_category_name_zh", entity.get("category_name_zh")
        ),
        "entity_confidence": entity.get("confidence"),
        "entity_title_zh": entity.get("entity_title_zh"),
        "entity_visibility": entity.get("entity_visibility"),
        "clean_summary": entity.get("clean_summary"),
        "entity_type": entity.get("entity_type"),
        "entity_sources": entity.get("sources"),
    }


def resolve_content_tree_classification(page, entities, content_tree):
    route = entity_route_key(page.get("route") or page.get("source_url") or "")
    entity = entities.get(route)
    inventory_equipment_rejected = bool(
        page.get("system_id") == "inventory"
        and entity is not None
        and entity.get("content_category_id") == "equipment"
        and not (
            entity.get("entity_type") == "equipment"
            and entity.get("content_subcategory_id") in {
                "equipment_craft", "equipment_legendary", "equipment_vorax"
            }
        )
    )
    if (
        entity is not None
        and entity.get("content_category_id") is not None
        and not inventory_equipment_rejected
    ):
        return {
            "content_category_id": entity.get("content_category_id"),
            "content_category_name_zh": entity.get("content_category_name_zh"),
            "content_subcategory_id": entity.get("content_subcategory_id"),
            "content_subcategory_name_zh": entity.get("content_subcategory_name_zh"),
        }, "entity_override"
    if entity is not None and entity.get("category"):
        agreeing_primary = []
        for source in entity.get("sources", []):
            mapping = content_tree.get(source.get("system_id"))
            if (
                source.get("role") == "primary"
                and mapping is not None
                and mapping.get("content_category_id") == entity.get("category")
            ):
                agreeing_primary.append(mapping)
        if len(agreeing_primary) >= 2:
            return dict(agreeing_primary[0]), "entity_override"

    route_system_id = KNOWN_ROUTE_SYSTEM_IDS.get(route)
    if route_system_id in content_tree:
        return dict(content_tree[route_system_id]), "route_override"

    if page.get("system_id") == "craft" and entity is None:
        return {field: None for field in CONTENT_TREE_FIELD_NAMES}, "craft_rejected"

    if page.get("system_id") == "inventory":
        return {field: None for field in CONTENT_TREE_FIELD_NAMES}, "inventory_unclassified"

    system_mapping = content_tree.get(page.get("system_id"))
    if system_mapping is not None:
        return dict(system_mapping), "system_fallback"
    return {field: None for field in CONTENT_TREE_FIELD_NAMES}, "null"


def search_entity_integration_report(search_pages, entities):
    matched = []
    for page in search_pages:
        entity = entities.get(entity_route_key(page.get("route", "")))
        if entity is not None:
            matched.append(entity)
    categories = Counter(
        entity.get("category") if entity.get("category") is not None else "null"
        for entity in matched
    )
    confidence = Counter(entity.get("confidence") or "null" for entity in matched)
    return {
        "schema_version": 1,
        "search_index_schema_version": 4,
        "total_index_entries": len(search_pages),
        "matched_entities": len(matched),
        "matched_unique_entities": len({entity.get("entity_id") for entity in matched}),
        "unmatched_entries": len(search_pages) - len(matched),
        "entity_distribution": {
            "by_category": dict(sorted(categories.items())),
            "by_confidence": dict(sorted(confidence.items())),
        },
        "warnings": [],
        "errors": [],
    }


def search_entity_v2_integration_report(search_pages, entities):
    matched_entities = []
    for page in search_pages:
        entity = entities.get(entity_route_key(page.get("route") or page.get("source_url") or ""))
        if entity is not None:
            matched_entities.append(entity)
    unique = {
        entity["entity_id"]: entity
        for entity in matched_entities
        if entity.get("entity_id")
    }
    confidence = Counter(entity.get("confidence") or "null" for entity in unique.values())
    categories = Counter(
        entity.get("content_category_id") or "null" for entity in unique.values()
    )
    return {
        "schema_version": 1,
        "search_index_schema_version": 6,
        "total_entries": len(search_pages),
        "entity_matched": len(matched_entities),
        "unique_entities": len(unique),
        "primary_entities": confidence["primary"],
        "high_entities": confidence["high"],
        "medium_entities": confidence["medium"],
        "unmatched": len(search_pages) - len(matched_entities),
        "category_distribution": dict(sorted(categories.items())),
        "warnings": [],
        "errors": [],
    }


def pages_from_system_manifest(system_manifest_path, requested_system_id=None, translations=None):
    system_manifest = load_json(system_manifest_path)
    pages = []
    systems_included = []
    known_missing = []
    for system in system_manifest.get("systems", []):
        status = system.get("discovery_status") or system.get("status")
        system_id = system.get("system_id")
        if status != "confirmed" or (requested_system_id and system_id != requested_system_id):
            continue
        manifest_value = system.get("manifest_path")
        if not manifest_value:
            raise ValueError(f"Confirmed system {system_id!r} has no manifest_path")
        manifest_path = Path(manifest_value)
        if not manifest_path.is_absolute():
            manifest_path = ROOT / manifest_path
        manifest = load_json(manifest_path)
        systems_included.append(system_id)
        system_name_zh = system_display_name(system, translations, manifest)
        for entry in manifest.get("entries", []):
            if entry.get("validation", {}).get("status") == "not_found":
                known_missing.append({"system_id": system_id, "id": entry.get("id")})
                continue
            pages.append({
                "system_id": system_id,
                "system_name_zh": system_name_zh,
                "source_type": "official_system",
                "id": entry.get("id") or entry.get("slug"),
                "slug": entry.get("slug") or entry.get("id"),
                "title": entry.get("name_zh") or entry.get("name") or entry.get("id"),
                "source_url": entry.get("url"),
            })
    return pages, systems_included, known_missing


def pages_from_supplemental_manifest(manifest_path, requested_system_id=None, translations=None):
    if manifest_path is None or not manifest_path.is_file():
        return []
    manifest = load_json(manifest_path)
    system_id = manifest.get("system_id") or "recovered_internal_pages"
    system_name_zh = system_display_name({"system_id": system_id}, translations, manifest)
    if requested_system_id and requested_system_id != system_id:
        return []
    pages = []
    for entry in manifest.get("entries", []):
        if entry.get("validation", {}).get("status") != "available":
            continue
        pages.append({
            "system_id": system_id, "system_name_zh": system_name_zh,
            "source_type": "recovered_internal",
            "id": entry.get("id") or entry.get("slug"),
            "slug": entry.get("slug") or entry.get("id"),
            "title": entry.get("name_zh") or entry.get("name") or entry.get("id"),
            "source_url": entry.get("url"),
        })
    return pages


def supplemental_route_for_source(source_url):
    key = canonical_page_key(source_url)
    if not key:
        raise ValueError(f"Unsupported page URL: {source_url}")
    parts = [quote(unquote(part), safe="-_.~") for part in urlsplit(key).path.split("/") if part]
    return "/".join(parts) + "/index.html"


def output_path_for_route(output, route):
    return output / unquote(route)


def replace_attribute(raw, name, callback):
    pattern = re.compile(ATTR % re.escape(name), re.I | re.S)
    def replace(match):
        value = callback(match.group("value"))
        if value is None: return match.group(0)
        quote_char = match.group("quote") or '"'
        return match.group("prefix") + quote_char + html.escape(value, quote=True) + quote_char
    return pattern.sub(replace, raw, count=1)


def append_or_replace_attribute(raw, name, value):
    changed = replace_attribute(raw, name, lambda _: value)
    if changed != raw: return changed
    return re.sub(r"\s*/?>$", lambda m: f' {name}="{html.escape(value, quote=True)}"{m.group(0)}', raw)


class TextInspector(HTMLParser):
    def __init__(self, visible_skill_content_only=False):
        super().__init__(convert_charrefs=True)
        self.visible_skill_content_only = visible_skill_content_only
        self.skip = 0; self.text = []; self.title = ""; self.in_title = False
        self.element_stack = []

    def _excluded(self, tag, attrs):
        if tag in {"script", "style", "nav", "footer"}:
            return True
        if not self.visible_skill_content_only:
            return False
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").lower().split())
        locator = f"{attributes.get('id') or ''} {attributes.get('class') or ''}".lower()
        style = (attributes.get("style") or "").lower()
        inactive_tab = "tab-pane" in classes and not classes.intersection({"active", "show"})
        search_value_table = tag == "table" and "datatable" in classes
        historical_version = bool(classes.intersection({"previousitem", "history", "historical"}))
        explicitly_hidden = (
            "hidden" in attributes
            or (attributes.get("aria-hidden") or "").lower() == "true"
            or "d-none" in classes
            or "display:none" in style.replace(" ", "")
            or "visibility:hidden" in style.replace(" ", "")
        )
        return (inactive_tab or "npc" in locator or search_value_table
                or historical_version or explicitly_hidden)

    def _exclude_enclosing_link_list_card(self):
        for frame in reversed(self.element_stack):
            if "card" in frame["classes"]:
                if not frame["excluded"]:
                    frame["excluded"] = True
                    self.skip += 1
                    del self.text[frame["text_start"]:]
                return True
        return False

    def handle_starttag(self, tag, attrs):
        excluded = self._excluded(tag, attrs)
        if excluded: self.skip += 1
        if tag not in HTML_VOID_ELEMENTS:
            attributes = dict(attrs)
            self.element_stack.append({
                "tag": tag,
                "excluded": excluded,
                "classes": set((attributes.get("class") or "").lower().split()),
                "text_start": len(self.text),
            })
        if tag == "title": self.in_title = True
    def handle_endtag(self, tag):
        for index in range(len(self.element_stack) - 1, -1, -1):
            if self.element_stack[index]["tag"] == tag:
                removed = self.element_stack[index:]
                del self.element_stack[index:]
                self.skip -= sum(frame["excluded"] for frame in removed)
                break
        if tag == "title": self.in_title = False
    def handle_data(self, data):
        if self.in_title: self.title += data
        if (self.visible_skill_content_only and not self.skip and data.strip().casefold()
                in {"alts", "related skills", "关联技能"}
                and self.element_stack
                and "card-header" in self.element_stack[-1]["classes"]):
            self._exclude_enclosing_link_list_card()
            return
        if not self.skip: self.text.append(data)


class CSSRewriter:
    def __init__(self, asset_map, web_prefix):
        self.asset_map = asset_map; self.web_prefix = web_prefix; self.rewrites = 0; self.unresolved = Counter(); self.stats = Counter()

    def target(self, value, source_url, relative_from=None):
        absolute = normalized_url(value, source_url, self.stats)
        if not absolute: return None
        asset = self.asset_map.get(absolute)
        if not asset:
            if urlsplit(absolute).scheme in {"http", "https"} and not tracking_url(absolute): self.unresolved[urlsplit(absolute).hostname or ""] += 1
            return None
        fragment = urlsplit(html.unescape(value)).fragment
        target = "assets/" + asset["local_relative_path"]
        rewritten = posixpath.relpath(target, posixpath.dirname(relative_from)) if relative_from else self.web_prefix + target
        if fragment: rewritten += "#" + fragment
        self.rewrites += 1
        return rewritten

    def rewrite(self, text, source_url, relative_from=None):
        def css_url(match):
            target = self.target(match.group(2), source_url, relative_from)
            return match.group(0) if target is None else f"url({match.group(1)}{target}{match.group(1)})"
        text = CSS_URL.sub(css_url, text)
        def css_import(match):
            target = self.target(match.group(3), source_url, relative_from)
            return match.group(0) if target is None else match.group(1) + match.group(2) + target + match.group(2)
        return CSS_IMPORT.sub(css_import, text)


class HTMLRewriter(HTMLParser):
    def __init__(self, base_url, route_map, asset_map, web_prefix, css_rewriter):
        super().__init__(convert_charrefs=False)
        self.base_url = base_url; self.route_map = route_map; self.asset_map = asset_map
        self.web_prefix = web_prefix; self.search_url = web_prefix + "_local/search/"; self.css = css_rewriter
        self.output = []; self.skip_tag = None; self.skip_depth = 0; self.in_style = False; self.in_script = False
        self.stats = Counter(); self.unresolved_internal = set(); self.runtime_examples = []

    def asset_value(self, value):
        absolute = normalized_url(value, self.base_url, self.stats)
        if not absolute: return None
        asset = self.asset_map.get(absolute)
        if not asset:
            if urlsplit(absolute).scheme in {"http", "https"} and not tracking_url(absolute):
                self.stats["remaining_remote_asset_references"] += 1
                self.stats[f"remote_domain:{urlsplit(absolute).hostname or ''}"] += 1
            return None
        self.stats["html_asset_rewrites"] += 1
        fragment = urlsplit(html.unescape(value)).fragment
        target = self.web_prefix + "assets/" + asset["local_relative_path"]
        return target + (("#" + fragment) if fragment else "")

    def srcset(self, value):
        parts = []
        for entry in value.split(","):
            pieces = entry.strip().split(None, 1)
            if not pieces: continue
            target = self.asset_value(pieces[0]) or pieces[0]
            parts.append(target + ((" " + pieces[1]) if len(pieces) > 1 else ""))
        return ", ".join(parts)

    def internal_href(self, value):
        parsed = urlsplit(html.unescape(value)); key = canonical_page_key(value, self.base_url, self.stats)
        if not key: return None
        route = self.route_map.get(key)
        if not route:
            self.unresolved_internal.add(key); self.stats["internal_page_links_unresolved"] += 1
            if not parsed.scheme and not parsed.netloc and not parsed.path.startswith("/"):
                self.stats["relative_catalog_miss_canonicalized"] += 1
                suffix = (("?" + parsed.query) if parsed.query else "") + (("#" + parsed.fragment) if parsed.fragment else "")
                return key + suffix
            return None
        self.stats["internal_page_links_rewritten"] += 1
        suffix = (("?" + parsed.query) if parsed.query else "") + (("#" + parsed.fragment) if parsed.fragment else "")
        return self.web_prefix + route.removesuffix("index.html") + suffix

    def is_tracking_element(self, raw):
        lower = html.unescape(raw).lower()
        return any(part in lower for part in TRACKING)

    def handle_starttag(self, tag, attrs):
        if self.skip_tag:
            if tag == self.skip_tag: self.skip_depth += 1
            return
        raw = self.get_starttag_text()
        if tag in {"script", "iframe", "ins"} and self.is_tracking_element(raw):
            self.skip_tag = tag; self.skip_depth = 1; self.stats["tracking_elements_removed"] += 1; return
        if tag in {"link", "img", "source"} and self.is_tracking_element(raw):
            self.stats["tracking_elements_removed"] += 1; return
        for attr in ASSET_ATTRS.get(tag, ()):
            raw = replace_attribute(raw, attr, self.srcset if attr == "srcset" else self.asset_value)
        if tag == "a": raw = replace_attribute(raw, "href", self.internal_href)
        if tag == "form":
            before = raw; raw = replace_attribute(raw, "action", lambda _: self.search_url)
            if raw != before:
                raw = append_or_replace_attribute(raw, "method", "get"); self.stats["search_forms_rewritten"] += 1
        before = raw
        raw = replace_attribute(raw, "style", lambda value: self.css.rewrite(value, self.base_url))
        self.output.append(raw)
        self.in_style = tag == "style"; self.in_script = tag == "script"

    def handle_startendtag(self, tag, attrs):
        if self.skip_tag: return
        raw = self.get_starttag_text()
        if self.is_tracking_element(raw): self.stats["tracking_elements_removed"] += 1; return
        for attr in ASSET_ATTRS.get(tag, ()):
            raw = replace_attribute(raw, attr, self.srcset if attr == "srcset" else self.asset_value)
        self.output.append(raw)

    def handle_endtag(self, tag):
        if self.skip_tag:
            if tag == self.skip_tag:
                self.skip_depth -= 1
                if self.skip_depth == 0: self.skip_tag = None
            return
        self.output.append(f"</{tag}>")
        if tag == "style": self.in_style = False
        if tag == "script": self.in_script = False

    def handle_data(self, data):
        if self.skip_tag: return
        if self.in_style:
            data = self.css.rewrite(data, self.base_url)
        if self.in_script:
            count = len(RUNTIME.findall(data)); self.stats["runtime_http_reference_count"] += count
            if count and len(self.runtime_examples) < 20:
                for value in runtime_urls(data):
                    if value: self.runtime_examples.append({"page": self.base_url, "reference": value})
            data = rewrite_i18n_runtime_paths(data, self.web_prefix)
        self.output.append(data)
    def handle_entityref(self, name): self.output.append(f"&{name};") if not self.skip_tag else None
    def handle_charref(self, name): self.output.append(f"&#{name};") if not self.skip_tag else None
    def handle_comment(self, data): self.output.append(f"<!--{data}-->") if not self.skip_tag else None
    def handle_decl(self, decl): self.output.append(f"<!{decl}>") if not self.skip_tag else None
    def handle_pi(self, data): self.output.append(f"<?{data}>") if not self.skip_tag else None


def local_assets():
    return {
        "_local/search/index.html": """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TLIDB Local Search</title><link rel="stylesheet" href="styles.css"><script defer src="app.js"></script></head><body><main><h1>TLIDB Local Search</h1><div class="search-layout"><nav id="content-tree" aria-label="游戏内容分类"></nav><section class="search-main"><input id="search" type="search" placeholder="搜索全部本地页面" autocomplete="off"><p id="status">正在载入索引……</p><div id="results"></div></section></div></main></body></html>""",
        "_local/search/styles.css": """body{margin:0;background:#f5f6f8;color:#20242a;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1180px;margin:auto;padding:24px}.search-layout{display:grid;grid-template-columns:220px minmax(0,1fr);gap:24px;align-items:start}#search{box-sizing:border-box;width:100%;padding:12px;font-size:18px}#content-tree{position:sticky;top:16px;padding:10px;background:#fff;border-radius:8px}.tree-all,.tree-primary,.tree-child{box-sizing:border-box;width:100%;border:0;background:transparent;color:#334155;text-align:left;cursor:pointer;border-radius:6px}.tree-all,.tree-primary{padding:9px 10px;font-size:16px;font-weight:650}.tree-child{padding:7px 10px 7px 28px;font-size:14px}.tree-all:hover,.tree-primary:hover,.tree-child:hover,.tree-selected{background:#e2e8f0;color:#0f172a}.tree-category{margin-top:4px}.tree-children[hidden]{display:none}.group{margin-top:24px}.result{margin:10px 0;padding:12px;background:#fff;border-radius:6px}.result a{color:#075985;text-decoration:none}.entity-card{border-left:4px solid #0f766e}.entity-meta{display:flex;gap:8px;align-items:center;margin-top:6px;color:#475569;font-size:14px}.entity-category{padding:2px 7px;border-radius:999px;background:#ccfbf1;color:#115e59}.entity-sources{margin:7px 0 0;color:#475569;font-size:14px}mark{background:#ffe58f}@media(max-width:760px){.search-layout{grid-template-columns:1fr}#content-tree{position:static}.tree-category{display:inline-block;vertical-align:top;width:calc(50% - 4px)}}""",
        "_local/search/app.js": """(()=>{
const q=document.querySelector('#search'),tree=document.querySelector('#content-tree'),out=document.querySelector('#results'),status=document.querySelector('#status');
const esc=s=>String(s).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));
const hi=(s,k)=>{const i=s.toLocaleLowerCase().indexOf(k);return i<0?esc(s):esc(s.slice(0,i))+'<mark>'+esc(s.slice(i,i+k.length))+'</mark>'+esc(s.slice(i+k.length))};
let pages=[],contentTree={search_categories:[],hidden_systems:[]},hiddenSystems=new Set,selectedCategory=null,selectedSubcategory=null;
const visibleSubcategories=categoryId=>new Set((contentTree.search_categories.find(category=>category.id===categoryId)?.children||[]).filter(child=>child.search_visibility!=='hidden').map(child=>child.id));
const matchesContentTree=x=>{if(x.entity_visibility==='hidden'||hiddenSystems.has(x.system_id))return false;if(selectedSubcategory)return x.content_category_id===selectedCategory&&x.content_subcategory_id===selectedSubcategory;if(selectedCategory)return x.content_category_id===selectedCategory&&visibleSubcategories(selectedCategory).has(x.content_subcategory_id);return true};
const setSelectedButton=button=>{tree.querySelectorAll('button').forEach(item=>item.classList.toggle('tree-selected',item===button))};
const selectFilter=(categoryId,subcategoryId,button)=>{selectedCategory=categoryId;selectedSubcategory=subcategoryId;setSelectedButton(button);run()};
const renderContentTree=()=>{tree.innerHTML='';const all=document.createElement('button');all.type='button';all.className='tree-all tree-selected';all.textContent='全部';all.addEventListener('click',()=>selectFilter(null,null,all));tree.append(all);contentTree.search_categories.filter(category=>category.search_visibility==='primary').forEach(category=>{const section=document.createElement('div');section.className='tree-category';const primary=document.createElement('button');primary.type='button';primary.className='tree-primary';primary.textContent=category.name_zh;primary.setAttribute('aria-expanded','false');const children=document.createElement('div');children.className='tree-children';children.hidden=true;primary.addEventListener('click',()=>{children.hidden=!children.hidden;primary.setAttribute('aria-expanded',String(!children.hidden));selectFilter(category.id,null,primary)});category.children.filter(child=>child.search_visibility!=='hidden').forEach(child=>{const button=document.createElement('button');button.type='button';button.className='tree-child';button.textContent=child.name_zh;button.addEventListener('click',()=>selectFilter(category.id,child.id,button));children.append(button)});section.append(primary,children);tree.append(section)})};
const collectEntitySources=()=>{const all=new Map;pages.forEach(x=>{if(!x.entity_id||hiddenSystems.has(x.system_id))return;if(!all.has(x.entity_id))all.set(x.entity_id,new Set);all.get(x.entity_id).add(x.content_subcategory_name_zh||x.system_name_zh||x.system_id)});return all};
const collapseEntityHits=(hits,allSources)=>{const display=[],entities=new Map;hits.forEach(v=>{const id=v.x.entity_id;if(!id){display.push({...v,kind:'page'});return}if(!entities.has(id)){const item={...v,kind:'entity',sources:new Set(allSources.get(id)||[])};entities.set(id,item);display.push(item)}else{entities.get(id).sources.add(v.x.system_name_zh||v.x.system_id)}});return display};
const resultHref=(x,raw)=>encodeURI('../../'+x.route)+'?local_search='+encodeURIComponent(raw);
const run=()=>{const raw=q.value.trim(),k=raw.toLocaleLowerCase();out.innerHTML='';if(!k){status.textContent=`当前分类包含 ${pages.filter(matchesContentTree).length} 个页面。`;return}
const hits=pages.map(x=>{const t=x.title.toLocaleLowerCase(),p=x.plain_text.toLocaleLowerCase(),ti=t.indexOf(k),pi=p.indexOf(k);return{x,score:ti>=0?0:1,pos:pi}}).filter(v=>v.score===0||v.pos>=0).filter(v=>matchesContentTree(v.x)).sort((a,b)=>a.score-b.score||a.x.title.localeCompare(b.x.title));
const displayHits=collapseEntityHits(hits,collectEntitySources());status.textContent=`找到 ${displayHits.length} 个结果。`;const groups=new Map;
const resultGroup=x=>({id:x.content_subcategory_id||x.content_category_id||x.system_id,name:x.content_subcategory_name_zh||x.content_category_name_zh||x.system_name_zh||x.system_id});
displayHits.forEach(v=>{const group=resultGroup(v.x);if(!groups.has(group.id))groups.set(group.id,{name:group.name,items:[]});groups.get(group.id).items.push(v)});
groups.forEach((group,id)=>{const items=group.items,section=document.createElement('section');section.className='group';section.innerHTML=`<h2>${esc(group.name||id)} (${items.length})</h2>`;
items.forEach(item=>{const x=item.x,entity=item.kind==='entity',displayTitle=entity?(x.entity_title||x.title_display||x.title):(x.title_display||x.title),summary=x.summary_display||x.plain_text,displayPos=summary.toLocaleLowerCase().indexOf(k),start=Math.max(0,(displayPos<0?0:displayPos)-60),d=document.createElement('div');d.className=entity?'result entity-card':'result';const meta=entity?`<div class=\"entity-meta\"><span class=\"entity-category\">${esc(x.content_category_name_zh||x.entity_category_name_zh||x.entity_category||'未分类')}</span></div><p class=\"entity-sources\">来源：${[...item.sources].map(esc).join('、')}</p>`:'';d.innerHTML=`<a href=\"${resultHref(x,raw)}\"><strong>${hi(displayTitle,k)}</strong></a>${meta}<p>${hi(summary.slice(start,start+140),k)}</p>`;section.append(d)});out.append(section)})};
Promise.all([fetch('../../search-index.json').then(r=>r.json()),fetch('game-content-tree.json').then(r=>r.json())]).then(([index,treeConfig])=>{pages=index.pages||index;contentTree=treeConfig;hiddenSystems=new Set(contentTree.hidden_systems.map(item=>item.system_id));renderContentTree();const initial=new URLSearchParams(location.search).get('q')||'';q.value=initial;run()}).catch(e=>status.textContent=`索引或分类树加载失败：${e}`);q.addEventListener('input',run)})();""",
        "_local/mirror.js": """(()=>{const term=new URLSearchParams(location.search).get('local_search');if(!term)return;const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT,{acceptNode:n=>n.parentElement&& !/^(SCRIPT|STYLE|MARK)$/.test(n.parentElement.tagName)&&n.data.toLocaleLowerCase().includes(term.toLocaleLowerCase())?NodeFilter.FILTER_ACCEPT:NodeFilter.FILTER_REJECT});const node=walker.nextNode();if(!node)return;const i=node.data.toLocaleLowerCase().indexOf(term.toLocaleLowerCase()),mark=document.createElement('mark');mark.textContent=node.data.slice(i,i+term.length);node.parentNode.insertBefore(document.createTextNode(node.data.slice(0,i)),node);node.parentNode.insertBefore(mark,node);node.data=node.data.slice(i+term.length);mark.scrollIntoView({block:'center'})})();""",
    }


def inject_local_tools(document, web_prefix):
    script = f'<script defer src="{web_prefix}_local/mirror.js"></script>'
    if re.search(r"</head\s*>", document, re.I): document = re.sub(r"</head\s*>", script + "</head>", document, count=1, flags=re.I)
    else: document = script + document
    button = f'<a href="{web_prefix}_local/search/" style="position:fixed;right:12px;bottom:12px;z-index:2147483647;padding:8px 12px;background:#111827;color:white;border-radius:6px;text-decoration:none;font:14px sans-serif">🔍 Local Search</a>'
    if re.search(r"</body\s*>", document, re.I): return re.sub(r"</body\s*>", button + "</body>", document, count=1, flags=re.I)
    return document + button


def rewrite_i18n_runtime_paths(script, web_prefix):
    return re.sub(r"(?P<quote>['\"`])/i18n/", lambda match: match.group("quote") + web_prefix + "i18n/", script)


def copy_i18n_files(i18n_root, output):
    if i18n_root is None or not i18n_root.is_dir(): return 0
    copied = 0
    for source in i18n_root.rglob("*.json"):
        target = output / source.relative_to(i18n_root)
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target); copied += 1
    return copied


def build(season, raw_root, asset_manifest_path, asset_root, output, system_id=None, force=False,
          catalog_path=None, search_index_path=None, system_manifest_path=None,
          supplemental_manifest_path=None, i18n_root=None, game_category_mapping_path=None,
          entity_index_path=None, search_entity_report_path=None,
          game_content_tree_path=None, content_tree_report_path=None,
          search_entity_v2_report_path=None):
    started = time.monotonic(); warnings = []; errors = []
    catalog_path = catalog_path or output.parent / "catalog.json"
    search_index_path = search_index_path or output.parent / "search-index.json"
    catalog = load_json(catalog_path); old_search = load_json(search_index_path)
    known_missing = []
    translations = load_native_i18n(i18n_root)
    game_categories = load_game_category_mapping(game_category_mapping_path)
    content_tree = load_game_content_tree(game_content_tree_path)
    entities = load_entity_index(entity_index_path)
    if system_manifest_path is not None:
        catalog_pages, systems_included, known_missing = pages_from_system_manifest(
            system_manifest_path, system_id, translations
        )
        supplemental_pages = pages_from_supplemental_manifest(
            supplemental_manifest_path, system_id, translations
        )
        catalog_pages.extend(supplemental_pages)
    else:
        catalog_pages = [p for p in catalog.get("pages", []) if not system_id or p["system_id"] == system_id]
        systems_included = sorted({page["system_id"] for page in catalog_pages})
    search_by_key = {(p["system_id"], p["id"]): p for p in old_search.get("pages", [])}
    asset_manifest = load_json(asset_manifest_path); assets = asset_manifest.get("assets", [])
    asset_map = {item["source_url"]: item for item in assets}
    web_prefix = f"/local_wiki/{season}/site/"
    if force and output.exists(): shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    print("=" * 60); print("TLIDB Full Mirror Build"); print(f"Season: {season}"); print(f"Pages: {len(catalog_pages)}"); print(f"Assets: {len(assets)}"); print("=" * 60)
    assets_copied = 0; assets_missing = []; css_rewrites = 0; css_unresolved = Counter(); runtime_examples = []; runtime_asset_count = 0
    resolution_totals = Counter()
    for item in assets:
        source = asset_root / item["local_relative_path"]; target = output / "assets" / item["local_relative_path"]
        if not source.is_file(): assets_missing.append(item["source_url"]); continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if item.get("asset_type") == "stylesheet":
            text = source.read_text(encoding="utf-8", errors="replace"); css = CSSRewriter(asset_map, web_prefix)
            target.write_text(css.rewrite(text, item["source_url"], "assets/" + item["local_relative_path"]), encoding="utf-8")
            css_rewrites += css.rewrites; css_unresolved.update(css.unresolved); resolution_totals.update(css.stats)
        else:
            if item.get("asset_type") == "javascript":
                script = source.read_text(encoding="utf-8", errors="replace"); runtime_asset_count += len(RUNTIME.findall(script))
                for value in runtime_urls(script):
                    if len(runtime_examples) >= 20: break
                    if value: runtime_examples.append({"asset": item["source_url"], "reference": value})
                target.write_text(rewrite_i18n_runtime_paths(script, web_prefix), encoding="utf-8")
            else: shutil.copy2(source, target)
        assets_copied += 1
    i18n_files_copied = copy_i18n_files(i18n_root, output)
    print(f"[Assets] {assets_copied}/{len(assets)}")
    candidates = []; routes = defaultdict(list); known_missing_raw_pages = []; empty_snapshot_skipped = []; available_keys = set()
    for page in catalog_pages:
        source_url = page.get("source_url") or f"https://tlidb.com/cn/{page.get('slug') or page['id']}"
        slug = page.get("slug") or page.get("id"); raw_path = raw_root / page["system_id"] / "raw_html" / f"{quote(slug, safe='-_.')}.html"
        source_key = canonical_page_key(source_url)
        if not raw_path.is_file():
            if source_key in available_keys:
                continue
            known_missing_raw_pages.append({
                "system_id": page["system_id"], "id": page.get("id"),
                "reason": "manifest_entry_without_raw_snapshot",
            })
            continue
        if raw_path.stat().st_size == 0:
            try:
                empty_route = (supplemental_route_for_source(source_url)
                               if page.get("source_type") == "recovered_internal"
                               else route_for_source(source_url))
            except ValueError:
                empty_route = None
            empty_snapshot_skipped.append({
                "system_id": page["system_id"],
                "id": page.get("id"),
                "route": ("/" + empty_route.removesuffix("index.html")
                          if empty_route else None),
                "raw_size": 0,
                "reason": "skipped_empty_snapshot",
            })
            continue
        available_keys.add(source_key)
        try:
            route = (supplemental_route_for_source(source_url)
                     if page.get("source_type") == "recovered_internal" else route_for_source(source_url))
        except ValueError as exc: errors.append(str(exc)); continue
        record = dict(page, source_url=source_url, route=route, raw_path=raw_path)
        candidates.append(record); routes[canonical_page_key(source_url)].append(record)
    route_map = {key: matches[0]["route"] for key, matches in routes.items()}
    duplicate_conflicts = []; canonical_pages = []
    for key, matches in routes.items():
        canonical_pages.append(matches[0])
        if len(matches) > 1:
            hashes = {hashlib.sha256(p["raw_path"].read_bytes()).hexdigest() for p in matches}
            if len(hashes) > 1:
                duplicate_conflicts.append({"route": matches[0]["route"], "sources": [f"{p['system_id']}/{p.get('slug') or p['id']}" for p in matches]})
    totals = Counter({"runtime_http_reference_count": runtime_asset_count}); pages_failed = 0; unresolved_examples = set(); search_pages = []; by_system = defaultdict(list)
    content_classification_sources = Counter()
    for page in canonical_pages: by_system[page["system_id"]].append(page)
    overall = 0
    for sid in sorted(by_system):
        completed = 0
        for page in by_system[sid]:
            try:
                raw = page["raw_path"].read_text(encoding="utf-8")
                skill_page = page["system_id"] in SEARCH_SKILL_SYSTEMS
                inspector = TextInspector(visible_skill_content_only=skill_page); inspector.feed(raw)
                css = CSSRewriter(asset_map, web_prefix); rewriter = HTMLRewriter(page["source_url"], route_map, asset_map, web_prefix, css); rewriter.feed(raw); rewriter.close()
                rendered = inject_local_tools("".join(rewriter.output), web_prefix)
                target = output_path_for_route(output, page["route"])
                target.parent.mkdir(parents=True, exist_ok=True); target.write_text(rendered, encoding="utf-8")
                totals.update(rewriter.stats); totals["inline_css_rewrites"] += css.rewrites
                resolution_totals.update(css.stats)
                for host, count in css.unresolved.items(): totals[f"remote_domain:{host}"] += count
                unresolved_examples.update(rewriter.unresolved_internal); runtime_examples.extend(rewriter.runtime_examples[:20-len(runtime_examples)])
                old = search_by_key.get((page["system_id"], page["id"]), {})
                title = old.get("title") or " ".join(inspector.title.split()) or page.get("title") or page["id"]
                extracted_plain = " ".join(" ".join(inspector.text).split())
                page_entity = entities.get(entity_route_key(page["route"]))
                entity_search_text = (
                    (page_entity or {}).get("entity_type")
                    in ENTITY_CLEAN_SUMMARY_TYPES
                )
                if entity_search_text:
                    plain = (page_entity or {}).get("clean_summary") or extracted_plain
                else:
                    plain = extracted_plain if skill_page else (old.get("plain_text") or extracted_plain)
                game_category = game_categories.get(page["system_id"], {})
                search_document = {"system_id": page["system_id"],
                                     "system_name_zh": page.get("system_name_zh") or page["system_id"],
                                     "game_category": game_category.get("game_category"),
                                     "game_category_name_zh": game_category.get("game_category_name_zh"),
                                     "game_category_visibility": game_category.get("game_category_visibility"),
                                     "id": page["id"], "title": title,
                                     "title_display": search_title_display(title),
                                     "source_type": page.get("source_type", "official_system"),
                                     "source_url": page["source_url"], "route": page["route"].removesuffix("index.html"),
                                     "plain_text": plain, "summary_display": search_summary_display(plain)}
                search_document.update(entity_fields_for_route(page["route"], entities))
                if (page_entity or {}).get("search_system_id"):
                    search_document["system_id"] = page_entity["search_system_id"]
                    search_document["system_name_zh"] = page_entity.get(
                        "content_category_name_zh", "装备相关"
                    )
                if search_document.get("clean_summary"):
                    search_document["summary_display"] = search_document["clean_summary"]
                content_fields, content_source = resolve_content_tree_classification(
                    search_document, entities, content_tree
                )
                search_document.update(content_fields)
                content_classification_sources[content_source] += 1
                search_pages.append(search_document)
                totals["routes_generated"] += 1
                lower = raw.lower()
                totals["tooltip_pages"] += int("data-bs-title" in lower or 'data-bs-toggle="tooltip"' in lower or " title=" in lower)
                totals["collapse_pages"] += int('data-bs-toggle="collapse"' in lower)
                totals["tab_pages"] += int('data-bs-toggle="tab"' in lower)
                totals["dropdown_pages"] += int('data-bs-toggle="dropdown"' in lower)
                totals["datatable_pages"] += int(bool(re.search(r'class=["\'][^"\']*datatable', lower)))
            except Exception as exc:
                pages_failed += 1; errors.append(f"Failed {page['system_id']}/{page.get('slug') or page['id']}: {exc}")
            completed += 1; overall += 1
        print(f"[{sid}] {completed}/{len(by_system[sid])}")
    print(f"Overall pages: {overall}/{len(canonical_pages)}")
    for name, content in local_assets().items():
        target = output / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(content, encoding="utf-8")
    if game_content_tree_path is not None:
        if game_content_tree_path.is_file():
            tree_target = output / "_local/search/game-content-tree.json"
            tree_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(game_content_tree_path, tree_target)
        else:
            warnings.append(f"Game Content Tree config not found: {game_content_tree_path}")
    index_target = output / "cn/index.html"; index_target.parent.mkdir(parents=True, exist_ok=True)
    first_route = canonical_pages[0]["route"].removesuffix("index.html") if canonical_pages else "../_local/search/"
    index_target.write_text(f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=/{web_prefix.strip("/")}/{first_route}"><a href="{web_prefix}_local/search/">Local Search</a>', encoding="utf-8")
    output.joinpath("catalog.json").write_text(json.dumps({"season": season, "page_count": len(search_pages), "pages": [{k:p[k] for k in ("system_id","system_name_zh","source_type","id","title","source_url","route")} for p in search_pages]}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    output.joinpath("search-index.json").write_text(json.dumps({"schema_version": 8, "season": season, "page_count": len(search_pages), "pages": search_pages}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    entity_report = search_entity_integration_report(search_pages, entities)
    if search_entity_report_path is not None:
        search_entity_report_path.parent.mkdir(parents=True, exist_ok=True)
        search_entity_report_path.write_text(json.dumps(entity_report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    entity_v2_report = search_entity_v2_integration_report(search_pages, entities)
    if search_entity_v2_report_path is not None:
        search_entity_v2_report_path.parent.mkdir(parents=True, exist_ok=True)
        search_entity_v2_report_path.write_text(json.dumps(entity_v2_report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    content_tree_report = content_tree_index_integration_report(
        search_pages, content_classification_sources
    )
    if content_tree_report_path is not None:
        content_tree_report_path.parent.mkdir(parents=True, exist_ok=True)
        content_tree_report_path.write_text(json.dumps(content_tree_report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    remaining_domains = Counter(css_unresolved)
    for key, value in totals.items():
        if key.startswith("remote_domain:"): remaining_domains[key.split(":",1)[1]] += value
    if remaining_domains:
        warnings.append(f"{sum(remaining_domains.values())} remote static asset references could not be mapped through the Asset Manifest.")
    if totals["runtime_http_reference_count"]:
        warnings.append(f"{totals['runtime_http_reference_count']} retained runtime HTTP patterns require local offline review; no responses were simulated.")
    report = {"season": season, "system_count": len(systems_included),
              "systems_included": systems_included, "inventory_included": "inventory" in systems_included,
              "supplemental_pages_included": sum(page["source_type"] == "recovered_internal" for page in search_pages),
              "recovered_pages_included": sum(page["source_type"] == "recovered_internal" for page in search_pages),
              "known_missing_pages": len(known_missing), "known_missing_entries": known_missing,
              "known_missing_detail_pages": known_missing,
              "known_missing_raw_pages": known_missing_raw_pages,
              "raw_pages_missing_count": len(known_missing_raw_pages),
              "empty_snapshot_skipped_count": len(empty_snapshot_skipped),
              "empty_snapshot_skipped_examples": empty_snapshot_skipped[:20],
              "raw_pages": len(catalog_pages), "routes_generated": totals["routes_generated"], "pages_failed": pages_failed,
              "assets_expected": len(assets), "assets_copied": assets_copied, "assets_missing": len(assets_missing), "assets_missing_examples": assets_missing[:20],
              "i18n_files_copied": i18n_files_copied,
              "html_asset_rewrites": totals["html_asset_rewrites"], "css_asset_rewrites": css_rewrites,
              "inline_css_rewrites": totals["inline_css_rewrites"], "internal_page_links_rewritten": totals["internal_page_links_rewritten"],
              "internal_page_links_unresolved": totals["internal_page_links_unresolved"], "unresolved_internal_examples": sorted(unresolved_examples)[:20],
              "search_forms_rewritten": totals["search_forms_rewritten"], "duplicate_route_conflicts": duplicate_conflicts,
              "tooltip_pages": totals["tooltip_pages"], "collapse_pages": totals["collapse_pages"], "tab_pages": totals["tab_pages"],
              "dropdown_pages": totals["dropdown_pages"], "datatable_pages": totals["datatable_pages"],
              "runtime_http_reference_count": totals["runtime_http_reference_count"], "runtime_http_examples": runtime_examples,
              "tracking_elements_removed": totals["tracking_elements_removed"],
              "relative_url_resolutions": totals["relative_url_resolutions"] + resolution_totals["relative_url_resolutions"],
              "wrong_directory_join_prevented": totals["wrong_directory_join_prevented"] + resolution_totals["wrong_directory_join_prevented"],
              "remaining_remote_asset_references": sum(remaining_domains.values()), "remaining_remote_domains": dict(remaining_domains),
              "elapsed": round(time.monotonic()-started,3), "warnings": warnings, "errors": errors}
    if duplicate_conflicts: report["warnings"].append(f"{len(duplicate_conflicts)} duplicate canonical routes had differing Raw HTML; first source order retained.")
    output.joinpath("mirror-build-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"Finished: Pages: {report['routes_generated']} Failed: {pages_failed} Assets: {assets_copied} Elapsed: {report['elapsed']}s")
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Build the offline TLIDB SS13 Full Mirror from Raw HTML and Raw Assets")
    parser.add_argument("--season", default="ss13"); parser.add_argument("--raw-root", type=Path, default=Path("data/raw/manifests"))
    parser.add_argument("--asset-manifest", type=Path, default=Path("data/raw/assets/ss13/asset-manifest.json"))
    parser.add_argument("--asset-root", type=Path, default=Path("data/raw/assets/ss13/files")); parser.add_argument("--output", type=Path, default=Path("local_wiki/ss13/site"))
    parser.add_argument("--system-manifest", type=Path, default=Path("sources/system_manifest.json"))
    parser.add_argument("--supplemental-manifest", type=Path,
                        default=Path("sources/recovered_internal_pages_manifest.json"))
    parser.add_argument("--i18n-root", type=Path, default=Path("data/raw/i18n/ss13/files"))
    parser.add_argument("--game-category-mapping", type=Path,
                        default=Path("config/game_category_mapping.json"))
    parser.add_argument("--entity-index", type=Path, default=Path("data/generated/entity-index-v3.json"))
    parser.add_argument("--search-entity-report", type=Path,
                        default=Path("data/reports/local-wiki/search-entity-integration-report.json"))
    parser.add_argument("--game-content-tree", type=Path,
                        default=Path("config/game_content_tree.json"))
    parser.add_argument("--content-tree-report", type=Path,
                        default=Path("data/reports/local-wiki/content-tree-index-integration-report.json"))
    parser.add_argument("--search-entity-v2-report", type=Path,
                        default=Path("data/reports/local-wiki/search-entity-v2-integration-report.json"))
    parser.add_argument("--system-id"); parser.add_argument("--force", action="store_true"); return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        report = build(args.season, resolve(args.raw_root), resolve(args.asset_manifest), resolve(args.asset_root), resolve(args.output), args.system_id, args.force,
                       system_manifest_path=resolve(args.system_manifest),
                       supplemental_manifest_path=resolve(args.supplemental_manifest),
                       i18n_root=resolve(args.i18n_root),
                       game_category_mapping_path=resolve(args.game_category_mapping),
                       entity_index_path=resolve(args.entity_index),
                       search_entity_report_path=resolve(args.search_entity_report),
                       game_content_tree_path=resolve(args.game_content_tree),
                       content_tree_report_path=resolve(args.content_tree_report),
                       search_entity_v2_report_path=resolve(args.search_entity_v2_report))
        return 1 if report["errors"] else 0
    except Exception as exc:
        print(f"Full Mirror build failed: {exc}", file=sys.stderr); return 1


if __name__ == "__main__": raise SystemExit(main())
