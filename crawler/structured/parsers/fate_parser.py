"""Structured parser for current Fate card effects."""

from __future__ import annotations

import hashlib
import json
from html.parser import HTMLParser
from typing import Any

from ..parser_base import ParserInput, StructuredParser
from ..schema import make_record_id


VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class FateCardInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, Any]] = []
        self.current_capture: dict[str, Any] | None = None
        self.current_modifiers: list[dict[str, str]] = []
        self.historical_modifier_ids: list[str] = []
        self.descriptions: list[str] = []
        self.current_cards = 0
        self.historical_cards = 0
        self.cache_tabs = 0

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs_list)
        classes = set((attrs.get("class") or "").split())
        parent_kind = self.stack[-1].get("card_kind") if self.stack else None
        card_kind = parent_kind
        if tag == "div" and {"ui_item", "popupItem"} <= classes:
            card_kind = "historical" if "previousItem" in classes else "current"
            if card_kind == "current":
                self.current_cards += 1
            else:
                self.historical_cards += 1
        if tag == "div" and "tab-pane" in classes and "cache-" in str(attrs.get("id") or ""):
            self.cache_tabs += 1
        frame = {"tag": tag, "card_kind": card_kind, "capture_root": False}
        if tag not in VOID:
            self.stack.append(frame)
        modifier_id = attrs.get("data-modifier-id")
        if modifier_id and card_kind == "historical":
            self.historical_modifier_ids.append(modifier_id)
        elif modifier_id and card_kind == "current" and self.current_capture is None:
            self.current_capture = {"kind": "modifier", "stable_key": modifier_id, "parts": []}
            frame["capture_root"] = True
        elif attrs.get("data-block") == "description2" and card_kind == "current" and self.current_capture is None:
            self.current_capture = {"kind": "description", "parts": []}
            frame["capture_root"] = True

    def handle_data(self, data: str) -> None:
        if self.current_capture is not None:
            self.current_capture["parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] != tag:
                continue
            removed = self.stack[index:]
            del self.stack[index:]
            if self.current_capture and any(frame["capture_root"] for frame in removed):
                text = " ".join(" ".join(self.current_capture["parts"]).split())
                if self.current_capture["kind"] == "modifier":
                    self.current_modifiers.append({
                        "stable_key": self.current_capture["stable_key"], "text": text,
                    })
                elif text:
                    self.descriptions.append(text)
                self.current_capture = None
            break


class FateParser(StructuredParser):
    parser_id = "pact.fate.effects"
    parser_version = "1.0.0"

    def probe(self, html: str) -> dict[str, Any]:
        inspector = FateCardInspector()
        inspector.feed(html)
        descriptor = {
            "current_card_count": inspector.current_cards,
            "historical_card_count": inspector.historical_cards,
            "current_modifier_count": len(inspector.current_modifiers),
            "current_modifier_key_count": sum(bool(item["stable_key"]) for item in inspector.current_modifiers),
            "current_unique_modifier_keys": len({item["stable_key"] for item in inspector.current_modifiers}),
            "historical_modifier_count": len(inspector.historical_modifier_ids),
            "current_history_duplicate_keys": len(
                {item["stable_key"] for item in inspector.current_modifiers}
                & set(inspector.historical_modifier_ids)
            ),
            "current_description_count": len(inspector.descriptions),
            "cache_tab_count": inspector.cache_tabs,
        }
        signature = {
            "current_card_count": descriptor["current_card_count"],
            "historical_card_count": descriptor["historical_card_count"],
            "current_modifier_count": descriptor["current_modifier_count"],
            "current_description_count": descriptor["current_description_count"],
            "cache_tab_count": descriptor["cache_tab_count"],
        }
        return {
            "descriptor": descriptor,
            "modifiers": inspector.current_modifiers,
            "descriptions": inspector.descriptions,
            "historical_modifier_ids": inspector.historical_modifier_ids,
            "structure_signature": hashlib.sha256(
                json.dumps(signature, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }

    def validate_structure(self, probe: dict[str, Any]) -> dict[str, Any]:
        observed = probe["descriptor"]
        undetermined = observed["current_modifier_count"] == 0
        checks = {
            "single_current_card": observed["current_card_count"] == 1,
            "effect_contract": (
                observed["current_description_count"] == 1 if undetermined
                else observed["current_modifier_count"] == 1
            ),
            "modifier_key_coverage": (
                True if undetermined else
                observed["current_modifier_key_count"] == observed["current_modifier_count"]
            ),
            "modifier_key_unique": (
                True if undetermined else
                observed["current_unique_modifier_keys"] == observed["current_modifier_count"]
            ),
            "history_separable": observed["historical_card_count"] in {0, 1},
        }
        mismatches = {
            key: {"expected": True, "observed": value}
            for key, value in checks.items() if not value
        }
        return {
            "status": "structure_mismatch" if mismatches else "matched",
            "expected": {"checks": sorted(checks)},
            "observed": observed,
            "mismatches": mismatches,
            "warnings": {},
        }

    def parse_records(self, parser_input: ParserInput, probe: dict[str, Any]) -> list[dict[str, Any]]:
        entity_id = f"tlidb:cn:{parser_input.canonical_id}"
        if probe["modifiers"]:
            source = probe["modifiers"][0]
            stable_key = f'modifier:{source["stable_key"]}'
            record_type = "fate_effect"
            locator_level = "record"
            confidence = "high"
            text = source["text"]
            section_key = "current_effect"
            section_selector = None
        else:
            stable_key = "section:current_description2"
            record_type = "fate_entity_effect"
            locator_level = "section"
            confidence = "medium"
            text = probe["descriptions"][0]
            section_key = "current_description"
            section_selector = '[data-block="description2"]'
        locator = {
            "section_key": section_key,
            "dom_id": "",
            "tab_target": "",
            "row_index": 0,
            "stable_key": stable_key,
            "locator_confidence": confidence,
            "locator_level": locator_level,
            "view_state": {"fate_state": "current"},
        }
        if section_selector:
            locator["section_selector"] = section_selector
        return [{
            "record_id": make_record_id(
                parser_id=self.parser_id,
                entity_id=entity_id,
                record_type=record_type,
                section_key=section_key,
                stable_key=stable_key,
            ),
            "season_id": parser_input.season_id,
            "entity_id": entity_id,
            "entity_type": "fate",
            "record_type": record_type,
            "section_id": section_key,
            "section_name": "命运效果",
            "text": text,
            "route": parser_input.canonical_route,
            "source_system": parser_input.system_id,
            "source_page_id": parser_input.canonical_id,
            "source_locator": locator,
            "source_record_index": 0,
            "parser_id": self.parser_id,
            "parser_version": self.parser_version,
            "identity_confidence": confidence,
        }]

