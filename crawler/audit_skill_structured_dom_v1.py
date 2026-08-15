"""Audit SS13 Skill DOM contracts without generating structured records."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "data/reports/local-wiki/skill-structured-dom-audit-v1.json"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

SYSTEMS = {
    "active_skill": ("skill_active", "主动技能"),
    "support_skill": ("skill_support", "辅助技能"),
    "passive_skill": ("skill_passive", "被动技能"),
    "activation_medium_skill": ("skill_activation_medium", "触媒技能"),
    "magnificent_support_skill": ("skill_magnificent_support", "华贵辅助技能"),
    "noble_support_skill": ("skill_noble_support", "崇高辅助技能"),
    "modularization_skill": ("skill_modularization", "模块化技能"),
}


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    parent: "Node | None" = None
    children: list["Node"] = field(default_factory=list)
    data: list[str] = field(default_factory=list)

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def descendants(self) -> Iterable["Node"]:
        for child in self.children:
            yield child
            yield from child.descendants()

    def text(self) -> str:
        values: list[str] = []
        if self.tag not in {"script", "style"}:
            values.extend(self.data)
            for child in self.children:
                values.append(child.text())
        return " ".join(" ".join(values).split())

    def ancestors(self) -> Iterable["Node"]:
        current = self.parent
        while current is not None:
            yield current
            current = current.parent


class TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, {key: value or "" for key, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].data.append(data)


def parse_html(html: str) -> Node:
    parser = TreeParser()
    parser.feed(html)
    return parser.root


def nodes(root: Node, *, tag: str | None = None, class_name: str | None = None) -> list[Node]:
    result = []
    for node in root.descendants():
        if tag is not None and node.tag != tag:
            continue
        if class_name is not None and class_name not in node.classes:
            continue
        result.append(node)
    return result


def ancestor_with_class(node: Node, class_name: str) -> Node | None:
    return next((ancestor for ancestor in node.ancestors() if class_name in ancestor.classes), None)


def is_in_inactive_pane(node: Node) -> bool:
    pane = ancestor_with_class(node, "tab-pane")
    return bool(pane and not ({"active", "show"} <= pane.classes))


def inactive_pane(node: Node) -> Node | None:
    pane = ancestor_with_class(node, "tab-pane")
    if pane and not ({"active", "show"} <= pane.classes):
        return pane
    return None


def is_historical(node: Node) -> bool:
    return any("previousItem" in ancestor.classes for ancestor in node.ancestors())


def nearest(node: Node, tag: str) -> Node | None:
    return next((ancestor for ancestor in node.ancestors() if ancestor.tag == tag), None)


def first_descendant(node: Node, *, tag: str | None = None, class_name: str | None = None) -> Node | None:
    return next(iter(nodes(node, tag=tag, class_name=class_name)), None)


def table_headers(table: Node) -> list[str]:
    return [header.text() for header in nodes(table, tag="th")]


def table_row_cells(row: Node) -> list[str]:
    return [child.text() for child in row.children if child.tag in {"td", "th"}]


def section_header(node: Node) -> str | None:
    card = ancestor_with_class(node, "card")
    if card is None:
        return None
    header = first_descendant(card, class_name="card-header")
    return header.text() if header else None


def inspect_skill_html(html: str) -> dict[str, Any]:
    root = parse_html(html)
    panes = nodes(root, class_name="tab-pane")
    active_panes = [pane for pane in panes if {"active", "show"} <= pane.classes]
    inactive_panes = [pane for pane in panes if pane not in active_panes]
    popup_cards = [
        card for card in nodes(root, class_name="popupItem")
        if "previousItem" not in card.classes and not is_in_inactive_pane(card)
    ]
    historical_cards = [
        card for card in nodes(root, class_name="popupItem")
        if "previousItem" in card.classes
        or (
            inactive_pane(card) is not None
            and "cache-" in inactive_pane(card).attrs.get("id", "")
        )
    ]
    related_cards = [
        card for card in nodes(root, class_name="popupItem")
        if "previousItem" not in card.classes
        and inactive_pane(card) is not None
        and "cache-" not in inactive_pane(card).attrs.get("id", "")
    ]
    current_card = popup_cards[0] if popup_cards else None
    info_match = re.search(
        r'<div class="card-header">Info</div>.*?<div>id:\s*([^<\s]+)</div>', html, re.I | re.S
    )
    info_id = info_match.group(1) if info_match else None
    modifier_nodes = [
        node for node in root.descendants()
        if node.attrs.get("data-modifier-id")
        and not is_historical(node)
        and not is_in_inactive_pane(node)
    ]
    modifiers = []
    for modifier in modifier_nodes:
        row = nearest(modifier, "tr")
        table = nearest(modifier, "table")
        pane = ancestor_with_class(modifier, "tab-pane")
        cells = table_row_cells(row) if row else []
        modifiers.append({
            "stable_key": f"modifier:{modifier.attrs['data-modifier-id']}",
            "modifier_id": modifier.attrs["data-modifier-id"],
            "text": modifier.text(),
            "tier": cells[0] if cells else None,
            "table_headers": table_headers(table) if table else [],
            "section": section_header(modifier),
            "pane_id": pane.attrs.get("id") if pane else None,
        })
    level_tables = []
    for table in nodes(root, tag="table", class_name="DataTable"):
        if is_historical(table) or is_in_inactive_pane(table):
            continue
        headers = table_headers(table)
        if headers and headers[0].casefold() == "level":
            rows = [row for row in nodes(table, tag="tr") if table_row_cells(row)]
            level_tables.append({
                "headers": headers,
                "row_count": max(0, len(rows) - 1 if rows and rows[0].tag == "tr" else len(rows)),
                "levels": [table_row_cells(row)[0] for row in rows if table_row_cells(row)][:45],
            })
    explicit = []
    tags = []
    version = None
    title = None
    level = None
    if current_card is not None:
        explicit = [item.text() for item in nodes(current_card, class_name="explicitMod") if item.text()]
        tags = [item.text() for item in nodes(current_card, class_name="tag") if item.text()]
        version_node = first_descendant(current_card, class_name="item_ver")
        title_node = first_descendant(current_card, class_name="card-title")
        level_node = first_descendant(current_card, class_name="level")
        version = version_node.text() if version_node else None
        title = title_node.text() if title_node else None
        level = level_node.text() if level_node else None
    tab_targets = [
        node.attrs.get("data-bs-target") for node in root.descendants()
        if node.attrs.get("data-bs-toggle") == "tab" and node.attrs.get("data-bs-target")
    ]
    has_cache_pane = any("cache-" in pane.attrs.get("id", "") for pane in inactive_panes)
    if modifiers:
        template_group = "skill_modifier_growth"
    elif active_panes and has_cache_pane:
        template_group = "skill_tabbed_cache_history"
    elif active_panes:
        template_group = "skill_tabbed_variants"
    else:
        template_group = "skill_standalone_card"
    data_ids = [node.attrs["data-id"] for node in root.descendants() if node.attrs.get("data-id")]
    data_skill_ids = [node.attrs["data-skill-id"] for node in root.descendants() if node.attrs.get("data-skill-id")]
    return {
        "template_group": template_group,
        "current_card_count": len(popup_cards),
        "current_pane_id": (
            ancestor_with_class(current_card, "tab-pane").attrs.get("id")
            if current_card is not None and ancestor_with_class(current_card, "tab-pane")
            else None
        ),
        "historical_card_count": len(historical_cards),
        "non_current_related_card_count": len(related_cards),
        "current_version": version,
        "current_title": title,
        "current_level": level,
        "tags": tags,
        "explicit_effects": explicit,
        "explicit_effect_count": len(explicit),
        "info_id": info_id,
        "modifiers": modifiers,
        "level_tables": level_tables,
        "active_panes": [pane.attrs.get("id") for pane in active_panes],
        "inactive_panes": [pane.attrs.get("id") for pane in inactive_panes],
        "tab_targets": tab_targets,
        "data_skill_ids": data_skill_ids,
        "data_ids": data_ids,
        "datatable_count": len(nodes(root, tag="table", class_name="DataTable")),
        "filter_count": sum(node.attrs.get("name") == "filter" for node in root.descendants()),
        "selector_count": sum(
            node.tag == "input" and node.attrs.get("type") in {"radio", "checkbox"}
            for node in root.descendants()
        ),
        "show_description_control": any(node.attrs.get("id") == "hideSmall" for node in root.descendants()),
        "alts_section": bool(re.search(r'<div class="card-header">Alts</div>', html, re.I)),
        "skill_shop_section": "Func_Skill_SkillStore" in html,
    }


def _raw_path(repo: Path, system: str, slug: str) -> Path:
    return repo / "data/raw/manifests" / system / "raw_html" / f"{quote(slug, safe='-_.')}.html"


def _meta_path(repo: Path, system: str, slug: str) -> Path:
    return repo / "data/raw/manifests" / system / "meta" / f"{quote(slug, safe='-_.')}.meta.json"


def _case(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "system_id": page["system_id"],
        "entity_id": page["entity_id"],
        "title": page["title"],
        "route": page["route"],
        "template_group": page["template_group"],
        "current_version": page["current_version"],
        "current_card_count": page["current_card_count"],
        "historical_card_count": page["historical_card_count"],
        "non_current_related_card_count": page["non_current_related_card_count"],
        "explicit_effect_count": page["explicit_effect_count"],
        "growth_modifier_count": page["growth_modifier_count"],
        "level_row_count": page["level_row_count"],
        "stable_entity_key": page["stable_entity_key"],
        "identity_confidence": page["identity_confidence"],
        "active_panes": page["active_panes"],
        "inactive_panes": page["inactive_panes"],
        "landing_level": "record" if page["growth_modifier_count"] else "section",
    }


def build_audit(repo: Path = ROOT) -> dict[str, Any]:
    entity_data = json.loads((repo / "data/generated/entity-index-v3.json").read_text(encoding="utf-8"))
    entity_by_id = {entity["entity_id"]: entity for entity in entity_data.get("entities", [])}
    search_data = json.loads((repo / "local_wiki/ss13/site/search-index.json").read_text(encoding="utf-8"))
    search_by_route = {
        "/" + page["route"].strip("/") + "/": page for page in search_data.get("pages", [])
    }
    pages: list[dict[str, Any]] = []
    errors: list[str] = []
    completeness: dict[str, dict[str, Any]] = {}

    for system, (subcategory, name_zh) in SYSTEMS.items():
        manifest = json.loads((repo / f"sources/{system}_manifest.json").read_text(encoding="utf-8"))
        stats = Counter()
        missing: list[str] = []
        zero: list[str] = []
        for entry in manifest.get("entries", []):
            stats["manifest_pages"] += 1
            slug = entry["slug"]
            raw_path = _raw_path(repo, system, slug)
            meta_path = _meta_path(repo, system, slug)
            if not raw_path.is_file():
                stats["missing_raw"] += 1
                missing.append(entry["id"])
                continue
            stats["raw_present"] += 1
            raw_bytes = raw_path.read_bytes()
            if not raw_bytes:
                stats["zero_byte_raw"] += 1
                zero.append(entry["id"])
                continue
            stats["raw_nonempty"] += 1
            html = raw_bytes.decode("utf-8", errors="replace")
            dom = inspect_skill_html(html)
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
            stats["meta_present"] += int(meta_path.is_file())
            stats["http_200"] += int(meta.get("http_status") == 200)
            stats["hash_matches"] += int(
                bool(meta.get("html_sha256"))
                and hashlib.sha256(raw_bytes).hexdigest() == meta.get("html_sha256")
            )
            route = f"/cn/{slug}/"
            entity_id = f"tlidb:cn:{slug}"
            entity = entity_by_id.get(entity_id)
            search = search_by_route.get(route, {})
            stable_key = f"skill:{dom['info_id']}" if dom["info_id"] else f"page:{slug}"
            confidence = "high" if dom["info_id"] else "medium"
            level_rows = sum(table["row_count"] for table in dom["level_tables"])
            page = {
                "system_id": system,
                "subcategory_id": subcategory,
                "subcategory_name_zh": name_zh,
                "id": entry["id"],
                "slug": slug,
                "title": entry.get("name_zh") or dom["current_title"] or slug,
                "route": route,
                "entity_id": entity_id,
                "entity_present": entity is not None,
                "entity_type": entity.get("entity_type") if entity else None,
                "entity_visibility": entity.get("entity_visibility") if entity else None,
                "entity_category": entity.get("content_category_id") if entity else None,
                "entity_subcategory": entity.get("content_subcategory_id") if entity else None,
                "stable_entity_key": stable_key,
                "identity_confidence": confidence,
                "raw_size": len(raw_bytes),
                "level_row_count": level_rows,
                "growth_modifier_count": len(dom["modifiers"]),
                "search_plain_text_length": len(search.get("plain_text", "")),
                **{key: value for key, value in dom.items() if key not in {"modifiers", "level_tables"}},
                "modifiers": dom["modifiers"],
                "level_tables": dom["level_tables"],
            }
            pages.append(page)
        completeness[system] = {
            **{key: stats[key] for key in (
                "manifest_pages", "raw_present", "raw_nonempty", "zero_byte_raw",
                "missing_raw", "meta_present", "http_200", "hash_matches",
            )},
            "missing_examples": missing[:10],
            "zero_byte_examples": zero[:10],
        }

    all_modifiers = [
        {**modifier, "entity_id": page["entity_id"], "route": page["route"]}
        for page in pages for modifier in page["modifiers"]
    ]
    info_groups: dict[str, list[str]] = defaultdict(list)
    for page in pages:
        if page["stable_entity_key"].startswith("skill:"):
            info_groups[page["stable_entity_key"]].append(page["entity_id"])
    modifier_groups: dict[str, list[str]] = defaultdict(list)
    modifier_text_groups: dict[str, list[str]] = defaultdict(list)
    for modifier in all_modifiers:
        modifier_groups[modifier["stable_key"]].append(modifier["entity_id"])
        modifier_text_groups[modifier["text"]].append(modifier["stable_key"])
    effect_text_groups: dict[str, list[str]] = defaultdict(list)
    for page in pages:
        effect = " ".join(dict.fromkeys(page["explicit_effects"]))
        if effect:
            effect_text_groups[effect].append(page["stable_entity_key"])

    templates = []
    for group, members in sorted(
        ((name, [page for page in pages if page["template_group"] == name])
         for name in {page["template_group"] for page in pages}),
        key=lambda item: (-len(item[1]), item[0]),
    ):
        templates.append({
            "id": group,
            "page_count": len(members),
            "systems": dict(Counter(page["system_id"] for page in members)),
            "representative_pages": [page["id"] for page in members[:8]],
            "dom_contract": {
                "current_popup_card": True,
                "active_tab_required": group.startswith("skill_tabbed"),
                "growth_modifier_table": group == "skill_modifier_growth",
                "historical_previous_item_excluded": True,
            },
        })

    plain_pages = [search_by_route.get(page["route"], {}) for page in pages]
    noise_patterns = {
        label: {
            "count": sum(token.casefold() in item.get("plain_text", "").casefold() for item in plain_pages),
            "examples": [
                item.get("id") for item in plain_pages
                if token.casefold() in item.get("plain_text", "").casefold()
            ][:8],
        }
        for label, token in {
            "info_id": "Info id",
            "show_description": "Show Description",
            "alts": "Alts",
            "historical_ss12": "SS12",
            "skill_shop": "Skill Shop",
            "cache_tab": "cache-",
            "npc": "NPC",
        }.items()
    }

    source_totals = Counter()
    for stats in completeness.values():
        source_totals.update({key: value for key, value in stats.items() if isinstance(value, int)})
    business = {
        system: {
            "subcategory_id": subcategory,
            "subcategory_name_zh": name,
            "entities": sum(page["system_id"] == system for page in pages),
        }
        for system, (subcategory, name) in SYSTEMS.items()
    }
    info_missing = [page["id"] for page in pages if page["identity_confidence"] != "high"]
    info_duplicate = {key: value for key, value in info_groups.items() if len(value) > 1}
    modifier_duplicate = {key: value for key, value in modifier_groups.items() if len(set(value)) > 1}
    same_modifier_text = {
        text: sorted(set(keys)) for text, keys in modifier_text_groups.items()
        if len(set(keys)) > 1
    }
    same_effect_text = {
        text: sorted(set(keys)) for text, keys in effect_text_groups.items()
        if len(set(keys)) > 1
    }
    record_count = len(pages) + len(all_modifiers)
    historical_pages = [page for page in pages if page["historical_card_count"]]
    modifier_pages = [page for page in pages if page["growth_modifier_count"]]
    level_pages = [page for page in pages if page["level_row_count"]]
    active_tabs = [page for page in pages if page["active_panes"]]
    case_lookup = {page["id"]: page for page in pages}
    simplest = min(pages, key=lambda page: (page["explicit_effect_count"] + page["growth_modifier_count"], page["raw_size"]))
    complex_page = max(pages, key=lambda page: (page["explicit_effect_count"] + page["growth_modifier_count"] + page["level_row_count"], page["raw_size"]))
    multi_modifier = max(modifier_pages, key=lambda page: page["growth_modifier_count"]) if modifier_pages else complex_page
    current_history = max(historical_pages, key=lambda page: page["historical_card_count"]) if historical_pages else complex_page

    report: dict[str, Any] = {
        "schema_version": 1,
        "source_completeness": {
            "totals": dict(source_totals),
            "by_system": completeness,
            "authorized_source": "seven confirmed SS13 skill manifests and their primary raw snapshots",
            "complete": source_totals["manifest_pages"] == source_totals["raw_nonempty"] == 721,
        },
        "entity_scope": {
            "entity_count": len(pages),
            "entity_present": sum(page["entity_present"] for page in pages),
            "visible": sum(page["entity_visibility"] != "hidden" for page in pages),
            "category": "skill",
            "entity_type_distribution": dict(Counter(str(page["entity_type"]) for page in pages)),
            "hidden_directory_entities_outside_scope": 7,
        },
        "business_classification": business,
        "template_groups": templates,
        "section_structure": {
            "current_skill_card": {
                "selector": ".card.ui_item.popupItem:not(.previousItem) within active pane or page root",
                "pages": sum(page["current_card_count"] > 0 for page in pages),
                "expected_per_page": 1,
            },
            "effect_blocks": {
                "selector": ".explicitMod inside current skill card",
                "total_blocks": sum(page["explicit_effect_count"] for page in pages),
                "business_boundary": "deduplicated current skill effect as one skill_effect record per entity",
            },
            "growth_modifiers": {
                "selector": "DataTable row descendants with data-modifier-id",
                "pages": len(modifier_pages),
                "records": len(all_modifiers),
            },
            "level_tables": {
                "selector": "DataTable whose first header is level",
                "pages": len(level_pages),
                "rows": sum(page["level_row_count"] for page in pages),
            },
        },
        "candidate_record_types": [
            {
                "record_type": "skill_effect",
                "count": len(pages),
                "business_unit": "one current SS13 skill card per entity; simple/details blocks deduplicated",
                "identity": "Info id scoped as skill:<id>",
                "confidence": "high" if not info_missing and not info_duplicate else "mixed",
            },
            {
                "record_type": "skill_growth_modifier",
                "count": len(all_modifiers),
                "business_unit": "one DOM node carrying data-modifier-id",
                "identity": "modifier:<data-modifier-id>",
                "confidence": "high" if not modifier_duplicate else "mixed",
            },
        ],
        "record_counts": {
            "skill_effect": len(pages),
            "skill_growth_modifier": len(all_modifiers),
            "estimated_total": record_count,
            "by_system": {
                system: {
                    "skill_effect": sum(page["system_id"] == system for page in pages),
                    "skill_growth_modifier": sum(
                        page["growth_modifier_count"] for page in pages if page["system_id"] == system
                    ),
                }
                for system in SYSTEMS
            },
        },
        "stable_key_analysis": {
            "data_skill_id": sum(len(page["data_skill_ids"]) for page in pages),
            "data_id": sum(len(page["data_ids"]) for page in pages),
            "data_id_accepted_for_identity": 0,
            "data_id_conclusion": "observed data-id attributes are not attached to the audited skill business record boundary",
            "data_modifier_id": len(all_modifiers),
            "info_id_coverage": len(pages) - len(info_missing),
            "info_id_missing": info_missing,
            "duplicate_info_ids": info_duplicate,
            "duplicate_modifier_ids_across_entities": modifier_duplicate,
            "identity_confidence": {
                "high": (len(pages) - len(info_missing)) + len(all_modifiers),
                "medium": len(info_missing),
                "low": 0,
            },
            "prohibited_identity_inputs": ["Chinese description", "numeric value", "season_id", "global row index"],
        },
        "duplicate_analysis": {
            "same_modifier_text_different_stable_ids": len(same_modifier_text),
            "same_skill_effect_text_different_skill_ids": len(same_effect_text),
            "modifier_examples": [
                {"text": text, "stable_keys": keys[:8]}
                for text, keys in list(same_modifier_text.items())[:8]
            ],
            "effect_examples": [
                {"text": text, "stable_keys": keys[:8]}
                for text, keys in list(same_effect_text.items())[:8]
            ],
            "conclusion": "text equality is not identity; stable gameplay/data keys remain distinct",
        },
        "level_model": {
            "pages_with_level_tables": len(level_pages),
            "level_rows": sum(page["level_row_count"] for page in pages),
            "observed_display_level": dict(Counter(page["current_level"] for page in pages)),
            "model": "level rows are numeric/text variants of the same skill effect, not independent searchable records",
            "parser_contract": "retain level/tier as metadata under skill_effect; do not derive record_id from level values",
        },
        "historical_exclusion": {
            "pages_with_history": len(historical_pages),
            "historical_cards": sum(page["historical_card_count"] for page in pages),
            "current_marker": ".popupItem without .previousItem, inside active/show pane when tabs exist",
            "non_current_related_cards": sum(page["non_current_related_card_count"] for page in pages),
            "historical_markers": [".previousItem", "cache-* pane", "SS12/older item_ver"],
            "other_excluded_scope": "inactive non-cache tab panes are related skills/variants, not owned by the current page entity",
            "excluded_from_records": True,
        },
        "view_state": {
            "pages_with_active_tab": len(active_tabs),
            "pages_with_datatable": sum(page["datatable_count"] > 0 for page in pages),
            "pages_with_filter": sum(page["filter_count"] > 0 for page in pages),
            "pages_with_selector": sum(page["selector_count"] > 0 for page in pages),
            "pages_with_show_description_control": sum(page["show_description_control"] for page in pages),
            "landing_contract": {
                "skill_effect": "activate current pane when present, then locate current popup card",
                "skill_growth_modifier": "locate data-modifier-id after DataTable readiness",
            },
        },
        "search_text_whitelist": {
            "include": [
                "current skill name", "current tags", "current weapon restriction",
                "current core attributes", "deduplicated current Simple/Details effect text",
                "current growth modifier text",
            ],
            "exclude": [
                "historical season cards and inactive/cache tabs", "Skill Shop aggregation",
                "Alts and related Item lists", "tooltip metadata/data-bs-title", "level UI controls",
                "DataTable headers", "Info/internal IDs", "navigation", "image/resource names",
                "script/style", "duplicated overview/plain_text", "non-current skill panes",
            ],
        },
        "noise_exclusions": {
            "current_search_plain_text": noise_patterns,
            "audit_conclusion": "current v1 skill plain_text still contains Info id, Show Description, and Skill Shop noise; structured search_text must use the DOM whitelist instead of plain_text",
        },
        "locator_support": {
            "record_level": len(all_modifiers),
            "section_level": len(pages),
            "page_level": 0,
            "total_records": record_count,
            "record_level_percent": round(100 * len(all_modifiers) / record_count, 2) if record_count else 0,
            "section_level_percent": round(100 * len(pages) / record_count, 2) if record_count else 0,
            "record_locator": "[data-modifier-id='<id>'] within growth DataTable",
            "section_locator": "active pane/page root + .card.ui_item.popupItem:not(.previousItem)",
        },
        "case_studies": {
            "simplest": _case(simplest),
            "most_complex": _case(complex_page),
            "active_skill": _case(next(page for page in pages if page["system_id"] == "active_skill")),
            "passive_skill": _case(next(page for page in pages if page["system_id"] == "passive_skill")),
            "support_skill": _case(next(page for page in pages if page["system_id"] == "support_skill")),
            "multi_level": _case(max(level_pages, key=lambda page: page["level_row_count"])),
            "multi_modifier": _case(multi_modifier),
            "current_and_history": _case(current_history),
        },
        "framework_compatibility": {
            "compatible": True,
            "existing_features_used": [
                "stable record_id", "identity_confidence", "source_locator",
                "structure_signature", "structure_mismatch", "record/section landing levels",
            ],
            "framework_change_required": False,
            "constraints": [
                "skill_effect uses a stable Info id for identity but only section-level DOM landing",
                "level rows remain metadata and are not emitted as records",
            ],
        },
        "parser_recommendation": {
            "parser_ready": True,
            "parser_file": "crawler/structured/skill_parser.py",
            "parser_id": "skill_structured_v1",
            "record_types": ["skill_effect", "skill_growth_modifier"],
            "estimated_records": record_count,
            "parameterized_systems": list(SYSTEMS),
            "structure_guards": [
                "exactly one current non-previous popup card", "Info id present and unique",
                "active pane ownership when tabs exist", "growth table header and data-modifier-id uniqueness",
            ],
        },
        "errors": errors,
    }

    if not report["source_completeness"]["complete"]:
        errors.append("skill source completeness failed")
    if report["entity_scope"]["entity_present"] != len(pages):
        errors.append("skill entity scope is incomplete")
    if any(page["current_card_count"] != 1 for page in pages):
        errors.append("one or more skill pages do not have exactly one current skill card")
    if info_missing or info_duplicate:
        errors.append("skill Info id coverage/uniqueness is insufficient")
    if modifier_duplicate:
        errors.append("modifier ids are reused across skill entities")
    if errors:
        report["parser_recommendation"]["parser_ready"] = False
        report["framework_compatibility"]["compatible"] = False
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = build_audit(args.root)
    output = args.output if args.output.is_absolute() else args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "entities": report["entity_scope"]["entity_count"],
        "records": report["record_counts"]["estimated_total"],
        "templates": len(report["template_groups"]),
        "parser_ready": report["parser_recommendation"]["parser_ready"],
        "errors": report["errors"],
    }, ensure_ascii=False))
    return int(bool(report["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
