"""Parameterized structured parser for the ten confirmed Vorax equipment pages."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from crawler.audit_vorax_structured_dom_v1 import inspect_html

from ..parser_base import ParserInput, StructuredParser
from ..schema import make_record_id
from ..structure_probe import TableRow, probe_section_table


@dataclass(frozen=True)
class VoraxDefinition:
    canonical_id: str
    title: str

    @property
    def route(self) -> str:
        return f"/cn/{self.canonical_id}/"


class _ModifierTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.capture: dict[str, Any] | None = None
        self.records: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs_list)
        if self.capture is not None:
            self.capture["depth"] += 1
        elif attrs.get("data-modifier-id"):
            self.capture = {"stable_key": attrs["data-modifier-id"], "parts": [], "depth": 1}

    def handle_startendtag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        return

    def handle_data(self, data: str) -> None:
        if self.capture is not None:
            self.capture["parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.capture is None:
            return
        self.capture["depth"] -= 1
        if self.capture["depth"] == 0:
            text = " ".join(" ".join(self.capture["parts"]).split())
            self.records.append({"stable_key": self.capture["stable_key"], "text": text})
            self.capture = None


def _pane(html: str, pane_id: str) -> str:
    pattern = re.compile(r'<div id="([^"]+)" class="tab-pane[^>]*>', re.I)
    starts = list(pattern.finditer(html))
    for index, match in enumerate(starts):
        if match.group(1) == pane_id:
            end = starts[index + 1].start() if index + 1 < len(starts) else len(html)
            return html[match.end() : end]
    return ""


def _modifier_records(fragment: str) -> list[dict[str, str]]:
    parser = _ModifierTextParser()
    parser.feed(fragment)
    return parser.records


def _current_entity_fragment(entity_pane: str) -> str:
    current = re.search(r'<div class="[^"]*\bpopupItem\b(?![^"]*\bpreviousItem\b)[^"]*">', entity_pane, re.I)
    if not current:
        return ""
    historical = re.search(r'<div class="[^"]*\bpopupItem\b[^"]*\bpreviousItem\b[^"]*">', entity_pane[current.end() :], re.I)
    end = current.end() + historical.start() if historical else len(entity_pane)
    return entity_pane[current.end() : end]


class VoraxEquipmentParser(StructuredParser):
    parser_id = "inventory.vorax_equipment.affixes"
    parser_version = "1.0.0"
    base_headers = ["Tier", "Modifier", "Level", "Weight"]
    craft_headers = [["Tier", "Modifier", "Lv", "Weight", "Library"]] * 2

    def __init__(self, definition: VoraxDefinition) -> None:
        self.definition = definition

    def probe(self, html: str) -> dict[str, Any]:
        audit = inspect_html(html)
        base = probe_section_table(html, section_id="基础词缀")
        craft = probe_section_table(html, section_id="打造")
        legendary = _modifier_records(_pane(html, "传奇品质"))
        entity_pane = _pane(html, self.definition.title)
        current_fragment = _current_entity_fragment(entity_pane)
        base_stats = _modifier_records(current_fragment)
        details = audit["detail_blocks"]
        descriptor = {
            "pane_ids": audit["pane_ids"],
            "entity_pane_id": audit["entity_pane_id"],
            "current_card_count": audit["current_card_count"],
            "historical_card_count": audit["historical_card_count"],
            "current_versions": audit["current_versions"],
            "base_table": base["descriptor"],
            "craft_table": craft["descriptor"],
            "legendary_item_count": audit["legendary_item_count"],
            "legendary_modifier_count": len(legendary),
            "current_base_stat_count": len(base_stats),
            "special_mechanic_count": len(details),
            "tier_controls": audit["craft_tier_values"],
            "legendary_filter_count": audit["legendary_filter_count"],
        }
        signature_payload = {
            "required_panes_present": all(key in audit["pane_ids"] for key in ("打造", "传奇品质", "基础词缀", self.definition.title, "Item")),
            "current_history_contract": [audit["current_card_count"], audit["historical_card_count"]],
            "base_headers": base["descriptor"]["table_headers"],
            "craft_headers": craft["descriptor"]["table_headers"],
            "base_key_attribute": base["descriptor"]["stable_key_attribute"],
            "craft_key_attribute": craft["descriptor"]["stable_key_attribute"],
            "tier_attribute": craft["descriptor"]["tier_attribute"],
            "tier_controls": audit["craft_tier_values"],
            "legendary_filter": audit["legendary_filter_count"] > 0,
        }
        return {
            "descriptor": descriptor,
            "base": base,
            "craft": craft,
            "legendary": legendary,
            "base_stats": base_stats,
            "special_mechanics": details,
            "structure_signature": hashlib.sha256(
                json.dumps(signature_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }

    def validate_structure(self, probe: dict[str, Any]) -> dict[str, Any]:
        observed = probe["descriptor"]
        required_panes = ["打造", "传奇品质", "基础词缀", self.definition.title, "Item"]
        checks = {
            "required_panes": all(key in observed["pane_ids"] for key in required_panes),
            "entity_pane": observed["entity_pane_id"] == self.definition.title,
            "current_card": observed["current_card_count"] == 1,
            "history_contract": observed["historical_card_count"] == 1,
            "current_ss13_validation": bool(observed["current_versions"]) and all("SS13" in value for value in observed["current_versions"]),
            "base_table_count": observed["base_table"]["table_count"] == 1,
            "base_headers": observed["base_table"]["table_headers"] == [self.base_headers],
            "base_stable_keys": observed["base_table"]["rows_with_stable_key"] == observed["base_table"]["row_count"] > 0,
            "craft_table_count": observed["craft_table"]["table_count"] == 2,
            "craft_headers": observed["craft_table"]["table_headers"] == self.craft_headers,
            "craft_stable_keys": observed["craft_table"]["rows_with_stable_key"] == observed["craft_table"]["row_count"] > 0,
            "craft_tier_contract": observed["craft_table"]["rows_with_tier"] == observed["craft_table"]["row_count"],
            "tier_controls": observed["tier_controls"] == ["all", "0+", "0", "1", "2"],
            "legendary_quality": observed["legendary_item_count"] > 0 and observed["legendary_modifier_count"] > 0,
            "legendary_filter": observed["legendary_filter_count"] == 1,
            "base_stats": observed["current_base_stat_count"] > 0,
            "special_mechanic": observed["special_mechanic_count"] == 1,
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

    @staticmethod
    def _tier(source_value: str | None) -> str:
        return {"0+": "t0_plus", "0": "t0", "1": "t1", "2": "t2"}.get(source_value, "all")

    def _record(
        self,
        parser_input: ParserInput,
        *,
        record_type: str,
        section_id: str,
        section_name: str,
        text: str,
        stable_key: str,
        row_index: int,
        dom_id: str,
        locator_level: str = "record",
        locator_confidence: str = "high",
        view_state: dict[str, str],
        **locator_extra: Any,
    ) -> dict[str, Any]:
        entity_id = f"tlidb:cn:{parser_input.canonical_id}"
        source_locator = {
            "section_key": section_id,
            "dom_id": dom_id,
            "tab_target": f"#{dom_id}",
            "row_index": row_index,
            "stable_key": stable_key,
            "locator_confidence": locator_confidence,
            "locator_level": locator_level,
            "view_state": view_state,
            **locator_extra,
        }
        return {
            "record_id": make_record_id(
                parser_id=self.parser_id,
                entity_id=entity_id,
                record_type=record_type,
                section_key=section_id,
                stable_key=stable_key,
            ),
            "season_id": parser_input.season_id,
            "entity_id": entity_id,
            "entity_type": "vorax_equipment",
            "record_type": record_type,
            "section_id": section_id,
            "section_name": section_name,
            "text": text,
            "route": parser_input.canonical_route,
            "source_system": parser_input.system_id,
            "source_page_id": parser_input.canonical_id,
            "source_locator": source_locator,
            "source_record_index": row_index,
            "parser_id": self.parser_id,
            "parser_version": self.parser_version,
            "identity_confidence": "high" if locator_level == "record" else "medium",
        }

    def _table_records(
        self,
        parser_input: ParserInput,
        rows: list[TableRow] | tuple[TableRow, ...],
        *,
        record_type: str,
        section_id: str,
        section_name: str,
        dom_id: str,
        vorax_tab: str,
        tier_aware: bool = False,
    ) -> list[dict[str, Any]]:
        result = []
        for index, row in enumerate(rows):
            stable_key = f"modifier:{row.stable_key}"
            tier = self._tier(row.tier_value) if tier_aware else None
            view_state = {"vorax_tab": vorax_tab, "season_container": "current"}
            if tier is not None:
                view_state["craft_tier"] = tier
            record = self._record(
                parser_input,
                record_type=record_type,
                section_id=section_id,
                section_name=section_name,
                text=row.cells[1],
                stable_key=stable_key,
                row_index=index,
                dom_id=dom_id,
                view_state=view_state,
                tier_value=row.tier_value,
                container_selector=f"#{dom_id}",
            )
            if tier is not None:
                record["tier"] = tier
            result.append(record)
        return result

    def parse_records(self, parser_input: ParserInput, probe: dict[str, Any]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        entity_dom_id = self.definition.title
        for index, item in enumerate(probe["base_stats"]):
            records.append(self._record(
                parser_input,
                record_type="vorax_base_stat",
                section_id="entity_card",
                section_name="基础属性",
                text=item["text"],
                stable_key=f"modifier:{item['stable_key']}",
                row_index=index,
                dom_id=entity_dom_id,
                view_state={"vorax_tab": "entity", "season_container": "current"},
                container_selector=f"#{entity_dom_id} .popupItem:not(.previousItem)",
            ))
        for index, text in enumerate(probe["special_mechanics"]):
            records.append(self._record(
                parser_input,
                record_type="vorax_special_mechanic",
                section_id="special_mechanic",
                section_name="特殊机制",
                text=text,
                stable_key="section:special_mechanic",
                row_index=index,
                dom_id=entity_dom_id,
                locator_level="section",
                locator_confidence="medium",
                view_state={"vorax_tab": "entity", "season_container": "current"},
                container_selector=f"#{entity_dom_id} .popupItem:not(.previousItem)",
                section_selector="[data-block='detail']",
            ))
        records.extend(self._table_records(
            parser_input, probe["base"]["rows"], record_type="vorax_base_affix",
            section_id="base_affixes", section_name="基础词缀", dom_id="基础词缀",
            vorax_tab="base_affix",
        ))
        records.extend(self._table_records(
            parser_input, probe["craft"]["rows"], record_type="vorax_craft_affix",
            section_id="craft_affixes", section_name="打造词缀", dom_id="打造",
            vorax_tab="craft", tier_aware=True,
        ))
        for index, item in enumerate(probe["legendary"]):
            records.append(self._record(
                parser_input,
                record_type="vorax_legendary_quality_affix",
                section_id="legendary_quality",
                section_name="传奇品质",
                text=item["text"],
                stable_key=f"modifier:{item['stable_key']}",
                row_index=index,
                dom_id="传奇品质",
                view_state={"vorax_tab": "legendary_quality", "legendary_filter": "clear", "season_container": "current"},
                container_selector="#传奇品质",
                legendary_filter_name="filter",
            ))
        return records

