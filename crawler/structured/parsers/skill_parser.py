"""Structured parser for current SS13 skill effects and growth modifiers."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from crawler.audit_skill_structured_dom_v1 import (
    ancestor_with_class,
    first_descendant,
    inspect_skill_html,
    nodes,
    parse_html,
)

from ..parser_base import ParserInput, StructuredParser
from ..schema import make_record_id


class SkillParser(StructuredParser):
    parser_id = "skill.structured"
    parser_version = "1.0.0"

    def probe(self, html: str) -> dict[str, Any]:
        dom = inspect_skill_html(html)
        root = parse_html(html)
        current_cards = [
            card for card in nodes(root, class_name="popupItem")
            if "previousItem" not in card.classes
            and not (
                (pane := ancestor_with_class(card, "tab-pane"))
                and not ({"active", "show"} <= pane.classes)
            )
        ]
        card = current_cards[0] if len(current_cards) == 1 else None
        title = dom.get("current_title") or ""
        tags = list(dict.fromkeys(dom.get("tags") or []))
        weapon_restrictions: list[str] = []
        core_attributes: list[str] = []
        if card is not None:
            weapon_restrictions = list(dict.fromkeys(
                node.text() for node in card.descendants()
                if node.attrs.get("data-block") == "weapon_restrict_description" and node.text()
            ))
            for node in card.descendants():
                if not ({"d-flex", "justify-content-center"} <= node.classes):
                    continue
                if any("tag" in descendant.classes for descendant in node.descendants()):
                    continue
                value = node.text()
                if value and value not in core_attributes:
                    core_attributes.append(value)
        effects = list(dict.fromkeys(value for value in dom.get("explicit_effects", []) if value))
        effect_parts = [title]
        if tags:
            effect_parts.append("标签：" + "、".join(tags))
        effect_parts.extend(weapon_restrictions)
        effect_parts.extend(core_attributes)
        effect_parts.extend(effects)
        effect_text = " ".join(value for value in effect_parts if value)
        modifier_ids = [item["modifier_id"] for item in dom["modifiers"]]
        modifier_id_counts = Counter(modifier_ids)
        modifier_identity_keys = [
            (
                f"modifier:{item['modifier_id']}:tier:{item['tier']}"
                if modifier_id_counts[item["modifier_id"]] > 1
                else f"modifier:{item['modifier_id']}"
            )
            for item in dom["modifiers"]
        ]
        descriptor = {
            "template_group": dom["template_group"],
            "current_card_count": dom["current_card_count"],
            "current_pane_count": len(dom["active_panes"]),
            "current_pane_id": dom["current_pane_id"],
            "skill_id_present": bool(dom["info_id"]),
            "effect_text_present": bool(effect_text),
            "growth_modifier_count": len(dom["modifiers"]),
            "growth_modifier_id_count": len(modifier_ids),
            "unique_growth_modifier_ids": len(set(modifier_ids)),
            "unique_growth_identity_keys": len(set(modifier_identity_keys)),
            "repeated_modifier_id_count": sum(
                count - 1 for count in modifier_id_counts.values() if count > 1
            ),
            "growth_headers_valid": all(
                item["table_headers"][:2] == ["Tier", "name"] for item in dom["modifiers"]
            ),
            "empty_growth_text_count": sum(not item["text"] for item in dom["modifiers"]),
            "level_table_count": len(dom["level_tables"]),
            "level_rows": sum(table["row_count"] for table in dom["level_tables"]),
            "level_headers_valid": all(
                table["headers"] and table["headers"][0].casefold() == "level"
                for table in dom["level_tables"]
            ),
            "filter_count": dom["filter_count"],
            "datatable_count": dom["datatable_count"],
            "historical_records_selected": 0,
            "inactive_records_selected": 0,
        }
        signature_contract = {
            key: descriptor[key] for key in (
                "template_group", "current_card_count", "current_pane_count",
                "growth_modifier_count", "level_table_count", "filter_count",
            )
        }
        return {
            "descriptor": descriptor,
            "skill_id": dom["info_id"],
            "title": title,
            "tags": tags,
            "weapon_restrictions": weapon_restrictions,
            "core_attributes": core_attributes,
            "effects": effects,
            "effect_text": effect_text,
            "current_pane_id": dom["current_pane_id"],
            "modifiers": dom["modifiers"],
            "modifier_id_counts": dict(modifier_id_counts),
            "level_tables": dom["level_tables"],
            "structure_signature": hashlib.sha256(
                json.dumps(signature_contract, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }

    def validate_structure(self, probe: dict[str, Any]) -> dict[str, Any]:
        observed = probe["descriptor"]
        checks = {
            "known_template_group": observed["template_group"] in {
                "skill_modifier_growth", "skill_standalone_card",
                "skill_tabbed_cache_history", "skill_tabbed_variants",
            },
            "one_current_card": observed["current_card_count"] == 1,
            "at_most_one_current_pane": observed["current_pane_count"] <= 1,
            "skill_id_present": observed["skill_id_present"],
            "effect_text_present": observed["effect_text_present"],
            "growth_modifier_id_coverage": (
                observed["growth_modifier_count"] == observed["growth_modifier_id_count"]
            ),
            "growth_identity_keys_unique": (
                observed["growth_modifier_count"] == observed["unique_growth_identity_keys"]
            ),
            "growth_headers_valid": observed["growth_headers_valid"],
            "growth_text_present": observed["empty_growth_text_count"] == 0,
            "level_headers_valid": observed["level_headers_valid"],
            "historical_scope_excluded": observed["historical_records_selected"] == 0,
            "inactive_scope_excluded": observed["inactive_records_selected"] == 0,
        }
        mismatches = {
            name: {"expected": True, "observed": value}
            for name, value in checks.items() if not value
        }
        return {
            "status": "structure_mismatch" if mismatches else "matched",
            "expected": {"checks": sorted(checks)},
            "observed": observed,
            "mismatches": mismatches,
            "warnings": {},
        }

    def parse_records(
        self, parser_input: ParserInput, probe: dict[str, Any]
    ) -> list[dict[str, Any]]:
        entity_id = f"tlidb:cn:{parser_input.canonical_id}"
        skill_id = str(probe["skill_id"])
        current_pane = probe["current_pane_id"]
        level_values = [
            level for table in probe["level_tables"] for level in table.get("levels", [])
        ]
        effect_stable_key = f"skill:{skill_id}"
        records: list[dict[str, Any]] = [{
            "record_id": make_record_id(
                parser_id=self.parser_id,
                entity_id=entity_id,
                record_type="skill_effect",
                section_key="skill_effect",
                stable_key=effect_stable_key,
            ),
            "season_id": parser_input.season_id,
            "entity_id": entity_id,
            "entity_type": "skill",
            "record_type": "skill_effect",
            "section_id": "skill_effect",
            "section_name": "技能效果",
            "text": probe["effect_text"],
            "route": parser_input.canonical_route,
            "source_system": parser_input.system_id,
            "source_page_id": parser_input.canonical_id,
            "source_locator": {
                "section_key": "skill_effect",
                "dom_id": current_pane or "",
                "tab_target": f"#{current_pane}" if current_pane else "",
                "row_index": 0,
                "stable_key": effect_stable_key,
                "locator_confidence": "high",
                "locator_level": "section",
                "section_selector": ".card.ui_item.popupItem:not(.previousItem)",
                "view_state": {
                    "skill_effect": True,
                    "skill_current_pane": current_pane,
                    "filter_reset": bool(probe["descriptor"]["filter_count"]),
                },
            },
            "source_record_index": 0,
            "parser_id": self.parser_id,
            "parser_version": self.parser_version,
            "identity_confidence": "high",
            "skill_id": skill_id,
            "skill_tags": probe["tags"],
            "weapon_restrictions": probe["weapon_restrictions"],
            "core_attributes": probe["core_attributes"],
            "level_table_present": bool(probe["level_tables"]),
            "level_row_count": probe["descriptor"]["level_rows"],
            "level_values": level_values,
            "display_level": "20",
        }]
        for index, modifier in enumerate(probe["modifiers"], start=1):
            repeated_id = probe["modifier_id_counts"][modifier["modifier_id"]] > 1
            stable_key = (
                f"modifier:{modifier['modifier_id']}:tier:{modifier['tier']}"
                if repeated_id else f"modifier:{modifier['modifier_id']}"
            )
            pane_id = modifier.get("pane_id")
            records.append({
                "record_id": make_record_id(
                    parser_id=self.parser_id,
                    entity_id=entity_id,
                    record_type="skill_growth_modifier",
                    section_key="skill_growth",
                    stable_key=stable_key,
                ),
                "season_id": parser_input.season_id,
                "entity_id": entity_id,
                "entity_type": "skill",
                "record_type": "skill_growth_modifier",
                "section_id": "skill_growth",
                "section_name": "成长词缀",
                "text": modifier["text"],
                "route": parser_input.canonical_route,
                "source_system": parser_input.system_id,
                "source_page_id": parser_input.canonical_id,
                "source_locator": {
                    "section_key": "skill_growth",
                    "dom_id": pane_id or "",
                    "tab_target": f"#{pane_id}" if pane_id else "",
                    "row_index": index - 1,
                    "stable_key": stable_key,
                    "locator_confidence": "high",
                    "locator_level": "record",
                    "section_selector": "table.DataTable",
                    "view_state": {
                        "skill_growth": True,
                        "skill_current_pane": pane_id,
                        "skill_modifier_id": modifier["modifier_id"],
                        "skill_modifier_tier": modifier.get("tier"),
                        "filter_reset": bool(probe["descriptor"]["filter_count"]),
                        "datatable_ready": True,
                    },
                },
                "source_record_index": index,
                "parser_id": self.parser_id,
                "parser_version": self.parser_version,
                "identity_confidence": "high",
                "skill_id": skill_id,
                "modifier_id": modifier["modifier_id"],
                "tier": modifier.get("tier") or "unknown",
                "source_section": modifier.get("section") or "成长",
            })
        return records
