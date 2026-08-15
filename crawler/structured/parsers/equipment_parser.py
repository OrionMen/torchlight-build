"""Parameterized parser for the 38 confirmed ordinary equipment pages."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from ..parser_base import ParserInput, StructuredParser
from ..schema import make_record_id
from ..structure_probe import TableRow, probe_section_table


@dataclass(frozen=True)
class EquipmentDefinition:
    canonical_id: str
    title: str

    @property
    def route(self) -> str:
        return f"/cn/{self.canonical_id}/"


EQUIPMENT_DEFINITIONS = (
    EquipmentDefinition("STR_Helmet", "力量头部"),
    EquipmentDefinition("DEX_Helmet", "敏捷头部"),
    EquipmentDefinition("INT_Helmet", "智慧头部"),
    EquipmentDefinition("STR_Chest_Armor", "力量胸甲"),
    EquipmentDefinition("DEX_Chest_Armor", "敏捷胸甲"),
    EquipmentDefinition("INT_Chest_Armor", "智慧胸甲"),
    EquipmentDefinition("STR_Gloves", "力量手套"),
    EquipmentDefinition("DEX_Gloves", "敏捷手套"),
    EquipmentDefinition("INT_Gloves", "智慧手套"),
    EquipmentDefinition("STR_Boots", "力量鞋子"),
    EquipmentDefinition("DEX_Boots", "敏捷鞋子"),
    EquipmentDefinition("INT_Boots", "智慧鞋子"),
    EquipmentDefinition("Claw", "爪"),
    EquipmentDefinition("Dagger", "匕首"),
    EquipmentDefinition("One-Handed_Sword", "单手剑"),
    EquipmentDefinition("One-Handed_Hammer", "单手锤"),
    EquipmentDefinition("One-Handed_Axe", "单手斧"),
    EquipmentDefinition("Wand", "法杖"),
    EquipmentDefinition("Rod", "灵杖"),
    EquipmentDefinition("Scepter", "魔杖"),
    EquipmentDefinition("Cane", "手杖"),
    EquipmentDefinition("Pistol", "手枪"),
    EquipmentDefinition("Two-Handed_Sword", "双手剑"),
    EquipmentDefinition("Two-Handed_Hammer", "双手锤"),
    EquipmentDefinition("Two-Handed_Axe", "双手斧"),
    EquipmentDefinition("Tin_Staff", "锡杖"),
    EquipmentDefinition("Cudgel", "武杖"),
    EquipmentDefinition("Bow", "弓"),
    EquipmentDefinition("Crossbow", "弩"),
    EquipmentDefinition("Musket", "火枪"),
    EquipmentDefinition("Fire_Cannon", "火炮"),
    EquipmentDefinition("STR_Shield", "力量盾牌"),
    EquipmentDefinition("DEX_Shield", "敏捷盾牌"),
    EquipmentDefinition("INT_Shield", "智慧盾牌"),
    EquipmentDefinition("Necklace", "项链"),
    EquipmentDefinition("Ring", "戒指"),
    EquipmentDefinition("Belt", "腰带"),
    EquipmentDefinition("Spirit_Ring", "灵戒"),
)


class EquipmentParser(StructuredParser):
    parser_id = "inventory.ordinary_equipment.affixes"
    parser_version = "1.1.0"
    base_headers = ["Tier", "Modifier", "Level", "Weight"]
    craft_headers = ["Tier", "Modifier", "Lv", "Weight", "Library"]

    def __init__(self, definition: EquipmentDefinition) -> None:
        self.definition = definition

    @property
    def base_dom_id(self) -> str:
        return f"{self.definition.title}基础词缀"

    @property
    def craft_dom_id(self) -> str:
        return f"{self.definition.title}打造"

    def probe(self, html: str) -> dict[str, Any]:
        base = probe_section_table(html, section_id=self.base_dom_id)
        craft = probe_section_table(html, section_id=self.craft_dom_id)
        signature_payload = {
            "base": base["descriptor"],
            "craft": craft["descriptor"],
        }
        signature = hashlib.sha256(
            json.dumps(signature_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return {"base": base, "craft": craft, "structure_signature": signature}

    def validate_structure(self, probe: dict[str, Any]) -> dict[str, Any]:
        expected = {
            "base_affixes": {
                "section_present": True,
                "tab_target_present": True,
                "table_count": 1,
                "table_headers": [self.base_headers],
            },
            "craft_affixes": {
                "section_present": True,
                "tab_target_present": True,
                "table_count": 2,
                "table_headers": [self.craft_headers, self.craft_headers],
                "tier_attribute": "data-tier",
            },
        }
        observed = {
            "base_affixes": probe["base"]["descriptor"],
            "craft_affixes": probe["craft"]["descriptor"],
        }
        mismatches: dict[str, Any] = {}
        warnings: dict[str, Any] = {}
        for section_key, requirements in expected.items():
            actual = observed[section_key]
            section_mismatches = {
                key: {"expected": value, "observed": actual.get(key)}
                for key, value in requirements.items()
                if actual.get(key) != value
            }
            if actual.get("row_count", 0) <= 0:
                section_mismatches["row_count"] = {
                    "expected": "> 0",
                    "observed": actual.get("row_count"),
                }
            if section_mismatches:
                mismatches[section_key] = section_mismatches
            if section_key == "craft_affixes" and actual.get("rows_with_tier") != actual.get("row_count"):
                mismatches.setdefault(section_key, {})["rows_with_tier"] = {
                    "expected": actual.get("row_count"),
                    "observed": actual.get("rows_with_tier"),
                }
            missing_keys = actual.get("row_count", 0) - actual.get("rows_with_stable_key", 0)
            if missing_keys:
                warnings[section_key] = {"rows_without_stable_key": missing_keys}
        return {
            "status": "structure_mismatch" if mismatches else "matched",
            "expected": expected,
            "observed": observed,
            "mismatches": mismatches,
            "warnings": warnings,
        }

    def _records_for_section(
        self,
        parser_input: ParserInput,
        *,
        rows: list[TableRow],
        section_key: str,
        section_name: str,
        dom_id: str,
        record_type: str,
        include_tier: bool = False,
    ) -> list[dict[str, Any]]:
        entity_id = f"tlidb:cn:{parser_input.canonical_id}"
        records = []
        for index, row in enumerate(rows):
            has_source_key = bool(row.stable_key)
            stable_key = f"modifier:{row.stable_key}" if has_source_key else f"row:{index}"
            locator_level = "record" if has_source_key else "section"
            record = {
                "record_id": make_record_id(
                    parser_id=self.parser_id,
                    entity_id=entity_id,
                    record_type=record_type,
                    section_key=section_key,
                    stable_key=stable_key,
                ),
                "season_id": parser_input.season_id,
                "entity_id": entity_id,
                "entity_type": "equipment",
                "record_type": record_type,
                "section_id": section_key,
                "section_name": section_name,
                "text": row.cells[1],
                "route": parser_input.canonical_route,
                "source_system": parser_input.system_id,
                "source_page_id": parser_input.canonical_id,
                "source_locator": {
                    "section_key": section_key,
                    "dom_id": dom_id,
                    "tab_target": f"#{dom_id}",
                    "row_index": index,
                    "stable_key": stable_key,
                    "locator_confidence": "high" if has_source_key else "medium",
                    "locator_level": locator_level,
                },
                "source_record_index": index,
                "parser_id": self.parser_id,
                "parser_version": self.parser_version,
                "identity_confidence": "high" if has_source_key else "low",
            }
            if include_tier:
                normalized_tier = {
                    "0+": "t0_plus",
                    "0": "t0",
                    "1": "t1",
                    "2": "t2",
                }.get(row.tier_value)
                record["tier"] = normalized_tier
                record["source_locator"]["tier_value"] = row.tier_value
                record["source_locator"]["tier_filter_name"] = "showDetail"
            records.append(record)
        return records

    def parse_records(
        self, parser_input: ParserInput, probe: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return self._records_for_section(
            parser_input,
            rows=probe["base"]["rows"],
            section_key="base_affixes",
            section_name="基础词缀",
            dom_id=self.base_dom_id,
            record_type="equipment_base_affix",
        ) + self._records_for_section(
            parser_input,
            rows=probe["craft"]["rows"],
            section_key="craft_affixes",
            section_name="打造词缀",
            dom_id=self.craft_dom_id,
            record_type="equipment_craft_affix",
            include_tier=True,
        )

    def parse(self, parser_input: ParserInput) -> dict[str, Any]:
        result = super().parse(parser_input)
        records = result.pop("records")
        result.update(
            {
                "entity_id": f"tlidb:cn:{parser_input.canonical_id}",
                "entity_type": "equipment",
                "title": self.definition.title,
                "route": parser_input.canonical_route,
                "sections": {
                    "base_affixes": [
                        record for record in records if record["record_type"] == "equipment_base_affix"
                    ],
                    "craft_affixes": [
                        record for record in records if record["record_type"] == "equipment_craft_affix"
                    ],
                },
            }
        )
        return result
