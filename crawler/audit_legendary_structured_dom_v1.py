"""Audit Legendary Equipment DOM contracts for a future structured parser."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote

from crawler.recover_legendary_refetch_v1 import NON_EQUIPMENT_IDS


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "data/reports/local-wiki/legendary-structured-dom-audit-v1.json"
VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


class LegendaryDOMInspector(HTMLParser):
    """Collect structural evidence without extracting a production record model."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, Any]] = []
        self.cards: list[dict[str, Any]] = []
        self.headings: list[str] = []
        self.capture: dict[str, Any] | None = None

    def _card(self) -> dict[str, Any] | None:
        return next((frame.get("card") for frame in reversed(self.stack) if frame.get("card")), None)

    def _in_tier_parent(self) -> bool:
        return any(frame.get("tier_parent") for frame in self.stack)

    def _start_capture(self, kind: str, frame: dict[str, Any], **extra: Any) -> None:
        if self.capture is None:
            self.capture = {"kind": kind, "frame": frame, "parts": [], **extra}
            frame["starts_capture"] = True

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs_list)
        classes = set((attrs.get("class") or "").split())
        card = self._card()
        if tag == "div" and "card" in classes:
            kind = "other"
            if "popupItem" in classes:
                kind = "historical" if "previousItem" in classes else "current"
            card = {
                "kind": kind,
                "classes": sorted(classes),
                "versions": [],
                "titles": [],
                "requirements": [],
                "images": [],
                "modifiers": [],
                "lore": [],
            }
            self.cards.append(card)
        i18n = attrs.get("data-i18n") or ""
        if card and "hyperlink|name|30001" in i18n:
            card["kind"] = "corrosion"
            card["section_key"] = "hyperlink|name|30001"
        if card and "Func_Tips_DropSource" in i18n:
            card["kind"] = "drop_source"
            card["section_key"] = "TextTable_GameFunc|value|Func_Tips_DropSource"
        frame = {
            "tag": tag,
            "card": card,
            "tier_parent": "tierParent" in classes,
            "starts_capture": False,
        }
        if tag not in VOID_ELEMENTS:
            self.stack.append(frame)
        if tag == "h1":
            self._start_capture("heading", frame)
        elif card and "item_ver" in classes:
            self._start_capture("version", frame, card=card)
        elif card and tag == "h5" and "card-title" in classes:
            self._start_capture("title", frame, card=card)
        elif card and tag == "span" and {"tag", "tlborder"} <= classes:
            self._start_capture("requirement", frame, card=card)
        elif card and tag == "img":
            card["images"].append(attrs.get("src"))
        elif card and attrs.get("data-modifier-id"):
            self._start_capture(
                "modifier", frame, card=card, stable_key=attrs["data-modifier-id"],
                in_tier_parent=self._in_tier_parent(),
            )
        elif card and "fst-italic" in classes:
            self._start_capture("lore", frame, card=card)

    def handle_data(self, data: str) -> None:
        if self.capture is not None:
            self.capture["parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] != tag:
                continue
            removed = self.stack[index:]
            del self.stack[index:]
            if self.capture and any(frame is self.capture["frame"] for frame in removed):
                value = " ".join(" ".join(self.capture["parts"]).split())
                kind = self.capture["kind"]
                card = self.capture.get("card")
                if value:
                    if kind == "heading":
                        self.headings.append(value)
                    elif kind == "version":
                        card["versions"].append(value)
                    elif kind == "title":
                        card["titles"].append(value)
                    elif kind == "requirement":
                        card["requirements"].append(value)
                    elif kind == "lore":
                        card["lore"].append(value)
                    elif kind == "modifier":
                        card["modifiers"].append({
                            "stable_key": self.capture["stable_key"],
                            "text": value,
                            "in_tier_parent": self.capture["in_tier_parent"],
                        })
                self.capture = None
            break


def inspect_html(html: str) -> dict[str, Any]:
    parser = LegendaryDOMInspector()
    parser.feed(html)
    cards_by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for card in parser.cards:
        cards_by_kind[card["kind"]].append(card)
    current = cards_by_kind["current"]
    historical = cards_by_kind["historical"]
    corrosion = cards_by_kind["corrosion"]
    drop = cards_by_kind["drop_source"]
    current_modifiers = [modifier for card in current for modifier in card["modifiers"]]
    corrosion_modifiers = [modifier for card in corrosion for modifier in card["modifiers"]]
    base_stats = [modifier for modifier in current_modifiers if not modifier["in_tier_parent"]]
    affixes = [modifier for modifier in current_modifiers if modifier["in_tier_parent"]]
    return {
        "headings": parser.headings,
        "current_card_count": len(current),
        "historical_card_count": len(historical),
        "corrosion_card_count": len(corrosion),
        "drop_source_card_count": len(drop),
        "current_versions": [version for card in current for version in card["versions"]],
        "historical_versions": [version for card in historical for version in card["versions"]],
        "title_count": sum(len(card["titles"]) for card in current),
        "image_count": sum(len(card["images"]) for card in current),
        "requirement_count": sum(len(card["requirements"]) for card in current),
        "base_stat_count": len(base_stats),
        "legendary_affix_count": len(affixes),
        "corrosion_effect_count": len(corrosion_modifiers),
        "historical_modifier_count": sum(len(card["modifiers"]) for card in historical),
        "current_stable_key_count": sum(bool(item["stable_key"]) for item in current_modifiers),
        "corrosion_stable_key_count": sum(bool(item["stable_key"]) for item in corrosion_modifiers),
        "lore_count": sum(len(card["lore"]) for card in current + historical),
        "base_stat_examples": base_stats[:2],
        "legendary_affix_examples": affixes[:3],
        "corrosion_effect_examples": corrosion_modifiers[:3],
        "lore_examples": [text for card in current for text in card["lore"]][:1],
    }


def _template_group(evidence: dict[str, Any]) -> str:
    if evidence["current_card_count"] > 1:
        return "multi_variant_current_and_history"
    if evidence["drop_source_card_count"] == 0:
        return "current_history_without_drop_source"
    if evidence["historical_card_count"] == 0:
        return "current_only_with_corrosion"
    return "standard_current_history_corrosion_drop"


def build_audit(repo: Path = ROOT) -> dict[str, Any]:
    manifest = json.loads((repo / "sources/legendary_gear_manifest.json").read_text(encoding="utf-8"))
    raw_root = repo / "data/raw/manifests/legendary_gear/raw_html"
    pages: list[dict[str, Any]] = []
    errors: list[str] = []
    for entry in manifest.get("entries", []):
        if entry["id"] in NON_EQUIPMENT_IDS:
            continue
        raw_path = raw_root / f"{quote(entry['slug'], safe='-_.')}.html"
        if not raw_path.is_file() or not raw_path.stat().st_size:
            errors.append(f"missing or empty raw: {entry['id']}")
            continue
        evidence = inspect_html(raw_path.read_text(encoding="utf-8", errors="replace"))
        pages.append({
            "id": entry["id"],
            "title": entry.get("name_zh") or entry["id"],
            "route": f"/cn/{entry['slug']}/",
            "template_group": _template_group(evidence),
            **evidence,
        })

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for page in pages:
        grouped[page["template_group"]].append(page)
    template_groups = []
    for group_id, members in sorted(grouped.items()):
        template_groups.append({
            "id": group_id,
            "page_count": len(members),
            "example_pages": [page["id"] for page in members[:5]],
            "current_season_selector": ".card.ui_item.popupItem:not(.previousItem)",
            "record_selector": "[data-modifier-id] scoped to current/corrosion card",
            "historical_selector": ".card.ui_item.popupItem.previousItem",
        })

    by_id = {page["id"]: page for page in pages}
    single = min(
        (page for page in pages if page["legendary_affix_count"] > 0),
        key=lambda page: page["legendary_affix_count"],
    )
    multiple = max(pages, key=lambda page: page["legendary_affix_count"])
    history = next(page for page in pages if page["historical_card_count"])
    corruption = next(page for page in pages if page["corrosion_effect_count"])
    case_ids = {
        "necklace_of_firebird": "Necklace_of_Firebird",
        "single_legendary_effect": single["id"],
        "multiple_legendary_effects": multiple["id"],
        "ss13_and_history": history["id"],
        "corrosion": corruption["id"],
    }
    case_studies = {key: by_id[page_id] for key, page_id in case_ids.items()}

    current_modifier_total = sum(
        page["base_stat_count"] + page["legendary_affix_count"] for page in pages
    )
    corrosion_modifier_total = sum(page["corrosion_effect_count"] for page in pages)
    current_detection_misses = [page["id"] for page in pages if not page["current_card_count"]]
    non_ss13_current = [
        page["id"] for page in pages
        if not page["current_versions"] or any("SS13" not in value for value in page["current_versions"])
    ]
    historical_pages = [page for page in pages if page["historical_card_count"]]
    if len(pages) != 332:
        errors.append(f"expected 332 audited pages, got {len(pages)}")
    if sum(group["page_count"] for group in template_groups) != len(pages):
        errors.append("template groups do not cover every audited page")
    if current_detection_misses:
        errors.append(f"current-season detection misses: {len(current_detection_misses)}")

    return {
        "schema_version": 1,
        "legendary_pages": len(pages),
        "excluded_non_equipment_pages": sorted(NON_EQUIPMENT_IDS),
        "template_groups": template_groups,
        "current_season_detection": {
            "primary_selector": ".card.ui_item.popupItem:not(.previousItem)",
            "supporting_contract": ".item_ver within the selected card identifies SS13",
            "detected_pages": len(pages) - len(current_detection_misses),
            "missed_pages": current_detection_misses,
            "non_ss13_current_labels": non_ss13_current,
            "reason": "Current cards omit the previousItem class; season text is corroboration, not the primary selector.",
        },
        "historical_season_detection": {
            "selector": ".card.ui_item.popupItem.previousItem",
            "pages_with_history": len(historical_pages),
            "historical_card_count": sum(page["historical_card_count"] for page in pages),
            "historical_modifier_count": sum(page["historical_modifier_count"] for page in pages),
            "exclusion_rule": "Exclude the complete previousItem card before extracting any modifier records.",
        },
        "data_regions": {
            "equipment_name": "h1 plus h5.card-title inside current card",
            "image_and_base_card": "img inside current .popupItem (display metadata; not a search record)",
            "requirement_level": "span.tag.tlborder inside current card (display metadata; exclude from search)",
            "base_attributes": "current-card [data-modifier-id] outside .tierParent",
            "legendary_affixes": "current-card .tierParent [data-modifier-id]",
            "corrosion": "card identified by header data-i18n=hyperlink|name|30001",
            "drop_source": "card identified by data-i18n=TextTable_GameFunc|value|Func_Tips_DropSource",
            "lore": ".fst-italic inside item cards",
            "history": ".popupItem.previousItem",
        },
        "candidate_record_types": [
            {
                "record_type": "legendary_base_stat",
                "selector": ".popupItem:not(.previousItem) [data-modifier-id] outside .tierParent",
                "locator_level": "record",
                "record_count": sum(page["base_stat_count"] for page in pages),
                "recommendation": "include",
            },
            {
                "record_type": "legendary_affix",
                "selector": ".popupItem:not(.previousItem) .tierParent [data-modifier-id]",
                "locator_level": "record",
                "record_count": sum(page["legendary_affix_count"] for page in pages),
                "recommendation": "include; DOM does not justify splitting generic affix versus effect further",
            },
            {
                "record_type": "legendary_corruption_effect",
                "selector": "corrosion card [data-modifier-id]",
                "locator_level": "record",
                "record_count": corrosion_modifier_total,
                "recommendation": "include",
            },
        ],
        "locator_support": {
            "record_level": sum(
                bool(page["current_stable_key_count"] or page["corrosion_stable_key_count"])
                for page in pages
            ),
            "section_level": 0,
            "page_level": 0,
            "record_count": current_modifier_total + corrosion_modifier_total,
            "stable_record_count": sum(
                page["current_stable_key_count"] + page["corrosion_stable_key_count"]
                for page in pages
            ),
            "scope_requirement": "Resolve data-modifier-id inside the selected current or corrosion card; IDs can repeat in historical cards.",
        },
        "stable_key_sources": [
            {
                "attribute": "data-modifier-id",
                "applies_to": ["legendary_base_stat", "legendary_affix", "legendary_corruption_effect"],
                "confidence": "high when scoped to current/corrosion container",
            },
            {
                "attribute": "data-i18n=hyperlink|name|30001",
                "applies_to": ["corrosion section container"],
                "confidence": "high section identity",
            },
        ],
        "noise_exclusions": [
            ".popupItem.previousItem and all SS12/older modifiers",
            "requirement level badges",
            ".fst-italic lore",
            "Drop Source card",
            "navigation/footer",
            "images and resource names",
            "UI controls, script and style content",
            "tooltip-only internal metadata and raw IDs as searchable text",
        ],
        "structure_signature_recommendation": {
            "include": [
                "current-card selector/class contract",
                "current-card count",
                "presence and nesting of tierParent modifier lists",
                "data-modifier-id coverage count",
                "corrosion section identity and modifier-list structure",
                "ability to identify and exclude previousItem history",
            ],
            "exclude": ["modifier prose", "numeric rolls", "requirement level", "lore", "image URL"],
        },
        "case_studies": case_studies,
        "parser_recommendation": (
            "Use one parameterized Legendary parser with four DOM template groups, not per-page parsers. "
            "Select current cards by popupItem without previousItem, reject historical cards before record "
            "extraction, and emit base-stat, legendary-affix, and corruption records keyed by scoped "
            "data-modifier-id. Keep requirement, lore, drop source, images, and UI data out of Structured Search."
        ),
        "errors": errors,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    report = build_audit(repo)
    output = args.output if args.output.is_absolute() else repo / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
