"""Structured parser for Pact Spirit contract-node effects."""

from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from typing import Any

from ..parser_base import ParserInput, StructuredParser
from ..schema import make_record_id


VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class PactNodeInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, Any]] = []
        self.blocked_depth = 0
        self.current_node: dict[str, Any] | None = None
        self.current_segment: dict[str, Any] | None = None
        self.nodes: list[dict[str, Any]] = []
        self.node_containers = 0
        self.popup_cards = 0
        self.overview_sections = 0
        self.point_sections = 0
        self.npc_panes = 0
        self.npc_nodes_seen = 0

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs_list)
        classes = set((attrs.get("class") or "").split())
        inactive_npc = (
            tag == "div" and "tab-pane" in classes
            and str(attrs.get("id") or "").endswith("_NPC")
            and not ({"active", "show"} & classes)
        )
        if inactive_npc:
            self.npc_panes += 1
        blocked = self.blocked_depth > 0 or inactive_npc or tag in {"script", "style", "nav", "footer", "table"}
        parent = self.stack[-1] if self.stack else None
        starts_block = bool(inactive_npc or (self.blocked_depth == 0 and tag in {"script", "style", "nav", "footer", "table"}))
        frame = {
            "tag": tag, "blocked": blocked, "node_root": False,
            "segment_root": False, "flex_root": False, "block_increment": starts_block,
        }
        if tag not in VOID:
            self.stack.append(frame)
            self.blocked_depth += int(starts_block)

        if attrs.get("data-src") == "des_effect":
            self.overview_sections += 1
        elif attrs.get("data-src") == "point":
            self.point_sections += 1

        node_container = tag == "div" and {"d-flex", "border", "rounded"} <= classes
        if node_container and blocked:
            self.npc_nodes_seen += 1
        elif node_container:
            self.node_containers += 1
            self.current_node = {"data_id": None, "data_level": None, "segments": []}
            frame["node_root"] = True

        if self.current_node is not None and tag == "img":
            if attrs.get("data-id") is not None:
                self.current_node["data_id"] = attrs.get("data-id")
            if attrs.get("data-level") is not None:
                self.current_node["data_level"] = attrs.get("data-level")

        if self.current_node is not None and tag == "div" and {"flex-grow-1", "ms-2"} <= classes:
            frame["flex_root"] = True
        elif (
            self.current_node is not None and tag == "div" and parent is not None
            and parent.get("flex_root") and not blocked
        ):
            self.current_segment = {"parts": []}
            frame["segment_root"] = True

        if tag == "div" and "popupItem" in classes:
            self.popup_cards += 1

    def handle_data(self, data: str) -> None:
        if self.current_segment is not None and self.blocked_depth == 0:
            self.current_segment["parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] != tag:
                continue
            removed = self.stack[index:]
            del self.stack[index:]
            if self.current_segment and any(frame["segment_root"] for frame in removed):
                value = " ".join(" ".join(self.current_segment["parts"]).split())
                self.current_node["segments"].append(value)
                self.current_segment = None
            if self.current_node and any(frame["node_root"] for frame in removed):
                self.nodes.append(self.current_node)
                self.current_node = None
            self.blocked_depth = max(0, self.blocked_depth - sum(frame["block_increment"] for frame in removed))
            break


class PactSpiritParser(StructuredParser):
    parser_id = "pact.spirit.contract_effects"
    parser_version = "1.0.0"

    def probe(self, html: str) -> dict[str, Any]:
        inspector = PactNodeInspector()
        inspector.feed(html)
        valid = [
            node for node in inspector.nodes
            if node.get("data_id") and node.get("data_level") and len(node.get("segments", [])) >= 2
        ]
        keys = [f'contract:{node["data_id"]}:level:{node["data_level"]}' for node in valid]
        descriptor = {
            "popup_card_count": inspector.popup_cards,
            "overview_section_count": inspector.overview_sections,
            "point_section_count": inspector.point_sections,
            "contract_node_count": inspector.node_containers,
            "valid_node_count": len(valid),
            "stable_key_count": len(keys),
            "unique_stable_key_count": len(set(keys)),
            "inactive_npc_panes": inspector.npc_panes,
            "npc_records_emitted": inspector.npc_nodes_seen,
        }
        signature = {
            "popup_card_count": descriptor["popup_card_count"],
            "overview_section_count": descriptor["overview_section_count"],
            "point_section_count": descriptor["point_section_count"],
            "contract_node_count": descriptor["contract_node_count"],
            "stable_key_coverage": descriptor["stable_key_count"],
            "inactive_npc_panes": descriptor["inactive_npc_panes"],
        }
        return {
            "descriptor": descriptor,
            "nodes": valid,
            "structure_signature": hashlib.sha256(
                json.dumps(signature, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }

    def validate_structure(self, probe: dict[str, Any]) -> dict[str, Any]:
        observed = probe["descriptor"]
        checks = {
            "single_popup_card": observed["popup_card_count"] == 1,
            "overview_present": observed["overview_section_count"] == 1,
            "point_present": observed["point_section_count"] == 1,
            "contract_nodes_present": observed["contract_node_count"] > 0,
            "node_contract_coverage": observed["valid_node_count"] == observed["contract_node_count"],
            "stable_key_coverage": observed["stable_key_count"] == observed["contract_node_count"],
            "stable_key_unique_within_entity": observed["unique_stable_key_count"] == observed["stable_key_count"],
            "npc_records_excluded": observed["npc_records_emitted"] == 0,
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
        records = []
        for index, node in enumerate(probe["nodes"]):
            stable_key = f'contract:{node["data_id"]}:level:{node["data_level"]}'
            name, effect = node["segments"][:2]
            records.append({
                "record_id": make_record_id(
                    parser_id=self.parser_id,
                    entity_id=entity_id,
                    record_type="pact_contract_node_effect",
                    section_key="contract_nodes",
                    stable_key=stable_key,
                ),
                "season_id": parser_input.season_id,
                "entity_id": entity_id,
                "entity_type": "pact_spirit",
                "record_type": "pact_contract_node_effect",
                "section_id": "contract_nodes",
                "section_name": "契约效果",
                "text": f"{name} {effect}".strip(),
                "route": parser_input.canonical_route,
                "source_system": parser_input.system_id,
                "source_page_id": parser_input.canonical_id,
                "source_locator": {
                    "section_key": "contract_nodes",
                    "dom_id": "",
                    "tab_target": "",
                    "row_index": index,
                    "stable_key": stable_key,
                    "locator_confidence": "high",
                    "locator_level": "record",
                    "view_state": {
                        "pact_contract": True,
                        "pact_data_id": node["data_id"],
                        "pact_data_level": node["data_level"],
                    },
                },
                "source_record_index": index,
                "parser_id": self.parser_id,
                "parser_version": self.parser_version,
                "identity_confidence": "high",
                "node_name": name,
                "node_effect": effect,
                "node_context": node["segments"][2] if len(node["segments"]) > 2 else None,
                "contract_data_id": node["data_id"],
                "contract_data_level": node["data_level"],
            })
        return records
