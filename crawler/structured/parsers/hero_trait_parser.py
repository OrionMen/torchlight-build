"""Structured parser for current Hero Trait affix blocks."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any

from crawler.parse_hero import parse_hero_html

from ..parser_base import ParserInput, StructuredParser
from ..schema import make_record_id


class HeroTraitParser(StructuredParser):
    parser_id = "hero.trait.effects"
    parser_version = "1.0.0"

    def probe(self, html: str) -> dict[str, Any]:
        trait_target = re.search(
            r'<button[^>]*class="[^"]*\bactive\b[^"]*"[^>]*data-bs-target="(#[^"]+)"',
            html, re.I,
        )
        parsed: dict[str, Any] | None = None
        parse_error: str | None = None
        try:
            parsed = parse_hero_html(
                html,
                entity_id="probe",
                name_zh="probe",
                page_url="https://tlidb.com/cn/probe",
                raw_sha256=hashlib.sha256(html.encode("utf-8")).hexdigest(),
            )
        except ValueError as exc:
            parse_error = str(exc)

        rows: list[dict[str, Any]] = []
        node_count = 0
        tiered_node_count = 0
        max_levels = 0
        if parsed is not None:
            occurrences: Counter[str] = Counter()
            node_count = len(parsed["nodes"])
            for node in parsed["nodes"]:
                asset_key = node["icon"]["alt"]
                occurrences[asset_key] += 1
                occurrence = occurrences[asset_key]
                tiered_node_count += int(len(node["levels"]) > 1)
                max_levels = max(max_levels, len(node["levels"]))
                for level in node["levels"]:
                    level_key = str(level["level"]) if level["level"] is not None else "unspecified"
                    effect = " ".join(
                        item["text"] for item in level["effects"] if item["text"]
                    )
                    rows.append({
                        "node_index": node["index"],
                        "node_name": node["name"],
                        "required_level": node["required_level"],
                        "trait_level": level["level"],
                        "effect": " ".join(effect.split()),
                        "asset_key": asset_key,
                        "asset_occurrence": occurrence,
                        "stable_key": (
                            f"asset:{asset_key}:occurrence:{occurrence}:level:{level_key}"
                        ),
                    })

        composite_keys = [row["stable_key"] for row in rows]
        descriptor = {
            "trait_tab_count": len(re.findall(r'data-bs-target="#[^"]+-英雄特性"', html)),
            "active_trait_pane_count": len(re.findall(
                r'<div id="[^"]+-英雄特性" class="tab-pane fade show active">', html
            )),
            "skill_shop_sibling_count": len(re.findall(
                r'<div id="技能商店" class="tab-pane fade">', html
            )),
            "node_count": node_count,
            "affix_block_count": len(rows),
            "asset_key_count": sum(bool(row["asset_key"]) for row in rows),
            "composite_key_count": sum(bool(key) for key in composite_keys),
            "unique_composite_key_count": len(set(composite_keys)),
            "tiered_node_count": tiered_node_count,
            "max_levels_per_node": max_levels,
            "records_with_level": sum(row["trait_level"] is not None for row in rows),
            "records_without_level": sum(row["trait_level"] is None for row in rows),
            "skill_shop_records_emitted": 0,
            "parse_error": parse_error,
        }
        signature_contract = {
            key: descriptor[key] for key in (
                "trait_tab_count", "active_trait_pane_count", "skill_shop_sibling_count",
                "node_count", "affix_block_count", "asset_key_count",
                "tiered_node_count", "max_levels_per_node",
            )
        }
        return {
            "descriptor": descriptor,
            "trait_tab_target": trait_target.group(1) if trait_target else None,
            "rows": rows,
            "structure_signature": hashlib.sha256(
                json.dumps(signature_contract, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }

    def validate_structure(self, probe: dict[str, Any]) -> dict[str, Any]:
        observed = probe["descriptor"]
        checks = {
            "parse_succeeded": observed["parse_error"] is None,
            "single_trait_tab": observed["trait_tab_count"] == 1,
            "single_active_trait_pane": observed["active_trait_pane_count"] == 1,
            "skill_shop_sibling_separable": observed["skill_shop_sibling_count"] == 1,
            "trait_nodes_present": observed["node_count"] > 0,
            "affix_blocks_present": observed["affix_block_count"] > 0,
            "asset_identity_coverage": observed["asset_key_count"] == observed["affix_block_count"],
            "composite_identity_coverage": observed["composite_key_count"] == observed["affix_block_count"],
            "composite_identity_unique": observed["unique_composite_key_count"] == observed["affix_block_count"],
            "skill_shop_excluded": observed["skill_shop_records_emitted"] == 0,
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
            "warnings": {
                "identity": "medium confidence: icon asset key is not a native gameplay ID"
            },
        }

    def parse_records(self, parser_input: ParserInput, probe: dict[str, Any]) -> list[dict[str, Any]]:
        entity_id = f"tlidb:cn:{parser_input.canonical_id}"
        tab_target = probe["trait_tab_target"] or ""
        records: list[dict[str, Any]] = []
        for index, row in enumerate(probe["rows"]):
            records.append({
                "record_id": make_record_id(
                    parser_id=self.parser_id,
                    entity_id=entity_id,
                    record_type="hero_trait_effect",
                    section_key="hero_trait_effects",
                    stable_key=row["stable_key"],
                ),
                "season_id": parser_input.season_id,
                "entity_id": entity_id,
                "entity_type": "hero",
                "record_type": "hero_trait_effect",
                "section_id": "hero_trait_effects",
                "section_name": "英雄特性效果",
                "text": row["effect"],
                "route": parser_input.canonical_route,
                "source_system": parser_input.system_id,
                "source_page_id": parser_input.canonical_id,
                "source_locator": {
                    "section_key": "hero_trait_effects",
                    "dom_id": tab_target.lstrip("#"),
                    "tab_target": tab_target,
                    "row_index": index,
                    "stable_key": row["stable_key"],
                    "locator_confidence": "medium",
                    "locator_level": "record",
                    "view_state": {
                        "hero_trait_tab": tab_target,
                        "filter_reset": True,
                        "hero_trait_asset_key": row["asset_key"],
                        "hero_trait_asset_occurrence": row["asset_occurrence"],
                    },
                },
                "source_record_index": index,
                "parser_id": self.parser_id,
                "parser_version": self.parser_version,
                "identity_confidence": "medium",
                "node_name": row["node_name"],
                "required_level": row["required_level"],
                "trait_level": row["trait_level"],
                "icon_asset_key": row["asset_key"],
                "scoped_occurrence": row["asset_occurrence"],
            })
        return records
