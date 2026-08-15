"""Structured parser for current Talent node cards."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any

from crawler.audit_remaining_talent_structured_dom_v1 import _node_kind, inspect

from ..parser_base import ParserInput, StructuredParser
from ..schema import make_record_id


class TalentNodeParser(StructuredParser):
    parser_id = "talent.nodes"
    parser_version = "1.0.0"

    def probe(self, html: str) -> dict[str, Any]:
        dom = inspect(html)
        nodes = []
        active_panes = [pane for pane in dom["panes"] if pane["active"]]
        if active_panes:
            container_mode = "active_pane"
            container_id = active_panes[0]["id"]
        else:
            container_mode = "root"
            container_id = None
        for index, node in enumerate(dom["nodes"]):
            remainder = node["text"]
            if node["name"] and remainder.startswith(node["name"]):
                remainder = remainder[len(node["name"]):].strip()
            point_match = re.match(r"(?:(\d+)pts\s*)?(\d+)/(\d+)\s*", remainder)
            point_requirement = int(point_match.group(1)) if point_match and point_match.group(1) else None
            allocation_current = int(point_match.group(2)) if point_match else None
            allocation_limit = int(point_match.group(3)) if point_match else None
            effect = remainder[point_match.end():].strip() if point_match else remainder
            nodes.append({
                **node,
                "row_index": index,
                "point_requirement": point_requirement,
                "allocation_current": allocation_current,
                "allocation_limit": allocation_limit,
                "effect": effect,
            })
        ids = [node["talent_id"] for node in nodes]
        descriptor = {
            "container_mode": container_mode,
            "active_pane_count": len(active_panes),
            "node_card_count": dom["current_card_count"],
            "node_count": len(nodes),
            "data_talent_id_count": len(ids),
            "unique_data_talent_id_count": len(set(ids)),
            "empty_effect_count": sum(not node["effect"] for node in nodes),
            "historical_node_count": len(dom["historical_nodes"]),
            "support_pane_count": sum(
                pane["id"] in {"ProfessionTree", "Item"} or "_cache" in pane["id"]
                for pane in dom["panes"]
            ),
            "nested_modifier_node_count": sum(bool(node["modifier_ids"]) for node in nodes),
            "multi_modifier_node_count": sum(len(node["modifier_ids"]) > 1 for node in nodes),
            "filter_count": dom["filter_count"],
        }
        signature = {
            key: descriptor[key] for key in (
                "container_mode", "active_pane_count", "node_count",
                "node_card_count", "data_talent_id_count", "support_pane_count",
                "nested_modifier_node_count", "multi_modifier_node_count", "filter_count",
            )
        }
        return {
            "descriptor": descriptor,
            "nodes": nodes,
            "container_id": container_id,
            "structure_signature": hashlib.sha256(
                json.dumps(signature, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }

    def validate_structure(self, probe: dict[str, Any]) -> dict[str, Any]:
        observed = probe["descriptor"]
        checks = {
            "valid_container": (
                observed["container_mode"] == "root" and observed["active_pane_count"] == 0
            ) or (
                observed["container_mode"] == "active_pane" and observed["active_pane_count"] == 1
            ),
            "nodes_present": observed["node_count"] > 0,
            "data_talent_id_coverage": observed["data_talent_id_count"] == observed["node_card_count"],
            "data_talent_ids_unique": observed["unique_data_talent_id_count"] == observed["node_count"],
            "effects_present": observed["empty_effect_count"] == 0,
            "historical_nodes_excluded": observed["historical_node_count"] == 0,
            "nested_modifier_does_not_split_node": observed["multi_modifier_node_count"] == 0,
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

    def parse_records(self, parser_input: ParserInput, probe: dict[str, Any]) -> list[dict[str, Any]]:
        entity_id = f"tlidb:cn:{parser_input.canonical_id}"
        container_id = probe["container_id"]
        records = []
        for node in probe["nodes"]:
            node_family = (
                "talent_nether_king_entity"
                if probe["descriptor"]["nested_modifier_node_count"] else "talent_hero"
            )
            stable_key = f"talent:{node['talent_id']}"
            view_state = {
                "talent_container": container_id,
                "talent_root": container_id is None,
                "filter_reset": bool(probe["descriptor"]["filter_count"]),
            }
            records.append({
                "record_id": make_record_id(
                    parser_id=self.parser_id, entity_id=entity_id,
                    record_type="talent_node", section_key="talent_nodes",
                    stable_key=stable_key,
                ),
                "season_id": parser_input.season_id,
                "entity_id": entity_id,
                "entity_type": "talent",
                "record_type": "talent_node",
                "section_id": "talent_nodes",
                "section_name": "天赋节点",
                "text": node["effect"],
                "route": parser_input.canonical_route,
                "source_system": parser_input.system_id,
                "source_page_id": parser_input.canonical_id,
                "source_locator": {
                    "section_key": "talent_nodes",
                    "dom_id": container_id or "",
                    "tab_target": f"#{container_id}" if container_id else "",
                    "row_index": node["row_index"],
                    "stable_key": stable_key,
                    "locator_confidence": "high",
                    "locator_level": "record",
                    "view_state": view_state,
                },
                "source_record_index": node["row_index"],
                "parser_id": self.parser_id,
                "parser_version": self.parser_version,
                "identity_confidence": "high",
                "talent_id": node["talent_id"],
                "talent_name": node["name"],
                "node_type": _node_kind(node["name"], node_family),
                "point_requirement": node["point_requirement"],
                "allocation_current": node["allocation_current"],
                "allocation_limit": node["allocation_limit"],
                "board_entity_id": entity_id,
                "nested_modifier_ids": node["modifier_ids"],
            })
        return records
