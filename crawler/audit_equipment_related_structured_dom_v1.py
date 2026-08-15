"""Audit equipment-related system pages for future structured parsing.

This module is intentionally read-only: it describes record boundaries, stable
identity, locator feasibility, and noise exclusions without emitting records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


ENTITY_SPECS = {
    "fragrance": {
        "entity_id": "tlidb:cn:Blending_Rituals",
        "page_id": "Blending_Rituals",
        "route": "/cn/Blending_Rituals/",
        "section_id": "调香秘仪",
        "subcategory": "equipment_related_fragrance",
    },
    "tower": {
        "entity_id": "tlidb:cn:TOWER_Sequence",
        "page_id": "TOWER_Sequence",
        "route": "/cn/TOWER_Sequence/",
        "section_id": "高塔序列",
        "subcategory": "equipment_related_tower_sequence",
    },
}


def _clean(parts: list[str]) -> str:
    return " ".join(" ".join(parts).split())


def _signature(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class RelatedSystemInspector(HTMLParser):
    """Capture fragrance cards and tower table rows in approved active panes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, Any]] = []
        self.tabs: dict[str, dict[str, Any]] = {}
        self.sections: dict[str, dict[str, Any]] = {}
        self.fragrance_records: list[dict[str, Any]] = []
        self.tower_records: list[dict[str, Any]] = []
        self._tab: dict[str, Any] | None = None
        self._record: dict[str, Any] | None = None
        self._capture: dict[str, Any] | None = None
        self._anchor: dict[str, Any] | None = None
        self._cell: dict[str, Any] | None = None
        self._headers: list[str] = []
        self._header: dict[str, Any] | None = None
        self._table_depth = 0
        self.fragrance_filter_present = False
        self.tower_datatable_present = False

    def _section(self) -> str | None:
        return next((frame["section"] for frame in reversed(self.stack) if frame["section"]), None)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        inherited = self._section()
        section = attributes.get("id") if attributes.get("id") in {"调香秘仪", "高塔序列"} else inherited
        frame = {"tag": tag, "section": section}
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}:
            self.stack.append(frame)

        target = attributes.get("data-bs-target")
        if tag == "button" and target in {"#调香秘仪", "#高塔序列"}:
            self._tab = {"frame": frame, "target": target, "text": [], "active": "active" in classes}

        if attributes.get("id") in {"调香秘仪", "高塔序列"}:
            self.sections[attributes["id"]] = {
                "classes": sorted(classes),
                "active": "active" in classes and "show" in classes,
            }

        if section == "调香秘仪" and tag == "input" and attributes.get("name") == "filter":
            self.fragrance_filter_present = True
        if section == "高塔序列" and tag == "table":
            self._table_depth += 1
            self.tower_datatable_present = "DataTable" in classes

        if self._record is None and section == "调香秘仪" and tag == "div" and "col" in classes:
            self._record = self._new_record(frame, "fragrance")
        elif self._record is None and section == "高塔序列" and tag == "tr" and self._table_depth:
            self._record = self._new_record(frame, "tower")

        if self._record is not None:
            stable = attributes.get("data-modifier-id")
            if stable:
                self._record["modifier_ids"].append(stable)
                self._capture = {"frame": frame, "kind": "effect", "text": [], "value": stable}
            recipe = attributes.get("data-id")
            if recipe:
                self._record["recipe_ids"].append(recipe)
            chip = attributes.get("data-chip")
            if chip:
                self._record["chips"].append(chip)
                self._capture = {"frame": frame, "kind": "chip", "text": [], "value": chip}
            if tag == "a" and attributes.get("href"):
                self._anchor = {"frame": frame, "href": attributes["href"], "text": []}
            if self._record["kind"] == "tower" and tag == "td":
                self._cell = {"frame": frame, "text": []}
            if self._record["kind"] == "tower" and tag == "th":
                self._header = {"frame": frame, "text": []}

    @staticmethod
    def _new_record(frame: dict[str, Any], kind: str) -> dict[str, Any]:
        return {
            "frame": frame,
            "kind": kind,
            "text": [],
            "modifier_ids": [],
            "recipe_ids": [],
            "chips": [],
            "effect_parts": [],
            "chip_texts": [],
            "links": [],
            "cells": [],
            "br_count": 0,
        }

    def handle_data(self, data: str) -> None:
        if self._tab is not None:
            self._tab["text"].append(data)
        if self._record is not None:
            self._record["text"].append(data)
        if self._capture is not None:
            self._capture["text"].append(data)
        if self._anchor is not None:
            self._anchor["text"].append(data)
        if self._cell is not None:
            self._cell["text"].append(data)
        if self._header is not None:
            self._header["text"].append(data)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br" and self._record is not None:
            self._record["br_count"] += 1

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] != tag:
                continue
            removed = self.stack[index:]
            del self.stack[index:]
            if self._tab and any(frame is self._tab["frame"] for frame in removed):
                self.tabs[self._tab["target"]] = {"text": _clean(self._tab["text"]), "active": self._tab["active"]}
                self._tab = None
            if self._capture and any(frame is self._capture["frame"] for frame in removed):
                target = "effect_parts" if self._capture["kind"] == "effect" else "chip_texts"
                self._record[target].append(_clean(self._capture["text"]))
                self._capture = None
            if self._anchor and any(frame is self._anchor["frame"] for frame in removed):
                self._record["links"].append({"href": self._anchor["href"], "name_zh": _clean(self._anchor["text"])})
                self._anchor = None
            if self._cell and any(frame is self._cell["frame"] for frame in removed):
                self._record["cells"].append(_clean(self._cell["text"]))
                self._cell = None
            if self._header and any(frame is self._header["frame"] for frame in removed):
                self._headers.append(_clean(self._header["text"]))
                self._header = None
            if self._record and any(frame is self._record["frame"] for frame in removed):
                self._finish_record()
            if tag == "table" and self._table_depth:
                self._table_depth -= 1
            break

    def handle_starttag_br(self) -> None:
        pass

    def _finish_record(self) -> None:
        record = self._record
        self._record = None
        if not record["modifier_ids"]:
            return
        record.pop("frame", None)
        record["text"] = _clean(record["text"])
        record["effect"] = "\n".join(filter(None, record.pop("effect_parts")))
        record["chip_text"] = " ".join(filter(None, record.pop("chip_texts")))
        record["modifier_ids"] = list(dict.fromkeys(record["modifier_ids"]))
        record["recipe_ids"] = list(dict.fromkeys(record["recipe_ids"]))
        record["chips"] = list(dict.fromkeys(record["chips"]))
        if record["kind"] == "fragrance":
            type_match = re.search(r"(中型天赋|核心天赋|异香天赋)\s+Lv\.\d+", record["text"])
            record["talent_type"] = type_match.group(1) if type_match else None
            materials = []
            for link in record["links"]:
                match = re.search(rf"{re.escape(link['name_zh'])}\s*x(\d+)", record["text"])
                materials.append({**link, "quantity": int(match.group(1)) if match else None})
            record["materials"] = materials
            self.fragrance_records.append(record)
        else:
            record["equipment_type"] = record["cells"][1] if len(record["cells"]) > 1 else None
            tier_match = re.search(r"(中阶序列|高阶序列)", record["chip_text"])
            record["sequence_tier"] = tier_match.group(1) if tier_match else None
            self.tower_records.append(record)


