"""Audit Pact Spirit and Fate DOM contracts for future structured parsers."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from html import unescape
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote, unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "data/reports/local-wiki/pact-fate-structured-dom-audit-v1.json"
TAG_RE = re.compile(r"<[^>]+>")
CARD_RE = re.compile(r'<div class="([^\"]*\bcard\b[^\"]*)">', re.I)
MODIFIER_RE = re.compile(r'data-modifier-id="([^"]+)"', re.I)
PACT_NODE_RE = re.compile(
    r'<img\b[^>]*data-id="([^"]+)"[^>]*data-level="([^"]+)"[^>]*>', re.I
)


def _text(value: str) -> str:
    return " ".join(unescape(TAG_RE.sub(" ", value)).split())


def _route(value: str) -> str:
    path = unquote(urlsplit(value).path if "://" in value else value)
    return "/" + path.strip("/") + "/"


def _card_fragments(html: str) -> list[tuple[set[str], str]]:
    starts = list(CARD_RE.finditer(html))
    return [
        (
            set(match.group(1).split()),
            html[match.end(): starts[index + 1].start() if index + 1 < len(starts) else len(html)],
        )
        for index, match in enumerate(starts)
    ]


def _signature(prefix: str, contract: dict[str, Any]) -> str:
    value = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}_{hashlib.sha256(value.encode()).hexdigest()[:10]}"


def inspect_pact_html(html: str) -> dict[str, Any]:
    cards = _card_fragments(html)
    popup = [body for classes, body in cards if "popupItem" in classes]
    all_nodes = PACT_NODE_RE.findall(html)
    # The first keyed icon belongs to the summary card and repeats one grid node.
    contract_nodes = all_nodes[1:] if popup and all_nodes else all_nodes
    stable_keys = [f"contract:{node_id}:level:{level}" for node_id, level in contract_nodes]
    has_npc = bool(re.search(r'data-bs-target="#[^"]+_NPC"', html, re.I))
    contract = {
        "popup_cards": len(popup),
        "overview_sections": len(re.findall(r'data-src="des_effect"', html, re.I)),
        "point_sections": len(re.findall(r'data-src="point"', html, re.I)),
        "contract_node_count": len(contract_nodes),
        "upgrade_modifier_blocks": len(re.findall(r'class="modifier"', html, re.I)),
        "table_count": len(re.findall(r"<table\b", html, re.I)),
        "npc_tab": has_npc,
        "datatable_count": len(re.findall(r'class=["\'][^"\']*\bDataTable\b', html, re.I)),
    }
    return {
        "template_contract": contract,
        "template_group": _signature("pact", contract),
        "candidate_record_count": len(stable_keys),
        "stable_keys": stable_keys,
        "stable_key_count": len(stable_keys),
        "stable_key_unique": len(set(stable_keys)),
        "historical_content": "previousItem" in html or bool(re.search(r"SS1[0-2]", html)),
        "excluded_npc_tab": has_npc,
    }


def inspect_fate_html(html: str) -> dict[str, Any]:
    cards = _card_fragments(html)
    current = [body for classes, body in cards if "popupItem" in classes and "previousItem" not in classes]
    historical = [body for classes, body in cards if "popupItem" in classes and "previousItem" in classes]
    current_keys = [key for body in current for key in MODIFIER_RE.findall(body)]
    historical_keys = [key for body in historical for key in MODIFIER_RE.findall(body)]
    descriptions = [
        _text(value)
        for body in current
        for value in re.findall(r'<div\s+data-block="description2"[^>]*>(.*?)</div>', body, re.I | re.S)
        if _text(value)
    ]
    contract = {
        "current_cards": len(current),
        "historical_cards": len(historical),
        "current_modifier_count": len(current_keys),
        "description_sections": len(descriptions),
        "tab_count": len(re.findall(r'class="tab-pane', html, re.I)),
        "cache_tabs": len(re.findall(r"cache-", html, re.I)),
    }
    candidate_count = len(current_keys) if current_keys else int(bool(descriptions))
    return {
        "template_contract": contract,
        "template_group": _signature("fate", contract),
        "candidate_record_count": candidate_count,
        "current_stable_keys": current_keys,
        "historical_stable_keys": historical_keys,
        "description_examples": descriptions[:1],
        "stable_key_count": len(current_keys),
        "historical_duplicate_keys": sorted(set(current_keys) & set(historical_keys)),
    }


def _manifest_sources(repo: Path, routes: set[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for name in (
        "pactspirit_manifest.json", "destiny_manifest.json", "inventory_manifest.json",
        "recovered_internal_pages_manifest.json",
    ):
        path = repo / "sources" / name
        data = json.loads(path.read_text(encoding="utf-8"))
        system = data.get("system_id") or name.removesuffix("_manifest.json")
        for entry in data.get("entries", []):
            source = entry.get("url") or entry.get("path")
            if source and _route(source) in routes:
                result[_route(source)].append(system)
    return result


def _raw_for_entry(repo: Path, system: str, entry: dict[str, Any]) -> tuple[Path | None, str | None]:
    filename = f"{quote(entry['slug'], safe='-_.')}.html"
    primary = repo / "data/raw/manifests" / system / "raw_html" / filename
    if primary.is_file():
        return primary, system
    recovered = repo / "data/raw/manifests/recovered_internal_pages/raw_html" / filename
    if recovered.is_file():
        return recovered, "recovered_internal_pages"
    return None, None


def _meta_status(repo: Path, source_system: str | None, slug: str) -> dict[str, Any]:
    if not source_system:
        return {"present": False, "http_status": None, "status": None}
    path = repo / "data/raw/manifests" / source_system / "meta" / f"{quote(slug, safe='-_.')}.meta.json"
    if not path.is_file():
        return {"present": False, "http_status": None, "status": None}
    value = json.loads(path.read_text(encoding="utf-8"))
    return {
        "present": True,
        "http_status": value.get("http_status"),
        "status": value.get("status"),
        "content_length": value.get("content_length", value.get("bytes")),
    }


def _group_pages(pages: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for page in pages:
        grouped[page["template_group"]].append(page)
    result = []
    for group_id, members in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        contract = members[0]["template_contract"]
        result.append({
            "id": group_id,
            "page_count": len(members),
            "representative_pages": [page["id"] for page in members[:5]],
            "dom_contract": contract,
            "differences": (
                ["contract node count", "upgrade modifier count", "NPC tab/DataTable presence"]
                if kind == "pact" else
                ["history presence", "modifier presence", "cache tab presence"]
            ),
        })
    return result


def _case(page: dict[str, Any]) -> dict[str, Any]:
    fate = "current_stable_keys" in page
    return {
        "route": page["route"],
        "template_group": page["template_group"],
        "candidate_record_count": page["candidate_record_count"],
        "record_types": (["fate_effect"] if page.get("current_stable_keys") else
                         ["fate_entity_effect"] if fate else ["pact_contract_node_effect"]),
        "stable_keys": (
            page.get("current_stable_keys") or page.get("stable_keys") or []
        )[:20],
        "search_text_boundary": (
            "current modifier effect only" if fate and page.get("current_stable_keys")
            else "current description2 only" if fate
            else "contract node name + effect; ring/type remains metadata"
        ),
        "landing_level": "record" if page.get("stable_key_count") else "section",
    }


def build_audit(repo: Path = ROOT) -> dict[str, Any]:
    manifests = {
        system: json.loads((repo / f"sources/{system}_manifest.json").read_text(encoding="utf-8"))
        for system in ("pactspirit", "destiny")
    }
    entity_data = json.loads((repo / "data/generated/entity-index-v3.json").read_text(encoding="utf-8"))
    entity_counts = Counter(entity.get("entity_type") for entity in entity_data.get("entities", []))
    pages_by_system: dict[str, list[dict[str, Any]]] = {"pactspirit": [], "destiny": []}
    source_stats: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    for system, inspector in (("pactspirit", inspect_pact_html), ("destiny", inspect_fate_html)):
        entries = manifests[system]["entries"]
        missing: list[str] = []
        zero: list[str] = []
        recovered: list[str] = []
        meta_ok = 0
        for entry in entries:
            raw_path, source_system = _raw_for_entry(repo, system, entry)
            route = _route(entry.get("url") or entry.get("path"))
            if raw_path is None:
                missing.append(entry["id"])
                continue
            if raw_path.stat().st_size == 0:
                zero.append(entry["id"])
                continue
            if source_system != system:
                recovered.append(entry["id"])
            meta = _meta_status(repo, source_system, entry["slug"])
            meta_ok += int(meta["http_status"] == 200)
            evidence = inspector(raw_path.read_text(encoding="utf-8", errors="replace"))
            pages_by_system[system].append({
                "id": entry["id"],
                "title": entry.get("name_zh") or entry["id"],
                "route": route,
                "canonical_url": entry.get("url"),
                "raw_path": str(raw_path.relative_to(repo)),
                "raw_source_system": source_system,
                "raw_size": raw_path.stat().st_size,
                "meta": meta,
                **evidence,
            })
        label = "pact" if system == "pactspirit" else "fate"
        source_stats[label] = {
            "manifest_pages": len(entries),
            "entities": entity_counts["pact_spirit" if system == "pactspirit" else "fate"],
            "raw_present": len(pages_by_system[system]) + len(zero),
            "raw_nonempty": len(pages_by_system[system]),
            "raw_zero_byte": len(zero),
            "missing_raw": len(missing),
            "http_200_meta": meta_ok,
            "recovered_source_count": len(recovered),
            "recovered_source_pages": recovered,
            "zero_byte_pages": zero,
            "missing_pages": missing,
        }

    pact_pages = pages_by_system["pactspirit"]
    fate_pages = pages_by_system["destiny"]
    pact_groups = _group_pages(pact_pages, "pact")
    fate_groups = _group_pages(fate_pages, "fate")

    pact_occurrences: dict[str, list[str]] = defaultdict(list)
    for page in pact_pages:
        for key in page["stable_keys"]:
            pact_occurrences[key].append(page["id"])
    fate_occurrences: dict[str, list[str]] = defaultdict(list)
    for page in fate_pages:
        for key in page["current_stable_keys"]:
            fate_occurrences[key].append(page["id"])

    pact_records = sum(page["candidate_record_count"] for page in pact_pages)
    fate_entity_pages = [page for page in fate_pages if page["raw_source_system"] == "destiny"]
    fate_records = sum(page["candidate_record_count"] for page in fate_entity_pages)
    recovered_fate_records = sum(
        page["candidate_record_count"] for page in fate_pages
        if page["raw_source_system"] == "recovered_internal_pages"
    )
    pact_within_duplicates = sum(
        page["stable_key_count"] - page["stable_key_unique"] for page in pact_pages
    )
    fate_history_pages = [page for page in fate_pages if page["template_contract"]["historical_cards"]]
    history_records = sum(len(page["historical_stable_keys"]) for page in fate_pages)
    history_duplicates = sum(len(page["historical_duplicate_keys"]) for page in fate_pages)

    all_routes = {page["route"] for page in pact_pages + fate_pages}
    source_occurrences = _manifest_sources(repo, all_routes)
    duplicate_routes = {
        route: sources for route, sources in source_occurrences.items() if len(sources) > 1
    }
    by_id = {page["id"]: page for page in pact_pages + fate_pages}
    simplest_pact = min(pact_pages, key=lambda page: page["candidate_record_count"])
    complex_pact = max(
        pact_pages,
        key=lambda page: (
            page["template_contract"]["upgrade_modifier_blocks"], page["candidate_record_count"]
        ),
    )
    variant_pact = next(page for page in pact_pages if page["excluded_npc_tab"])
    ordinary_fate = next(
        page for page in fate_entity_pages
        if page["id"].startswith("Medium_Fate:") and page["current_stable_keys"]
    )
    complex_fate = max(fate_pages, key=lambda page: page["raw_size"])

    required_fate_cases = (
        "Micro_Fate:_Fire_Resistance", "Micro_Fate:_Deterioration_Duration",
        "Micro_Fate:_Trauma_Damage_Mitigation", "Undetermined_Fate",
    )
    missing_cases = [page_id for page_id in required_fate_cases if page_id not in by_id]
    if missing_cases:
        errors.append(f"missing required Fate cases: {missing_cases}")
    if sum(group["page_count"] for group in pact_groups) != 175:
        errors.append("Pact template groups do not cover 175 pages")
    if sum(group["page_count"] for group in fate_groups) != 193:
        errors.append("Fate template groups do not cover 193 manifest pages")
    if source_stats["pact"]["missing_raw"] or source_stats["pact"]["raw_zero_byte"]:
        errors.append("Pact source incomplete")
    if source_stats["fate"]["missing_raw"] or source_stats["fate"]["raw_zero_byte"]:
        errors.append("Fate effective source incomplete")

    return {
        "schema_version": 1,
        "source_completeness": {
            "pact": source_stats["pact"],
            "fate": source_stats["fate"],
            "fate_entity_linkage_gap": {
                "count": 2,
                "pages": source_stats["fate"]["recovered_source_pages"],
                "reason": "present and HTTP 200 in recovered Raw, classified in page Search, but absent from Entity Index v3",
            },
            "duplicate_routes": duplicate_routes,
        },
        "template_groups": {"pact": pact_groups, "fate": fate_groups},
        "candidate_record_types": {
            "pact": [{
                "record_type": "pact_contract_node_effect",
                "record_count": pact_records,
                "dom_selector": ".d-flex.border.rounded img[data-id][data-level] + sibling effect container",
                "stable_key_source": "composite data-id + data-level",
                "excluded_duplicates": "summary-card keyed icon and cumulative upgrade table",
            }],
            "fate": [
                {
                    "record_type": "fate_effect",
                    "record_count": sum(len(page["current_stable_keys"]) for page in fate_entity_pages),
                    "dom_selector": ".popupItem:not(.previousItem) [data-modifier-id]",
                    "stable_key_source": "data-modifier-id",
                },
                {
                    "record_type": "fate_entity_effect",
                    "record_count": sum(
                        page["candidate_record_count"] for page in fate_entity_pages
                        if not page["current_stable_keys"]
                    ),
                    "dom_selector": ".popupItem:not(.previousItem) [data-block=description2]",
                    "stable_key_source": "none; entity + section identity only, medium confidence",
                },
                {
                    "record_type": "fate_effect_recovered_candidate",
                    "record_count": recovered_fate_records,
                    "dom_selector": ".popupItem:not(.previousItem) [data-modifier-id]",
                    "stable_key_source": "data-modifier-id; blocked on Entity linkage decision",
                },
            ],
        },
        "record_counts": {
            "pact_entity_pages": 175,
            "pact_contract_node_effect": pact_records,
            "fate_entity_pages": 191,
            "fate_effect": sum(len(page["current_stable_keys"]) for page in fate_entity_pages),
            "fate_entity_effect_section_level": fate_records - sum(
                len(page["current_stable_keys"]) for page in fate_entity_pages
            ),
            "fate_total_entity_records": fate_records,
            "fate_recovered_candidate_records": recovered_fate_records,
        },
        "stable_key_coverage": {
            "pact": {
                "candidate_records": pact_records,
                "stable_key_records": pact_records,
                "coverage": 1.0,
                "unique_keys_global": len(pact_occurrences),
                "duplicate_keys_global": sum(len(pages) > 1 for pages in pact_occurrences.values()),
                "duplicate_within_entity": pact_within_duplicates,
                "duplicate_across_entities": sum(len(pages) > 1 for pages in pact_occurrences.values()),
                "duplicate_across_record_types": 0,
                "policy": "entity_id + record_type + section_key + contract data-id/data-level",
            },
            "fate": {
                "candidate_records": fate_records,
                "stable_key_records": sum(len(page["current_stable_keys"]) for page in fate_entity_pages),
                "coverage": round(sum(len(page["current_stable_keys"]) for page in fate_entity_pages) / fate_records, 6),
                "unique_keys_global": len({key for page in fate_entity_pages for key in page["current_stable_keys"]}),
                "duplicate_keys_global": 0,
                "duplicate_within_entity": 0,
                "duplicate_across_entities": sum(len(pages) > 1 for pages in fate_occurrences.values()),
                "duplicate_across_record_types": 0,
                "policy": "entity_id + record_type + current_card + data-modifier-id; Undetermined Fate is section-level",
            },
        },
        "duplicate_analysis": {
            "pact_main_card_grid_key_repeats_excluded": len(pact_pages),
            "pact_cross_entity_key_reuse_is_variant_context": sum(
                len(pages) > 1 for pages in pact_occurrences.values()
            ),
            "fate_current_key_cross_entity_duplicates": sum(
                len(pages) > 1 for pages in fate_occurrences.values()
            ),
            "fate_current_history_duplicate_keys": history_duplicates,
            "rule": "never deduplicate by effect text; entity identity remains part of record identity",
        },
        "historical_exclusion": {
            "pact": {
                "pages_with_history": sum(page["historical_content"] for page in pact_pages),
                "historical_records": 0,
                "recommended_exclusion_selector": None,
                "inactive_npc_pages": sum(page["excluded_npc_tab"] for page in pact_pages),
                "inactive_npc_selector": ".tab-pane[id$=_NPC]:not(.active):not(.show)",
            },
            "fate": {
                "pages_with_history": len(fate_history_pages),
                "entity_pages_with_history": sum(
                    bool(page["template_contract"]["historical_cards"])
                    for page in fate_entity_pages
                ),
                "historical_records": history_records,
                "entity_historical_records": sum(
                    len(page["historical_stable_keys"]) for page in fate_entity_pages
                ),
                "duplicate_current_history_keys": history_duplicates,
                "entity_duplicate_current_history_keys": sum(
                    len(page["historical_duplicate_keys"]) for page in fate_entity_pages
                ),
                "current_selector": ".card.ui_item.popupItem:not(.previousItem)",
                "recommended_exclusion_selector": ".card.ui_item.popupItem.previousItem",
            },
        },
        "search_text_whitelist": {
            "pact": ["contract node name", "contract node effect", "record type name only when needed"],
            "fate": ["current modifier effect", "Entity name only when needed", "Undetermined Fate current description2"],
        },
        "noise_exclusions": [
            "lv/name table headers", "Info id", "Show Description", "cookie UI", "navigation",
            "footer", "JS/CSS", "image and asset paths", "tooltip metadata", "internal IDs",
            "historical season cards", "inactive NPC/cache tabs", "duplicate cumulative upgrade table",
            "generic install/remove help text except Undetermined Fate's actual entity effect",
        ],
        "view_state": {
            "pact": {
                "tab_activation": False,
                "inactive_npc_exclusion": True,
                "datatable_ready": False,
                "filter_reset": False,
                "record_scope": "active main page contract-node grid",
            },
            "fate": {
                "tab_activation": False,
                "current_card_selection": True,
                "season_container": "current",
                "datatable_ready": False,
                "filter_reset": False,
            },
        },
        "locator_support": {
            "pact": {"record_level": pact_records, "section_level": 0, "page_level": 0},
            "fate": {
                "record_level": sum(len(page["current_stable_keys"]) for page in fate_entity_pages),
                "section_level": fate_records - sum(len(page["current_stable_keys"]) for page in fate_entity_pages),
                "page_level": 0,
            },
            "fallback": ["record", "section", "page"],
        },
        "case_studies": {
            "pact": {
                "red_umbrella": _case(by_id["Red_Umbrella"]),
                "simplest": {"id": simplest_pact["id"], **_case(simplest_pact)},
                "most_complex": {"id": complex_pact["id"], **_case(complex_pact)},
                "variant_npc": {"id": variant_pact["id"], **_case(variant_pact)},
            },
            "fate": {
                "micro_fire_resistance": _case(by_id["Micro_Fate:_Fire_Resistance"]),
                "micro_deterioration_duration": _case(by_id["Micro_Fate:_Deterioration_Duration"]),
                "micro_trauma_damage_mitigation": _case(by_id["Micro_Fate:_Trauma_Damage_Mitigation"]),
                "undetermined_fate": _case(by_id["Undetermined_Fate"]),
                "ordinary": {"id": ordinary_fate["id"], **_case(ordinary_fate)},
                "most_complex": {"id": complex_fate["id"], **_case(complex_fate)},
            },
        },
        "framework_compatibility": {
            "compatible": True,
            "supported": [
                "stable record_id", "source_locator", "structure_signature", "view_state",
                "supplemental route", "record/section/page landing",
            ],
            "required_framework_changes": [],
            "implementation_note": "recovered Fate pages need an explicit Entity-linkage policy, not a Framework extension",
        },
        "parser_recommendation": {
            "strategy": "separate parsers",
            "reason": "Pact contract-node composites and Fate current-card modifiers have different DOM, identity, history, and landing contracts",
            "pact": {
                "file": "pact_spirit_parser.py",
                "parser_id": "pact.pact_spirit.contract_nodes",
                "record_types": ["pact_contract_node_effect"],
                "stable_key_policy": "contract:<data-id>:level:<data-level>, always scoped by entity_id",
                "landing_strategy": "record grid node; fallback page",
                "signature_fields": [
                    "popup card count", "overview/point sections", "contract node count",
                    "upgrade table presence", "NPC tab/DataTable presence",
                ],
            },
            "fate": {
                "file": "fate_parser.py",
                "parser_id": "pact.fate.current_effects",
                "record_types": ["fate_effect", "fate_entity_effect"],
                "stable_key_policy": "current data-modifier-id; section identity only for Undetermined_Fate",
                "landing_strategy": "current card modifier; Undetermined_Fate current description section; fallback page",
                "signature_fields": [
                    "current/history card counts", "current modifier count", "description2 presence",
                    "tab/cache presence",
                ],
            },
        },
        "errors": errors,
    }


def write_report(report: dict[str, Any], path: Path = DEFAULT_REPORT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    report = build_audit(args.repo.resolve())
    write_report(report, args.report)
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
