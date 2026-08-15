"""Structured parser for the two equipment-related system entities."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from crawler.audit_equipment_related_structured_dom_v1 import inspect_html

from ..parser_base import ParserInput, StructuredParser
from ..schema import make_record_id


@dataclass(frozen=True)
class EquipmentRelatedDefinition:
    canonical_id: str
    entity_id: str
    title: str
    route: str
    profile: str
    section_key: str
    section_name: str
    record_type: str
    subcategory_id: str
    subcategory_name_zh: str


FRAGRANCE = EquipmentRelatedDefinition(
    canonical_id="Blending_Rituals",
    entity_id="tlidb:cn:Blending_Rituals",
    title="调香秘仪",
    route="/cn/Blending_Rituals/",
    profile="fragrance",
    section_key="fragrance",
    section_name="调香秘仪",
    record_type="fragrance_affix",
    subcategory_id="equipment_related_fragrance",
    subcategory_name_zh="调香秘仪",
)

TOWER_SEQUENCE = EquipmentRelatedDefinition(
    canonical_id="TOWER_Sequence",
    entity_id="tlidb:cn:TOWER_Sequence",
    title="高塔序列",
    route="/cn/TOWER_Sequence/",
    profile="tower_sequence",
    section_key="tower_sequence",
    section_name="高塔序列",
    record_type="tower_sequence_affix",
    subcategory_id="equipment_related_tower_sequence",
    subcategory_name_zh="高塔序列",
)

DEFINITIONS = (FRAGRANCE, TOWER_SEQUENCE)
TALENT_TYPES = {"中型天赋": "medium", "核心天赋": "core", "异香天赋": "exotic"}


class EquipmentRelatedParser(StructuredParser):
    parser_id = "equipment_related.system.affixes"
    parser_version = "1.0.0"

    def __init__(self, definition: EquipmentRelatedDefinition) -> None:
        self.definition = definition

    def probe(self, html: str) -> dict[str, Any]:
        inspected = inspect_html(html)
        records = (
            inspected["fragrance_records"]
            if self.definition.profile == "fragrance"
            else inspected["tower_records"]
        )
        descriptor = {
            "section": inspected["sections"].get(self.definition.section_name),
            "tab": inspected["tabs"].get(f"#{self.definition.section_name}"),
            "record_count": len(records),
            "stable_key_count": sum(len(record["modifier_ids"]) == 1 for record in records),
        }
        if self.definition.profile == "fragrance":
            descriptor.update({
                "recipe_id_count": sum(len(record["recipe_ids"]) == 1 for record in records),
                "talent_type_count": sum(record.get("talent_type") in TALENT_TYPES for record in records),
                "recipe_field_count": sum(bool(record.get("materials")) for record in records),
                "filter_present": inspected["fragrance_filter_present"],
            })
        else:
            descriptor.update({
                "datatable_present": inspected["tower_datatable_present"],
                "headers": inspected["tower_headers"],
                "sequence_count": sum(
                    len(record["chips"]) == 1 and record.get("sequence_tier") in {"中阶序列", "高阶序列"}
                    for record in records
                ),
                "equipment_type_count": sum(bool(record.get("equipment_type")) for record in records),
            })
        signature_payload = {
            "profile": self.definition.profile,
            "section_active": bool(descriptor["section"] and descriptor["section"]["active"]),
            "tab_present": bool(descriptor["tab"]),
            "record_count": descriptor["record_count"],
            "stable_key_coverage": descriptor["stable_key_count"],
            "headers": descriptor.get("headers"),
            "recipe_contract": [descriptor.get("recipe_id_count"), descriptor.get("talent_type_count")],
            "datatable_present": descriptor.get("datatable_present"),
        }
        return {
            "descriptor": descriptor,
            "records": records,
            "structure_signature": hashlib.sha256(
                json.dumps(signature_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }

    def validate_structure(self, probe: dict[str, Any]) -> dict[str, Any]:
        observed = probe["descriptor"]
        expected_count = 97 if self.definition.profile == "fragrance" else 408
        checks = {
            "section_active": bool(observed["section"] and observed["section"]["active"]),
            "tab_present": bool(observed["tab"]),
            "record_count": observed["record_count"] == expected_count,
            "stable_key_coverage": observed["stable_key_count"] == expected_count,
        }
        if self.definition.profile == "fragrance":
            checks.update({
                "recipe_id_coverage": observed["recipe_id_count"] == expected_count,
                "talent_type_coverage": observed["talent_type_count"] == expected_count,
                "recipe_field_coverage": observed["recipe_field_count"] == expected_count,
                "filter_present": observed["filter_present"],
            })
        else:
            checks.update({
                "datatable_present": observed["datatable_present"],
                "headers": observed["headers"] == ["Affix", "来源"],
                "sequence_coverage": observed["sequence_count"] == expected_count,
                "equipment_type_coverage": observed["equipment_type_count"] == expected_count,
            })
        mismatches = {
            key: {"expected": True, "observed": value}
            for key, value in checks.items() if not value
        }
        keys = [record["modifier_ids"][0] for record in probe["records"] if len(record["modifier_ids"]) == 1]
        if len(set(keys)) != len(keys):
            mismatches["stable_key_uniqueness"] = {
                "expected": len(keys), "observed": len(set(keys)),
            }
        return {
            "status": "structure_mismatch" if mismatches else "matched",
            "expected": {"record_count": expected_count, "checks": sorted(checks)},
            "observed": observed,
            "mismatches": mismatches,
            "warnings": {},
        }

    def parse_records(self, parser_input: ParserInput, probe: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            self._fragrance_record(parser_input, record, index)
            if self.definition.profile == "fragrance"
            else self._tower_record(parser_input, record, index)
            for index, record in enumerate(probe["records"])
        ]

    def _base_record(
        self,
        parser_input: ParserInput,
        source: dict[str, Any],
        index: int,
        *,
        section_name: str,
        view_state: dict[str, Any],
    ) -> dict[str, Any]:
        stable_key = f'modifier:{source["modifier_ids"][0]}'
        return {
            "record_id": make_record_id(
                parser_id=self.parser_id,
                entity_id=self.definition.entity_id,
                record_type=self.definition.record_type,
                section_key=self.definition.section_key,
                stable_key=stable_key,
            ),
            "season_id": parser_input.season_id,
            "entity_id": self.definition.entity_id,
            "entity_type": "equipment_related_system",
            "record_type": self.definition.record_type,
            "section_id": self.definition.section_key,
            "section_name": section_name,
            "text": source["effect"],
            "route": self.definition.route,
            "source_system": parser_input.system_id,
            "source_page_id": parser_input.canonical_id,
            "source_locator": {
                "section_key": self.definition.section_key,
                "dom_id": self.definition.section_name,
                "tab_target": f"#{self.definition.section_name}",
                "row_index": index,
                "stable_key": stable_key,
                "locator_confidence": "high",
                "locator_level": "record",
                "view_state": view_state,
            },
            "source_record_index": index,
            "parser_id": self.parser_id,
            "parser_version": self.parser_version,
            "identity_confidence": "high",
        }

    def _fragrance_record(self, parser_input: ParserInput, source: dict[str, Any], index: int) -> dict[str, Any]:
        talent_name = source["talent_type"]
        record = self._base_record(
            parser_input,
            source,
            index,
            section_name=talent_name,
            view_state={"equipment_related_section": "fragrance", "filter_reset": True},
        )
        record.update({
            "talent_type": TALENT_TYPES[talent_name],
            "talent_type_name_zh": talent_name,
            "recipe_id": source["recipe_ids"][0],
            "recipe_materials": [
                {"name_zh": material["name_zh"], "route": f'/cn/{material["href"]}/', "quantity": material["quantity"]}
                for material in source["materials"]
            ],
        })
        return record

    def _tower_record(self, parser_input: ParserInput, source: dict[str, Any], index: int) -> dict[str, Any]:
        pattern = source["chips"][0]
        tier = source["sequence_tier"]
        equipment = source["equipment_type"]
        record = self._base_record(
            parser_input,
            source,
            index,
            section_name=f"{tier} {pattern} · {equipment}",
            view_state={"equipment_related_section": "tower_sequence", "datatable_ready": True},
        )
        record.update({
            "sequence_tier": "intermediate" if tier == "中阶序列" else "advanced",
            "sequence_tier_name_zh": tier,
            "sequence_pattern": pattern,
            "equipment_type": equipment,
        })
        return record