def inspect_html(html: str) -> dict[str, Any]:
    parser = RelatedSystemInspector()
    parser.feed(html)
    return {
        "tabs": parser.tabs,
        "sections": parser.sections,
        "fragrance_records": parser.fragrance_records,
        "tower_records": parser.tower_records,
        "fragrance_filter_present": parser.fragrance_filter_present,
        "tower_datatable_present": parser.tower_datatable_present,
        "tower_headers": parser._headers,
    }


def _source(repo: Path, page_id: str) -> dict[str, Any]:
    manifest_path = repo / "sources/help_manifest.json"
    raw_path = repo / f"data/raw/manifests/help/raw_html/{page_id}.html"
    meta_path = repo / f"data/raw/manifests/help/meta/{page_id}.meta.json"
    manifest = _load_json(manifest_path)
    entry = next((item for item in manifest.get("entries", []) if item.get("id") == page_id), None)
    meta = _load_json(meta_path) if meta_path.is_file() else {}
    size = raw_path.stat().st_size if raw_path.is_file() else 0
    return {
        "system_id": "help",
        "page_id": page_id,
        "manifest_entry_present": entry is not None,
        "canonical_url": (entry or {}).get("url"),
        "raw_path": str(raw_path.relative_to(repo)),
        "raw_present": raw_path.is_file(),
        "raw_size": size,
        "raw_nonempty": size > 0,
        "meta_present": meta_path.is_file(),
        "http_status": meta.get("http_status"),
        "meta_content_length": meta.get("content_length"),
        "meta_hash_present": bool(meta.get("html_sha256")),
    }


