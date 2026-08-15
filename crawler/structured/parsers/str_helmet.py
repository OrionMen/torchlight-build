"""Single-page framework demo: STR_Helmet base affixes."""

from __future__ import annotations

from typing import Any

from ..parser_base import ParserInput, StructuredParser
from ..schema import make_record_id
from ..structure_probe import probe_section_table


class StrHelmetBaseAffixParser(StructuredParser):
    parser_id = "inventory.str_helmet.base_affix"
    parser_version = "1.0.0"
    section_dom_id = "力量头部基础词缀"
    section_key = "base_affix"
    expected_headers = ["Tier", "Modifier", "Level", "Weight"]

    def probe(self, html: str) -> dict[str, Any]:
        return probe_section_table(html, section_id=self.section_dom_id)

    def validate_structure(self, probe: dict[str, Any]) -> dict[str, Any]:
        observed = probe["descriptor"]
        expected = {
            "section_present": True,
            "tab_target_present": True,
            "table_count": 1,
            "headers": self.expected_headers,
            "stable_key_attribute": "data-modifier-id",
        }
        mismatches = {
            key: {"expected": value, "observed": observed.get(key)}
            for key, value in expected.items()
            if observed.get(key) != value
        }
        if observed.get("row_count", 0) and observed.get("rows_with_stable_key") != observed.get("row_count"):
            mismatches["rows_with_stable_key"] = {
                "expected": observed.get("row_count"),
                "observed": observed.get("rows_with_stable_key"),
            }
        return {
            "status": "structure_mismatch" if mismatches else "matched",
            "expected": expected,
            "observed": observed,
            "mismatches": mismatches,
        }

    def parse_records(
        self, parser_input: ParserInput, probe: dict[str, Any]
    ) -> list[dict[str, Any]]:
        records = []
        entity_id = f"tlidb:cn:{parser_input.canonical_id}"
        for index, row in enumerate(probe["rows"]):
            stable_key = f"modifier:{row.stable_key}"
            text = row.cells[1]
            locator = {
                "section_key": self.section_key,
                "dom_id": self.section_dom_id,
                "tab_target": f"#{self.section_dom_id}",
                "row_index": index,
                "stable_key": stable_key,
                "locator_confidence": "high",
                "locator_level": "record",
            }
            records.append(
                {
                    "record_id": make_record_id(
                        parser_id=self.parser_id,
                        entity_id=entity_id,
                        record_type="affix",
                        section_key=self.section_key,
                        stable_key=stable_key,
                    ),
                    "season_id": parser_input.season_id,
                    "entity_id": entity_id,
                    "entity_type": "equipment",
                    "record_type": "affix",
                    "section_id": self.section_key,
                    "section_name": "基础词缀",
                    "text": text,
                    "route": parser_input.canonical_route,
                    "source_system": parser_input.system_id,
                    "source_page_id": parser_input.canonical_id,
                    "source_locator": locator,
                    "source_record_index": index,
                    "parser_id": self.parser_id,
                    "parser_version": self.parser_version,
                }
            )
        return records
