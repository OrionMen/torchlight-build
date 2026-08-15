"""Structured parser for the two authorized Ethereal Prism affix tables."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from crawler.audit_ethereal_prism_structured_dom_v1 import inspect_section_rows

from ..parser_base import ParserInput, StructuredParser
from ..schema import make_record_id
from ..structure_probe import probe_section_table


ENTITY_ID = "tlidb:cn:Ethereal_Prism"


@dataclass(frozen=True)
class PrismSectionDefinition:
    section_key: str
    section_name: str
    record_type: str
    headers: tuple[str, ...]
    expected_count: int


SECTIONS = (
    PrismSectionDefinition("base_affixes", "基础词缀", "ethereal_prism_base_affix", ("Modifier",), 33),
    PrismSectionDefinition("random_affixes", "随机词缀", "ethereal_prism_random_affix", ("Modifier", "出现位置"), 358),
)


def _section_fragment(html: str, section_id: str) -> str:
    starts = list(re.finditer(r'<div\s+id="([^"]+)"\s+class="tab-pane[^>]*>', html, re.I))
    for index, match in enumerate(starts):
        if match.group(1) == section_id:
            end = starts[index + 1].start() if index + 1 < len(starts) else len(html)
            return html[match.end():end]
    return ""


class EtherealPrismParser(StructuredParser):
    parser_id = "talent.ethereal_prism.affixes"
    parser_version = "1.0.0"

    def probe(self, html: str) -> dict[str, Any]:
        sections: dict[str, dict[str, Any]] = {}
        signature_payload: dict[str, Any] = {}
        for definition in SECTIONS:
            table_probe = probe_section_table(html, section_id=definition.section_name)
            rows = inspect_section_rows(html, definition.section_name)
            fragment = _section_fragment(html, definition.section_name)
            datatable_count = len(re.findall(r'<table\b[^>]*class=["\'][^"\']*\bDataTable\b', fragment, re.I))
            outer_keys = [row["outer_stable_key"] for row in rows]
            descriptor = {
                **table_probe["descriptor"],
                "datatable_count": datatable_count,
                "outer_stable_key_count": sum(bool(key) for key in outer_keys),
                "outer_unique_key_count": len(set(outer_keys)),
                "rows_with_nested_modifier": sum(bool(row["nested_modifier_ids"]) for row in rows),
            }
            sections[definition.section_key] = {"descriptor": descriptor, "rows": rows}
            signature_payload[definition.section_key] = {
                "section_present": descriptor["section_present"],
                "tab_target_present": descriptor["tab_target_present"],
                "pane_classes": descriptor["section_classes"],
                "datatable_count": datatable_count,
                "headers": descriptor["headers"],
                "row_count": len(rows),
                "outer_stable_key_count": descriptor["outer_stable_key_count"],
                "outer_unique_key_count": descriptor["outer_unique_key_count"],
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
        all_outer: list[str] = []
        for definition in SECTIONS:
            descriptor = probe["sections"][definition.section_key]["descriptor"]
            rows = probe["sections"][definition.section_key]["rows"]
            checks = {
                "section_present": descriptor["section_present"],
                "tab_target_present": descriptor["tab_target_present"],
                "single_datatable": descriptor["datatable_count"] == 1,
                "headers": descriptor["headers"] == list(definition.headers),
                "row_count": len(rows) == definition.expected_count,
                "outer_stable_coverage": descriptor["outer_stable_key_count"] == definition.expected_count,
                "outer_stable_unique": descriptor["outer_unique_key_count"] == definition.expected_count,
            }
            expected[definition.section_key] = {
                "headers": list(definition.headers),
                "row_count": definition.expected_count,
                "checks": sorted(checks),
            }
            observed[definition.section_key] = descriptor
            failed = {key: {"expected": True, "observed": value} for key, value in checks.items() if not value}
            if failed:
                mismatches[definition.section_key] = failed
            all_outer.extend(row["outer_stable_key"] for row in rows)
        if len(set(all_outer)) != len(all_outer):
            mismatches["cross_section_outer_stable_unique"] = {
                "expected": len(all_outer), "observed": len(set(all_outer)),
            }
        return {
            "status": "structure_mismatch" if mismatches else "matched",
            "expected": expected,
            "observed": observed,
            "mismatches": mismatches,
            "warnings": {},
        }

    def parse_records(self, parser_input: ParserInput, probe: dict[str, Any]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for definition in SECTIONS:
            rows = probe["sections"][definition.section_key]["rows"]
            for index, row in enumerate(rows):
                stable_key = f'modifier:{row["outer_stable_key"]}'
                record = {
                    "record_id": make_record_id(
                        parser_id=self.parser_id,
                        entity_id=ENTITY_ID,
                        record_type=definition.record_type,
                        section_key=definition.section_key,
                        stable_key=stable_key,
                    ),
                    "season_id": parser_input.season_id,
                    "entity_id": ENTITY_ID,
                    "entity_type": "talent_system",
                    "record_type": definition.record_type,
                    "section_id": definition.section_key,
                    "section_name": definition.section_name,
                    "text": row["text"],
                    "route": parser_input.canonical_route,
                    "source_system": parser_input.system_id,
                    "source_page_id": parser_input.canonical_id,
                    "source_locator": {
                        "section_key": definition.section_key,
                        "dom_id": definition.section_name,
                        "tab_target": f"#{definition.section_name}",
                        "row_index": index,
                        "stable_key": stable_key,
                        "locator_confidence": "high",
                        "locator_level": "record",
                        "view_state": {
                            "ethereal_prism_section": definition.section_key,
                            "datatable_ready": True,
                        },
                        "outer_modifier_required": True,
                    },
                    "source_record_index": index,
                    "parser_id": self.parser_id,
                    "parser_version": self.parser_version,
                    "identity_confidence": "high",
                    "nested_modifier_ids": row["nested_modifier_ids"],
                }
                if definition.section_key == "random_affixes":
                    record["occurrence_location_text"] = row["source_text"]
                records.append(record)
        return records