def _entity(repo: Path, spec: dict[str, str]) -> dict[str, Any]:
    index = _load_json(repo / "data/generated/entity-index-v3.json")
    entity = next((item for item in index.get("entities", []) if item.get("entity_id") == spec["entity_id"]), None)
    return {
        "entity_id": spec["entity_id"],
        "present": entity is not None,
        "entity_type": (entity or {}).get("entity_type"),
        "category": (entity or {}).get("content_category_id") or (entity or {}).get("category"),
        "subcategory": (entity or {}).get("content_subcategory_id") or (entity or {}).get("subcategory"),
        "canonical_route": (entity or {}).get("canonical_route"),
        "visibility": (entity or {}).get("entity_visibility"),
    }


def _duplicates(records: list[dict[str, Any]], key) -> dict[str, Any]:
    groups: dict[str, list[int]] = defaultdict(list)
    for index, record in enumerate(records):
        groups[key(record)].append(index)
    duplicates = {value: indexes for value, indexes in groups.items() if value and len(indexes) > 1}
    return {
        "group_count": len(duplicates),
        "record_count": sum(len(indexes) for indexes in duplicates.values()),
        "examples": [{"value": value, "row_indexes": indexes[:8]} for value, indexes in list(duplicates.items())[:5]],
    }


def _case(record: dict[str, Any], page_id: str, route: str, section: str, index: int) -> dict[str, Any]:
    stable = record["modifier_ids"][0]
    return {
        "source_page_id": page_id,
        "route": route,
        "section": section,
        "row_index": index,
        "stable_key": f"modifier:{stable}",
        "text": record["effect"],
        "candidate_fields": {
            "talent_type": record.get("talent_type"),
            "materials": record.get("materials"),
            "sequence_tier": record.get("sequence_tier"),
            "sequence_pattern": (record.get("chips") or [None])[0],
            "equipment_type": record.get("equipment_type"),
        },
        "source_locator": {
            "locator_level": "record",
            "section_key": section,
            "dom_id": section,
            "tab_target": f"#{section}",
            "row_index": index,
            "stable_key": f"modifier:{stable}",
            "selector": f'#{section} [data-modifier-id="{stable}"]',
            "locator_confidence": "high",
        },
    }


