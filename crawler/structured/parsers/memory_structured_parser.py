"""Strict section-whitelist parser for the Hero Memories system entity."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from ..parser_base import ParserInput, StructuredParser
from ..schema import make_record_id
from ..structure_probe import probe_section_table


ENTITY_ID = "tlidb:cn:Hero_Memories"


@dataclass(frozen=True)
class MemorySectionDefinition:
    section_key: str
    section_name: str
    record_type: str
    view_state: str


@dataclass(frozen=True)
class MemorySourceDefinition:
    system_id: str
    canonical_id: str
    route: str
    headers: tuple[str, ...]
    sections: tuple[MemorySectionDefinition, ...]


HERO_MEMORY_SOURCE = MemorySourceDefinition(
    system_id="inventory",
    canonical_id="Hero_Memories",
    route="/cn/Hero_Memories/",
    headers=("Tier", "Modifier", "Level", "Weight", "来源"),
    sections=(
        MemorySectionDefinition("base_attribute", "基础属性", "memory_base_attribute", "base_attribute"),
        MemorySectionDefinition("fixed_affix", "固有词缀", "memory_fixed_affix", "fixed_affix"),
        MemorySectionDefinition("random_affix", "随机词缀", "memory_random_affix", "random_affix"),
    ),
)

MEMORY_REVIVAL_SOURCE = MemorySourceDefinition(
    system_id="help",
    canonical_id="Memory_Revival",
    route="/cn/Memory_Revival/",
    headers=("Tier", "Modifier", "Level", "Weight"),
    sections=(
        MemorySectionDefinition("revival_affix", "复苏词缀", "memory_revival_affix", "revival_affix"),
        MemorySectionDefinition("revival_moon_affix", "复苏词缀（月相）", "memory_revival_moon_affix", "revival_moon_affix"),
    ),
)

MEMORY_SOURCES = (HERO_MEMORY_SOURCE, MEMORY_REVIVAL_SOURCE)


class MemoryStructuredParser(StructuredParser):
    parser_id = "memory.hero_memory.affixes"
    parser_version = "1.0.0"

    def __init__(self, definition: MemorySourceDefinition) -> None:
        self.definition = definition

    def probe(self, html: str) -> dict[str, Any]:
        sections = {
            definition.section_key: probe_section_table(html, section_id=definition.section_name)
            for definition in self.definition.sections
        }
        signature_payload = {
            key: value["descriptor"] for key, value in sections.items()
        }
        return {
            "sections": sections,
            "structure_signature": hashlib.sha256(
                json.dumps(signature_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }

    def validate_structure(self, probe: dict[str, Any]) -> dict[str, Any]:
        expected: dict[str, Any] = {}
        observed: dict[str, Any] = {}
        mismatches: dict[str, Any] = {}
        for definition in self.definition.sections:
            descriptor = probe["sections"][definition.section_key]["descriptor"]
            requirements = {
                "section_present": True,
                "tab_target_present": True,
                "table_count": 1,
                "headers": list(self.definition.headers),
            }
            expected[definition.section_key] = requirements
            observed[definition.section_key] = descriptor
            section_mismatches = {
                key: {"expected": value, "observed": descriptor.get(key)}
                for key, value in requirements.items()
                if descriptor.get(key) != value
            }
            if descriptor.get("row_count", 0) <= 0:
                section_mismatches["row_count"] = {
                    "expected": "> 0",
                    "observed": descriptor.get("row_count"),
                }
            if descriptor.get("rows_with_stable_key") != descriptor.get("row_count"):
                section_mismatches["rows_with_stable_key"] = {
                    "expected": descriptor.get("row_count"),
                    "observed": descriptor.get("rows_with_stable_key"),
                }
            if section_mismatches:
                mismatches[definition.section_key] = section_mismatches
        return {
            "status": "structure_mismatch" if mismatches else "matched",
            "expected": expected,
            "observed": observed,
            "mismatches": mismatches,
            "warnings": {},
        }

    def parse_records(
        self, parser_input: ParserInput, probe: dict[str, Any]
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for definition in self.definition.sections:
            rows = probe["sections"][definition.section_key]["rows"]
            for index, row in enumerate(rows):
                # Structure validation guarantees the key and Modifier column.
                stable_key = f"modifier:{row.stable_key}"
                records.append({
                    "record_id": make_record_id(
                        parser_id=self.parser_id,
                        entity_id=ENTITY_ID,
                        record_type=definition.record_type,
                        section_key=definition.section_key,
                        stable_key=stable_key,
                    ),
                    "season_id": parser_input.season_id,
                    "entity_id": ENTITY_ID,
                    "entity_type": "memory_system",
                    "record_type": definition.record_type,
                    "section_id": definition.section_key,
                    "section_name": definition.section_name,
                    "text": row.cells[1],
                    "route": self.definition.route,
                    "source_system": self.definition.system_id,
                    "source_page_id": self.definition.canonical_id,
                    "source_locator": {
                        "section_key": definition.section_key,
                        "dom_id": definition.section_name,
                        "tab_target": f"#{definition.section_name}",
                        "row_index": index,
                        "stable_key": stable_key,
                        "locator_confidence": "high",
                        "locator_level": "record",
                        "view_state": {"memory_section": definition.view_state},
                    },
                    "source_record_index": index,
                    "parser_id": self.parser_id,
                    "parser_version": self.parser_version,
                    "identity_confidence": "high",
                })
        return records
