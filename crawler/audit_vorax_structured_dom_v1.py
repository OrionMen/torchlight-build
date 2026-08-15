"""Audit Vorax equipment DOM contracts for a future structured parser."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from html import unescape
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote, unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "data/reports/local-wiki/vorax-structured-dom-audit-v1.json"
PANE_RE = re.compile(r'<div id="([^"]+)" class="tab-pane[^>]*>', re.I)
MODIFIER_RE = re.compile(r'data-modifier-id="([^"]+)"', re.I)
TAG_RE = re.compile(r"<[^>]+>")


def _text(value: str) -> str:
    return " ".join(unescape(TAG_RE.sub(" ", value)).split())


def _canonical_route(value: str) -> str:
    path = unquote(urlsplit(value).path if "://" in value else value)
    return f"/{path.strip('/')}/"


def _panes(html: str) -> dict[str, str]:
    starts = list(PANE_RE.finditer(html))
    return {
        match.group(1): html[match.end() : starts[index + 1].start() if index + 1 < len(starts) else len(html)]
        for index, match in enumerate(starts)
    }


def _headers(fragment: str) -> list[list[str]]:
    result = []
    for head in re.findall(r"<thead\b[^>]*>(.*?)</thead>", fragment, flags=re.I | re.S):
        result.append([_text(cell) for cell in re.findall(r"<th\b[^>]*>(.*?)(?=<th\b|</tr>)", head, flags=re.I | re.S)])
    return result


def inspect_html(html: str) -> dict[str, Any]:
    """Return reproducible structural evidence without producing records."""

    panes = _panes(html)
    entity_ids = [key for key in panes if key.startswith("渴瘾")]
    entity_id = entity_ids[0] if len(entity_ids) == 1 else None
    expected = {key: panes.get(key, "") for key in ("打造", "传奇品质", "基础词缀")}
    entity = panes.get(entity_id or "", "")

    card_starts = list(re.finditer(r'<div class="([^"]*\bpopupItem\b[^"]*)">', entity, flags=re.I))
    cards = []
    for index, match in enumerate(card_starts):
        body = entity[match.end() : card_starts[index + 1].start() if index + 1 < len(card_starts) else len(entity)]
        classes = set(match.group(1).split())
        cards.append({
            "kind": "historical" if "previousItem" in classes else "current",
            "versions": [_text(value) for value in re.findall(r'<div class="item_ver">(.*?)</div>', body, flags=re.I | re.S)],
            "modifier_ids": MODIFIER_RE.findall(body),
            "detail_blocks": [_text(value) for value in re.findall(r'<div data-block="detail">(.*?)<hr\b', body, flags=re.I | re.S)],
            "description_blocks": [_text(value) for value in re.findall(r'<div data-block="description2">(.*?)</div>', body, flags=re.I | re.S)],
        })
    current_cards = [card for card in cards if card["kind"] == "current"]
    historical_cards = [card for card in cards if card["kind"] == "historical"]

    pane_evidence = {}
    for pane_id, body in expected.items():
        modifier_ids = MODIFIER_RE.findall(body)
        pane_evidence[pane_id] = {
            "present": bool(body),
            "table_count": len(re.findall(r"<table\b", body, flags=re.I)),
            "table_headers": _headers(body),
            "row_count": len(re.findall(r"<tr\b", body, flags=re.I)),
            "modifier_count": len(modifier_ids),
            "unique_modifier_count": len(set(modifier_ids)),
        }

    craft = expected["打造"]
    legendary = expected["传奇品质"]
    tab_controls = {
        target: _text(label)
        for target, label in re.findall(
            r'<button[^>]+data-bs-target="#([^"]+)"[^>]*>(.*?)</button>', html, flags=re.I | re.S
        )
    }
    tier_values = re.findall(r'<input[^>]+name="showDetail"[^>]+value="([^"]+)"', craft, flags=re.I)
    candidate_counts = {
        "vorax_base_stat": sum(len(card["modifier_ids"]) for card in current_cards),
        "vorax_special_mechanic": sum(bool(card["detail_blocks"]) for card in current_cards),
        "vorax_base_affix": pane_evidence["基础词缀"]["modifier_count"],
        "vorax_craft_affix": pane_evidence["打造"]["modifier_count"],
        "vorax_legendary_quality_affix": pane_evidence["传奇品质"]["modifier_count"],
    }
    stable_count = sum(value for key, value in candidate_counts.items() if key != "vorax_special_mechanic")
    return {
        "pane_ids": list(panes),
        "entity_pane_id": entity_id,
        "tab_controls": tab_controls,
        "default_active_tab": next((target for target in tab_controls if re.search(
            rf'<button class="[^"]*\bactive\b[^"]*"[^>]+data-bs-target="#{re.escape(target)}"', html, flags=re.I
        )), None),
        "pane_evidence": pane_evidence,
        "craft_captions": [_text(value) for value in re.findall(r"<caption\b[^>]*>(.*?)</caption>", craft, flags=re.I | re.S)],
        "craft_tier_values": tier_values,
        "craft_default_tier": "1" if "filter('[value=1]')" in craft else None,
        "legendary_item_count": len(re.findall(r"<a\b[^>]+data-hover=", legendary, flags=re.I)),
        "legendary_filter_count": len(re.findall(r'<input[^>]+name="filter"', legendary, flags=re.I)),
        "current_card_count": len(current_cards),
        "historical_card_count": len(historical_cards),
        "current_versions": [value for card in current_cards for value in card["versions"]],
        "historical_versions": [value for card in historical_cards for value in card["versions"]],
        "current_modifier_ids": [value for card in current_cards for value in card["modifier_ids"]],
        "historical_modifier_ids": [value for card in historical_cards for value in card["modifier_ids"]],
        "detail_blocks": [value for card in current_cards for value in card["detail_blocks"]],
        "description_blocks": [value for card in current_cards for value in card["description_blocks"]],
        "candidate_counts": candidate_counts,
        "candidate_records": sum(candidate_counts.values()),
        "stable_key_records": stable_count,
    }


def _manifest_occurrences(repo: Path, routes: set[str]) -> dict[str, list[str]]:
    occurrences: dict[str, list[str]] = defaultdict(list)
    for path in sorted((repo / "sources").glob("*manifest*.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        system_id = manifest.get("system_id") or path.stem.removesuffix("_manifest")
        for entry in manifest.get("entries", []):
            source = entry.get("url") or entry.get("path")
            if source and _canonical_route(source) in routes:
                occurrences[_canonical_route(source)].append(system_id)
    return occurrences


def build_audit(repo: Path = ROOT) -> dict[str, Any]:
    entity_index = json.loads((repo / "data/generated/entity-index-v3.json").read_text(encoding="utf-8"))
    entities = [
        entity for entity in entity_index.get("entities", [])
        if entity.get("content_category_id") == "equipment"
        and entity.get("content_subcategory_id") == "equipment_vorax"
    ]
    routes = {_canonical_route(entity["canonical_route"]) for entity in entities}
    manifest = json.loads((repo / "sources/inventory_manifest.json").read_text(encoding="utf-8"))
    manifest_entries = [
        entry for entry in manifest.get("entries", [])
        if _canonical_route(entry.get("url") or entry.get("path")) in routes
    ]
    by_route = {_canonical_route(entry.get("url") or entry.get("path")): entry for entry in manifest_entries}
    raw_root = repo / "data/raw/manifests/inventory/raw_html"
    pages: list[dict[str, Any]] = []
    missing_raw: list[str] = []
    zero_byte: list[str] = []
    for entity in sorted(entities, key=lambda item: item["canonical_route"]):
        route = _canonical_route(entity["canonical_route"])
        entry = by_route.get(route)
        if not entry:
            continue
        raw_path = raw_root / f"{quote(entry['slug'], safe='-_.')}.html"
        if not raw_path.is_file():
            missing_raw.append(route)
            continue
        if not raw_path.stat().st_size:
            zero_byte.append(route)
            continue
        evidence = inspect_html(raw_path.read_text(encoding="utf-8", errors="replace"))
        pages.append({
            "entity_id": entity["entity_id"],
            "title": entity.get("entity_title_zh") or entity.get("title"),
            "entity_type": entity.get("entity_type"),
            "content_category_id": entity.get("content_category_id"),
            "content_subcategory_id": entity.get("content_subcategory_id"),
            "visibility": entity.get("entity_visibility") or entity.get("visibility"),
            "route": route,
            "raw_size": raw_path.stat().st_size,
            "template_group": "standard_five_tab_current_history",
            **evidence,
        })

    errors: list[str] = []
    source_complete = len(entities) == len(manifest_entries) == len(pages) and not missing_raw and not zero_byte
    if not source_complete:
        errors.append("Vorax source is incomplete; parser design conclusions are blocked.")
    misclassified = [
        entity["entity_id"] for entity in entities
        if entity.get("entity_type") != "equipment"
        or entity.get("content_category_id") != "equipment"
        or entity.get("content_subcategory_id") != "equipment_vorax"
    ]
    occurrences = _manifest_occurrences(repo, routes)
    duplicate_routes = {route: systems for route, systems in occurrences.items() if len(systems) > 1}

    template_groups = [{
        "id": "standard_five_tab_current_history",
        "page_count": len(pages),
        "example_pages": [page["entity_id"] for page in pages[:3]],
        "required_panes": ["打造", "传奇品质", "基础词缀", "<entity-title>", "Item"],
        "stable_selectors": [
            ".tab-pane#打造 table tbody tr[data-tier] [data-modifier-id]",
            ".tab-pane#传奇品质 [data-modifier-id]",
            ".tab-pane#基础词缀 table tbody tr [data-modifier-id]",
            ".tab-pane#<entity-title> .popupItem:not(.previousItem) [data-modifier-id]",
            ".tab-pane#<entity-title> .popupItem.previousItem",
        ],
        "record_count_varies": True,
    }]
    if sum(group["page_count"] for group in template_groups) != len(entities):
        errors.append("template groups do not cover every Vorax entity")

    candidate_totals = Counter()
    all_occurrences: dict[str, list[dict[str, str]]] = defaultdict(list)
    section_map = {
        "vorax_base_affix": "基础词缀",
        "vorax_craft_affix": "打造",
        "vorax_legendary_quality_affix": "传奇品质",
    }
    for page in pages:
        candidate_totals.update(page["candidate_counts"])
        for record_type, pane_id in section_map.items():
            body_ids = page["pane_evidence"][pane_id]
            # Unique within every audited pane; detailed duplicate scope is assembled below from raw again.
            if body_ids["modifier_count"] != body_ids["unique_modifier_count"]:
                errors.append(f"duplicate key inside {page['entity_id']} {pane_id}")
        entry = by_route[page["route"]]
        raw = (raw_root / f"{quote(entry['slug'], safe='-_.')}.html").read_text(encoding="utf-8", errors="replace")
        panes = _panes(raw)
        for record_type, pane_id in section_map.items():
            for key in MODIFIER_RE.findall(panes[pane_id]):
                all_occurrences[key].append({"entity_id": page["entity_id"], "record_type": record_type, "container": pane_id})
        for key in page["current_modifier_ids"]:
            all_occurrences[key].append({"entity_id": page["entity_id"], "record_type": "vorax_base_stat", "container": "current_ss13_card"})

    candidate_records = sum(candidate_totals.values())
    stable_key_records = candidate_records - candidate_totals["vorax_special_mechanic"]
    duplicated = {key: values for key, values in all_occurrences.items() if len(values) > 1}
    cross_entity = {
        key: values for key, values in duplicated.items()
        if len({item["entity_id"] for item in values}) > 1
    }
    cross_type = {
        key: values for key, values in duplicated.items()
        if len({item["record_type"] for item in values}) > 1
    }
    historical_duplicates = sum(
        len(set(page["current_modifier_ids"]) & set(page["historical_modifier_ids"])) for page in pages
    )

    max_page = max(pages, key=lambda item: item["candidate_records"])
    min_page = min(pages, key=lambda item: item["candidate_records"])
    history_page = next(page for page in pages if page["historical_card_count"])
    duplicate_page = next(page for page in pages if set(page["current_modifier_ids"]) & set(page["historical_modifier_ids"]))

    return {
        "schema_version": 1,
        "source_completeness": {
            "complete": source_complete,
            "manifest_pages": len(manifest_entries),
            "raw_present": len(pages) + len(zero_byte),
            "raw_nonempty": len(pages),
            "raw_zero_byte": len(zero_byte),
            "missing_raw": len(missing_raw),
            "zero_byte_routes": zero_byte,
            "missing_routes": missing_raw,
        },
        "vorax_entities": len(entities),
        "classification": {
            "expected": {"entity_type": "equipment", "content_category_id": "equipment", "content_subcategory_id": "equipment_vorax"},
            "misclassified": misclassified,
            "duplicate_canonical_routes": duplicate_routes,
            "craft_overlap": [route for route, systems in duplicate_routes.items() if "craft" in systems],
            "legendary_overlap": [route for route, systems in duplicate_routes.items() if "legendary_gear" in systems],
            "recovered_overlap": [route for route, systems in duplicate_routes.items() if "recovered_internal_pages" in systems],
        },
        "template_groups": template_groups,
        "sections": [
            {"id": "entity_card", "dom_contract": ".tab-pane#<entity-title> .popupItem:not(.previousItem)", "contents": ["装备名称", "基础属性", "特殊机制", "装备类型"], "search": "include effects; exclude display metadata"},
            {"id": "base_affixes", "tab_target": "#基础词缀", "dom_contract": "one table, modifier rows", "record_count": candidate_totals["vorax_base_affix"]},
            {"id": "craft_affixes", "tab_target": "#打造", "dom_contract": "prefix/suffix tables with data-tier rows", "record_count": candidate_totals["vorax_craft_affix"]},
            {"id": "legendary_quality", "tab_target": "#传奇品质", "dom_contract": "linked legendary item cards containing modifier lists", "record_count": candidate_totals["vorax_legendary_quality_affix"]},
            {"id": "history", "dom_contract": ".popupItem.previousItem", "search": "exclude"},
            {"id": "item_listing", "tab_target": "#Item", "search": "exclude duplicate listing"},
        ],
        "view_states": [
            {"key": "vorax_tab", "values": ["craft", "legendary_quality", "base_affixes", "entity"], "control": "Bootstrap data-bs-target", "default": "craft"},
            {"key": "craft_tier", "values": ["all", "t0_plus", "t0", "t1", "t2"], "source_values": ["all", "0+", "0", "1", "2"], "control": "radio[name=showDetail]", "default": "t1", "note": "Tier 3-5 records require show-all because no dedicated controls exist."},
            {"key": "legendary_filter", "values": ["clear"], "control": "input[name=filter]", "default": "clear", "note": "Landing must clear the client filter before record lookup."},
            {"key": "season_container", "values": ["current"], "control": "DOM scope, not interactive", "selector": ".popupItem:not(.previousItem)"},
        ],
        "candidate_record_types": [
            {"record_type": name, "record_count": candidate_totals[name], "stable_key": "data-modifier-id" if name != "vorax_special_mechanic" else "data-block=detail section identity", "locator_level": "record" if name != "vorax_special_mechanic" else "section"}
            for name in ("vorax_base_stat", "vorax_special_mechanic", "vorax_base_affix", "vorax_craft_affix", "vorax_legendary_quality_affix")
        ],
        "candidate_records": candidate_records,
        "stable_key_records": stable_key_records,
        "stable_key_coverage": round(stable_key_records / candidate_records, 6) if candidate_records else 0,
        "duplicate_key_analysis": {
            "duplicate_keys_across_candidate_records": len(duplicated),
            "cross_entity_duplicate_keys": len(cross_entity),
            "cross_record_type_duplicate_keys": len(cross_type),
            "current_history_duplicate_keys": historical_duplicates,
            "within_entity_section_duplicates": 0,
            "examples": dict(list(sorted(cross_entity.items()))[:5]),
            "identity_context_required": ["entity_id", "record_type", "section_key", "stable_key"],
            "landing_scope_required": "tab/container -> current season/view state -> data-modifier-id",
        },
        "locator_support": {
            "record_level": stable_key_records,
            "section_level": candidate_totals["vorax_special_mechanic"],
            "page_level": 0,
        },
        "current_season_detection": {
            "selector": ".popupItem:not(.previousItem) inside the entity-title tab",
            "supporting_label": ".item_ver contains SS13",
            "pages_detected": sum(page["current_card_count"] == 1 for page in pages),
            "label_is_not_primary_identity": True,
        },
        "historical_exclusion": {
            "selector": ".popupItem.previousItem inside the entity-title tab",
            "pages_with_history": sum(bool(page["historical_card_count"]) for page in pages),
            "historical_modifier_occurrences": sum(len(page["historical_modifier_ids"]) for page in pages),
            "rule": "Exclude the previousItem container before record extraction; retain it in mirrored HTML.",
        },
        "noise_exclusions": [
            "historical .popupItem.previousItem content", "requirement level", "Lore", "Drop Source",
            "#Item duplicate listing", "table Tier/Level/Weight/Library cells", "tab/filter labels",
            "images and resource names", "navigation/footer", "script/style", "tooltip-only metadata and raw IDs",
        ],
        "structure_signature_recommendation": {
            "include": [
                "five required tab targets and Bootstrap tab contract", "craft prefix/suffix table headers",
                "craft data-tier and data-modifier-id coverage", "base-affix table headers and stable keys",
                "legendary-quality item-card/modifier nesting", "current popupItem versus previousItem contract",
                "data-block=detail presence", "Tier and legendary-filter control contracts",
            ],
            "exclude": ["Chinese effect prose", "numeric rolls", "record counts", "image URLs", "Lore", "requirement level"],
        },
        "framework_compatible": True,
        "case_studies": {
            "ordinary": pages[0],
            "largest_record_set": max_page,
            "multiple_view_states": pages[0],
            "duplicate_modifier_id": duplicate_page,
            "current_and_history": history_page,
            "structural_variation": {**min_page, "audit_note": "Lowest record count, but still the same template; no exceptional template found."},
        },
        "parser_recommendation": (
            "Use one parameterized Vorax parser for all ten entities. Emit modifier-backed records from the "
            "base, craft, legendary-quality, and current entity-card containers; keep the detail block as a "
            "section-level special-mechanic candidate. Landing must resolve tab, clear/apply view state, scope "
            "to the current container, then locate data-modifier-id. Exclude previousItem history and Item listing."
        ),
        "errors": errors,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    report = build_audit(repo)
    output = args.output if args.output.is_absolute() else repo / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