def build_report(repo: Path) -> dict[str, Any]:
    sources = {name: _source(repo, spec["page_id"]) for name, spec in ENTITY_SPECS.items()}
    parsed = {}
    for name, source in sources.items():
        parsed[name] = inspect_html((repo / source["raw_path"]).read_text(encoding="utf-8", errors="replace"))
    fragrance = parsed["fragrance"]["fragrance_records"]
    tower = parsed["tower"]["tower_records"]
    entities = {name: _entity(repo, spec) for name, spec in ENTITY_SPECS.items()}

    fragrance_keys = [item["modifier_ids"][0] for item in fragrance]
    fragrance_recipes = [item["recipe_ids"][0] if item["recipe_ids"] else "" for item in fragrance]
    tower_keys = [item["modifier_ids"][0] for item in tower]
    fragrance_types = Counter(item.get("talent_type") for item in fragrance)
    tower_tiers = Counter(item.get("sequence_tier") for item in tower)
    tower_equipment = Counter(item.get("equipment_type") for item in tower)

    multi = max(enumerate(fragrance), key=lambda item: (item[1]["br_count"], len(item[1]["effect"])))
    heavy = max(enumerate(fragrance), key=lambda item: sum(material.get("quantity") or 0 for material in item[1]["materials"]))
    fragrance_type_examples = {}
    for talent_type in ("中型天赋", "核心天赋", "异香天赋"):
        index = next(i for i, item in enumerate(fragrance) if item.get("talent_type") == talent_type)
        fragrance_type_examples[talent_type] = _case(fragrance[index], "Blending_Rituals", "/cn/Blending_Rituals/", "调香秘仪", index)

    def tower_example(predicate) -> dict[str, Any]:
        index = next(i for i, item in enumerate(tower) if predicate(item))
        return _case(tower[index], "TOWER_Sequence", "/cn/TOWER_Sequence/", "高塔序列", index)

    tower_examples = {
        "single_handed": tower_example(lambda item: item.get("equipment_type") in {"爪", "手杖", "单手锤", "单手剑", "单手斧", "匕首", "手枪"}),
        "two_handed": tower_example(lambda item: item.get("equipment_type") in {"双手剑", "双手锤", "双手斧", "弓", "弩", "火炮", "火枪"}),
        "staff": tower_example(lambda item: "法杖" in (item.get("equipment_type") or "") or item.get("equipment_type") == "锡杖"),
        "shield": tower_example(lambda item: "盾" in (item.get("equipment_type") or "")),
        "high_tier": tower_example(lambda item: item.get("sequence_tier") == "高阶序列"),
    }
    duplicate_text = _duplicates(tower, lambda item: item["effect"])
    duplicate_text_sequence = _duplicates(tower, lambda item: f'{item["effect"]}|{(item.get("chips") or [""])[0]}')
    if duplicate_text_sequence["examples"]:
        row = duplicate_text_sequence["examples"][0]["row_indexes"][0]
        tower_examples["duplicate_text"] = _case(tower[row], "TOWER_Sequence", "/cn/TOWER_Sequence/", "高塔序列", row)

    fragrance_shape = {
        "pane": "tab-pane.fade.show.active",
        "record_container": "div.row > div.col",
        "effect_attribute": "data-modifier-id",
        "secondary_attribute": "data-id",
        "talent_type_values": sorted(key for key in fragrance_types if key),
        "materials": "anchor + quantity",
        "filter": parsed["fragrance"]["fragrance_filter_present"],
        "record_count": len(fragrance),
        "stable_key_coverage": len(fragrance_keys) / len(fragrance) if fragrance else 0,
    }
    tower_shape = {
        "pane": "tab-pane.fade.show.active",
        "table_class": "DataTable",
        "headers": parsed["tower"]["tower_headers"],
        "cell_count": 2,
        "effect_attribute": "data-modifier-id",
        "sequence_attribute": "data-chip",
        "record_count": len(tower),
        "stable_key_coverage": len(tower_keys) / len(tower) if tower else 0,
    }
    errors = []
    if not all(source["manifest_entry_present"] and source["raw_nonempty"] for source in sources.values()):
        errors.append("source completeness failed")
    if not all(entity["present"] and entity["entity_type"] == "equipment_related_system" for entity in entities.values()):
        errors.append("entity model mismatch")
    if len(fragrance) != 97 or len(tower) != 408:
        errors.append("record count mismatch")
    if len(set(fragrance_keys)) != len(fragrance) or len(set(tower_keys)) != len(tower):
        errors.append("stable-key collision")

    return {
        "schema_version": 1,
        "audit_id": "equipment-related-structured-dom-audit-v1",
        "source_completeness": sources,
        "entity_model": entities,
        "fragrance_structure": {
            "entity_id": ENTITY_SPECS["fragrance"]["entity_id"],
            "route": ENTITY_SPECS["fragrance"]["route"],
            "section_id": "调香秘仪",
            "tab_target": "#调香秘仪",
            "active_pane": parsed["fragrance"]["sections"].get("调香秘仪"),
            "record_boundary": "one div.row > div.col card containing data-modifier-id",
            "record_count": len(fragrance),
            "talent_type_distribution": dict(fragrance_types),
            "modifier_key_count": len(set(fragrance_keys)),
            "recipe_id_count": len(set(fragrance_recipes)),
            "records_with_recipe_id": sum(bool(item["recipe_ids"]) for item in fragrance),
            "material_link_count": sum(len(item["materials"]) for item in fragrance),
            "filter_present": parsed["fragrance"]["fragrance_filter_present"],
            "structure_signature": _signature(fragrance_shape),
            "structure_descriptor": fragrance_shape,
        },
        "tower_structure": {
            "entity_id": ENTITY_SPECS["tower"]["entity_id"],
            "route": ENTITY_SPECS["tower"]["route"],
            "section_id": "高塔序列",
            "tab_target": "#高塔序列",
            "active_pane": parsed["tower"]["sections"].get("高塔序列"),
            "record_boundary": "one tbody tr with two cells and data-modifier-id",
            "record_count": len(tower),
            "headers": parsed["tower"]["tower_headers"],
            "sequence_tier_distribution": dict(tower_tiers),
            "equipment_type_distribution": dict(tower_equipment),
            "datatable_present": parsed["tower"]["tower_datatable_present"],
            "datatable_config": {"paging": False, "info": False, "autoWidth": False, "order": []},
            "structure_signature": _signature(tower_shape),
            "structure_descriptor": tower_shape,
        },
        "candidate_record_types": [
            {"record_type": "fragrance_affix", "entity_id": ENTITY_SPECS["fragrance"]["entity_id"], "count": len(fragrance), "record_boundary": "fragrance .col card"},
            {"record_type": "tower_sequence_affix", "entity_id": ENTITY_SPECS["tower"]["entity_id"], "count": len(tower), "record_boundary": "tower table row"},
        ],
        "stable_identity": {
            "fragrance": {
                "primary_attribute": "data-modifier-id",
                "secondary_attribute": "data-id",
                "records_with_stable_key": len(fragrance_keys),
                "unique_stable_keys": len(set(fragrance_keys)),
                "coverage": len(fragrance_keys) / len(fragrance) if fragrance else 0,
                "duplicate_stable_keys": len(fragrance_keys) - len(set(fragrance_keys)),
                "duplicate_recipe_ids": len(fragrance_recipes) - len(set(fragrance_recipes)),
                "recommended_identity": "entity_id + record_type + stable_key(modifier id)",
            },
            "tower": {
                "primary_attribute": "data-modifier-id",
                "records_with_stable_key": len(tower_keys),
                "unique_stable_keys": len(set(tower_keys)),
                "coverage": len(tower_keys) / len(tower) if tower else 0,
                "duplicate_stable_keys": len(tower_keys) - len(set(tower_keys)),
                "recommended_identity": "entity_id + record_type + stable_key(modifier id); retain equipment_type and sequence_pattern as identity context/validation",
            },
            "identity_independent_of": ["Chinese description", "numeric values", "material quantities", "season_id"],
        },
        "duplicate_analysis": {
            "fragrance_effect_text": _duplicates(fragrance, lambda item: item["effect"]),
            "tower_effect_text": duplicate_text,
            "tower_effect_and_sequence": duplicate_text_sequence,
            "tower_stable_key": _duplicates(tower, lambda item: item["modifier_ids"][0]),
            "conclusion": "Tower effect text intentionally repeats across equipment types. Modifier ids are unique, while equipment_type and sequence_pattern must remain explicit record fields and locator validation context.",
        },
        "record_fields": {
            "fragrance_affix": {
                "searchable": ["text", "talent_type"],
                "metadata": ["materials(name, route, quantity)", "recipe_id"],
                "not_semantically_parsed": ["numeric values", "conditions", "mechanics"],
            },
            "tower_sequence_affix": {
                "searchable": ["text", "sequence_tier", "sequence_pattern", "equipment_type"],
                "metadata": ["sequence_tier", "sequence_pattern", "equipment_type"],
                "not_semantically_parsed": ["numeric values", "conditions", "mechanics"],
            },
            "search_note": "Searching 弓 should return applicable tower rows because equipment_type is player-facing applicability data; result grouping/limits are a later Search concern.",
        },
        "view_state": {
            "fragrance": {
                "tab_target": "#调香秘仪",
                "filter_control": "[name=filter]",
                "required_state": "activate tab and clear the client filter before record lookup",
                "pagination_api_required": False,
            },
            "tower": {
                "tab_target": "#高塔序列",
                "datatable": True,
                "paging": False,
                "required_state": "activate tab, wait for shown.bs.tab/DataTable initialization, then scope lookup to the table",
                "pagination_api_required": False,
                "draw_event_wait_recommended": True,
            },
        },
        "locator_support": {
            "record_level": len(fragrance) + len(tower),
            "section_level": 0,
            "page_level": 0,
            "record_level_coverage": 1.0 if fragrance and tower else 0,
            "fragrance_selector": '#调香秘仪 [data-modifier-id="<id>"]',
            "tower_selector": '#高塔序列 table.DataTable [data-modifier-id="<id>"]',
            "fallback_order": ["record", "section", "page"],
        },
        "noise_exclusions": {
            "fragrance_whitelist": "only .col cards inside #调香秘仪 containing data-modifier-id",
            "tower_whitelist": "only tbody rows inside #高塔序列 table.DataTable containing data-modifier-id",
            "exclude": [
                "navigation, footer, scripts, styles, and image/resource names",
                "调香秘仪 help prose and filter UI",
                "material names/quantities from default search text (retain as metadata)",
                "高塔序列_cache and 高塔序列-帮助手册 tabs",
                "table headers and DataTables controls",
                "internal IDs as display/search text",
            ],
        },
        "case_studies": {
            "fragrance": {
                **fragrance_type_examples,
                "multi_line_effect": _case(multi[1], "Blending_Rituals", "/cn/Blending_Rituals/", "调香秘仪", multi[0]),
                "heavy_material_requirement": _case(heavy[1], "Blending_Rituals", "/cn/Blending_Rituals/", "调香秘仪", heavy[0]),
            },
            "tower": tower_examples,
        },
        "structure_signature_contract": {
            "fragrance_signature": _signature(fragrance_shape),
            "tower_signature": _signature(tower_shape),
            "on_mismatch": "structure_mismatch; do not emit apparently valid empty records",
            "excluded_from_signature": ["specific effect text", "numeric values", "material quantities"],
        },
        "framework_compatibility": {
            "compatible": True,
            "existing_contracts_reused": ["stable record_id", "source_locator", "structure_signature", "view_state", "record->section->page fallback"],
            "generic_extension_required": False,
            "reason": "Both pages expose unique data-modifier-id keys. Fragrance records remain in DOM after filter reset; Tower DataTables disables paging, so no row-materialization API is required.",
        },
        "parser_recommendation": {
            "implement_parser": True,
            "parser_shape": "one parameterized equipment_related_parser.py with fragrance and tower page profiles; do not create one parser file per record",
            "record_types": ["fragrance_affix", "tower_sequence_affix"],
            "prerequisites": ["strict pane whitelist", "header/record-count/stable-key validation", "filter/DataTable view-state contract"],
            "semantic_parsing": "defer",
        },
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report(args.repo.resolve())
    output = args.output or args.repo / "data/reports/local-wiki/equipment-related-structured-dom-audit-v1.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "errors": report["errors"]}, ensure_ascii=False))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
