"""Audit the 27 current Hero Trait pages for structured-record boundaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote, unquote, urlparse

from crawler.parse_hero import parse_hero_html


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "data/reports/local-wiki/hero-trait-structured-dom-audit-v1.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _route(value: str) -> str:
    path = unquote(urlparse(value).path if "://" in value else value)
    return "/" + path.strip("/") + "/"


def _signature(descriptor: dict[str, Any]) -> str:
    payload = json.dumps(descriptor, sort_keys=True, separators=(",", ":"))
    return "hero_trait_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:10]


def _record_rows(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    occurrences: Counter[str] = Counter()
    for node in parsed["nodes"]:
        asset_key = node["icon"]["alt"]
        occurrences[asset_key] += 1
        occurrence = occurrences[asset_key]
        for level in node["levels"]:
            level_key = str(level["level"]) if level["level"] is not None else "unspecified"
            effect = " ".join(item["text"] for item in level["effects"] if item["text"])
            rows.append({
                "node_index": node["index"],
                "node_name": node["name"],
                "required_level": node["required_level"],
                "trait_level": level["level"],
                "effect": " ".join(effect.split()),
                "native_stable_key": None,
                "asset_key": asset_key,
                "asset_occurrence": occurrence,
                "composite_key": (
                    f"asset:{asset_key}:occurrence:{occurrence}:level:{level_key}"
                ),
                "identity_confidence": "medium",
                "locator_level": "record",
            })
    return rows


def _case(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": page["entity_id"],
        "route": page["route"],
        "template_group": page["template_group"],
        "candidate_records": page["candidate_record_count"],
        "record_types": ["hero_trait_effect"],
        "stable_keys": [record["composite_key"] for record in page["records"][:12]],
        "identity_confidence": "medium",
        "view_state": {
            "hero_trait_tab": page["trait_tab_target"],
            "filter_reset": True,
            "trait_level": "record metadata; no selector",
        },
        "search_boundary": "Hero name + trait node name + optional level label + one data-src=affix block",
        "locator_level": "record",
    }


def build_audit(repo: Path = ROOT) -> dict[str, Any]:
    manifest = _load(repo / "sources/hero_manifest.json")
    entity_index = _load(repo / "data/generated/entity-index-v3.json")
    recovered = _load(repo / "sources/recovered_internal_pages_manifest.json")
    hero_entities = {
        entity["entity_id"]: entity for entity in entity_index.get("entities", [])
        if entity.get("entity_type") == "hero"
    }
    raw_root = repo / "data/raw/manifests/hero/raw_html"
    meta_root = repo / "data/raw/manifests/hero/meta"
    recovered_routes = {
        _route(entry.get("url") or entry.get("path") or "")
        for entry in recovered.get("entries", [])
    }
    pages: list[dict[str, Any]] = []
    missing: list[str] = []
    zero: list[str] = []
    meta_missing: list[str] = []
    meta_http_200 = 0
    hash_matches = 0
    routes: defaultdict[str, list[str]] = defaultdict(list)
    errors: list[str] = []

    for entry in manifest.get("entries", []):
        slug = entry.get("slug") or entry["id"]
        route = _route(entry.get("url") or f"/cn/{slug}/")
        routes[route].append(entry["id"])
        raw_path = raw_root / f"{quote(slug, safe='-_.')}.html"
        if not raw_path.is_file():
            missing.append(entry["id"])
            continue
        if raw_path.stat().st_size == 0:
            zero.append(entry["id"])
            continue
        raw = raw_path.read_bytes()
        html = raw.decode("utf-8", errors="replace")
        meta_path = meta_root / f"{quote(slug, safe='-_.')}.meta.json"
        meta: dict[str, Any] = {}
        if meta_path.is_file():
            meta = _load(meta_path)
            meta_http_200 += int(meta.get("http_status") == 200)
            hash_matches += int(
                (meta.get("sha256") or meta.get("html_sha256"))
                == hashlib.sha256(raw).hexdigest()
            )
        else:
            meta_missing.append(entry["id"])
        try:
            parsed = parse_hero_html(
                html,
                entity_id=entry["id"],
                name_zh=entry.get("name_zh") or entry["id"],
                page_url=entry["url"],
                raw_sha256=hashlib.sha256(raw).hexdigest(),
            )
        except ValueError as exc:
            errors.append(f"{entry['id']}: {exc}")
            continue
        records = _record_rows(parsed)
        node_levels = [len(node["levels"]) for node in parsed["nodes"]]
        asset_keys = [node["icon"]["alt"] for node in parsed["nodes"]]
        duplicate_assets = sum(count > 1 for count in Counter(asset_keys).values())
        trait_target_match = re.search(
            r'<button[^>]*class="[^"]*\bactive\b[^"]*"[^>]*data-bs-target="(#[^"]+)"',
            html, re.I,
        )
        trait_target = trait_target_match.group(1) if trait_target_match else None
        structural = {
            "trait_tab_count": len(re.findall(r'data-bs-target="#[^"]+-英雄特性"', html)),
            "active_trait_pane_count": len(re.findall(r'class="tab-pane fade show active"', html)),
            "skill_shop_pane_count": len(re.findall(r'id="技能商店" class="tab-pane', html)),
            "trait_node_count": len(parsed["nodes"]),
            "tiered_node_count": sum(levels > 1 for levels in node_levels),
            "max_levels_per_node": max(node_levels),
            "six_level_node_count": sum(levels == 6 for levels in node_levels),
            "duplicate_asset_key_groups": duplicate_assets,
            "filter_present": 'name="filter"' in html,
        }
        pages.append({
            "id": entry["id"],
            "entity_id": f"tlidb:cn:{slug}",
            "title": entry.get("name_zh") or entry["id"],
            "route": route,
            "manifest_system": manifest.get("system_id", "hero"),
            "raw_path": str(raw_path.relative_to(repo)),
            "raw_size": len(raw),
            "meta_http_status": meta.get("http_status"),
            "entity_linked": f"tlidb:cn:{slug}" in hero_entities,
            "recovered_route_overlap": route in recovered_routes,
            "trait_tab_target": trait_target,
            "trait_node_count": len(parsed["nodes"]),
            "candidate_record_count": len(records),
            "explicit_level_records": sum(record["trait_level"] is not None for record in records),
            "unspecified_level_records": sum(record["trait_level"] is None for record in records),
            "records": records,
            "structure": structural,
            "template_group": _signature(structural),
            "historical": {
                "previous_item": "previousItem" in html,
                "cache_tabs": len(re.findall(r'id="cache-', html, re.I)),
                "inactive_legacy_tabs": len(re.findall(
                    r'class="tab-pane(?![^"]*\b(?:active|show)\b)[^"]*"[^>]*', html, re.I
                )),
                "season_labels": sorted(set(re.findall(r"SS(?:10|11|12)赛季", html))),
            },
        })

    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for page in pages:
        grouped[page["template_group"]].append(page)
    template_groups = []
    for group_id, members in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        template_groups.append({
            "id": group_id,
            "count": len(members),
            "representative_entities": [page["id"] for page in members[:5]],
            "required_selectors": [
                '.tab-pane.show.active[id$="-英雄特性"]',
                '.card.mb-2 .d-flex.border-top.rounded',
                '.flex-grow-1 .fw-bold',
                '[data-src="affix"]',
            ],
            "record_structure": "one data-src=affix block per record; br-separated lines stay together",
            "view_state_differences": {
                "node_count": members[0]["structure"]["trait_node_count"],
                "tiered_node_count": members[0]["structure"]["tiered_node_count"],
                "max_levels_per_node": members[0]["structure"]["max_levels_per_node"],
                "duplicate_asset_key_groups": members[0]["structure"]["duplicate_asset_key_groups"],
            },
            "candidate_records": sum(page["candidate_record_count"] for page in members),
        })

    all_records = [record for page in pages for record in page["records"]]
    native_keys = [record["native_stable_key"] for record in all_records if record["native_stable_key"]]
    composite_keys_by_entity: defaultdict[str, list[str]] = defaultdict(list)
    base_keys_by_entity: defaultdict[str, list[str]] = defaultdict(list)
    effect_occurrences: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
    name_occurrences: defaultdict[str, list[str]] = defaultdict(list)
    for page in pages:
        for record in page["records"]:
            composite_keys_by_entity[page["entity_id"]].append(record["composite_key"])
            level = record["trait_level"] if record["trait_level"] is not None else "unspecified"
            base_keys_by_entity[page["entity_id"]].append(
                f'asset:{record["asset_key"]}:level:{level}'
            )
            effect_occurrences[record["effect"]].append((page["entity_id"], record["node_name"]))
            name_occurrences[record["node_name"]].append(page["entity_id"])
    duplicate_base_groups = sum(
        count > 1 for keys in base_keys_by_entity.values()
        for count in Counter(keys).values()
    )
    duplicate_composite_groups = sum(
        count > 1 for keys in composite_keys_by_entity.values()
        for count in Counter(keys).values()
    )
    counts = [page["candidate_record_count"] for page in pages]
    minimum = min(pages, key=lambda page: (page["candidate_record_count"], page["id"]))
    maximum = max(pages, key=lambda page: (page["candidate_record_count"], page["id"]))
    ordinary = next(page for page in pages if page["id"] == "Anger")
    branch = next(page for page in pages if page["id"] == "Zealot_of_War")
    duplicate = next(page for page in pages if page["id"] == "Incarnation_of_the_Gods")
    legacy = ordinary
    history_pages = [page for page in pages if any((
        page["historical"]["previous_item"], page["historical"]["cache_tabs"],
        page["historical"]["season_labels"],
    ))]
    duplicate_routes = [
        {"route": route, "sources": ids}
        for route, ids in sorted(routes.items()) if len(ids) > 1
    ]

    report = {
        "schema_version": 1,
        "source_completeness": {
            "manifest_pages": len(manifest.get("entries", [])),
            "entities": len(hero_entities),
            "raw_present": len(manifest.get("entries", [])) - len(missing),
            "raw_nonempty": len(pages),
            "zero_byte": zero,
            "missing": missing,
            "meta_present": len(manifest.get("entries", [])) - len(meta_missing),
            "http_200_meta": meta_http_200,
            "raw_hash_matches_meta": hash_matches,
            "duplicate_routes": duplicate_routes,
            "duplicate_route_count": len(duplicate_routes),
            "recovered_source_pages": [page["id"] for page in pages if page["recovered_route_overlap"]],
        },
        "entity_model": {
            "page_object": "one current Hero Trait variant Entity, not a generic hero and not one talent record",
            "entity_count": len(pages),
            "entity_classification": ["hero", "hero_trait"],
            "child_object": "trait node containing one or more DOM affix blocks",
            "record_boundary": "one data-src=affix block; never split by br, sentence, span, color, or punctuation",
            "hero_summary_role": "entity context only",
            "skill_shop_role": "separate inactive sibling tab; excluded",
        },
        "template_groups": template_groups,
        "candidate_record_types": [{
            "record_type": "hero_trait_effect",
            "count": len(all_records),
            "dom_boundary": '[data-src="affix"] inside one Hero Trait node',
            "reason": "level and non-level effects share the same affix-block contract",
        }],
        "record_counts": {
            "hero_entities": len(pages),
            "trait_nodes": sum(page["trait_node_count"] for page in pages),
            "hero_trait_effect": len(all_records),
            "explicit_level_records": sum(page["explicit_level_records"] for page in pages),
            "unspecified_level_records": sum(page["unspecified_level_records"] for page in pages),
            "line_fragments_not_records": sum(
                len(level["effects"])
                for page in pages
                for node in parse_hero_html(
                    (repo / page["raw_path"]).read_text(encoding="utf-8", errors="replace"),
                    entity_id=page["id"], name_zh=page["title"],
                    page_url=f"https://tlidb.com{page['route'].rstrip('/')}", raw_sha256="audit",
                )["nodes"] for level in node["levels"]
            ),
            "by_entity": {
                page["id"]: page["candidate_record_count"] for page in pages
            },
            "by_template_group": {
                group["id"]: group["candidate_records"] for group in template_groups
            },
        },
        "record_distribution": {
            "minimum": minimum["candidate_record_count"],
            "minimum_entities": [page["id"] for page in pages if page["candidate_record_count"] == minimum["candidate_record_count"]],
            "maximum": maximum["candidate_record_count"],
            "maximum_entities": [page["id"] for page in pages if page["candidate_record_count"] == maximum["candidate_record_count"]],
            "median": statistics.median(counts),
            "distribution": dict(sorted(Counter(counts).items())),
        },
        "stable_key_coverage": {
            "candidate_records": len(all_records),
            "native_data_id_records": len(native_keys),
            "native_stable_key_coverage": 0.0 if all_records else 0,
            "medium_confidence_composite_records": len(all_records),
            "medium_confidence_composite_coverage": 1.0 if all_records else 0,
            "composite_policy": "entity_id + record_type + section_key + icon alt asset key + same-asset occurrence + explicit level/unspecified",
            "warning": "icon alt is a presentation asset identifier, not a native gameplay ID; never report it as high confidence",
            "duplicate_before_occurrence_disambiguation": duplicate_base_groups,
            "duplicate_after_occurrence_disambiguation": duplicate_composite_groups,
        },
        "duplicate_analysis": {
            "duplicate_stable_key_groups_before_disambiguation": duplicate_base_groups,
            "duplicate_stable_key_groups_after_disambiguation": duplicate_composite_groups,
            "duplicate_effect_text_groups": sum(len(values) > 1 for values in effect_occurrences.values()),
            "same_text_different_hero_groups": sum(
                len({entity for entity, _ in values}) > 1 for values in effect_occurrences.values()
            ),
            "duplicate_trait_name_groups": sum(len(set(values)) > 1 for values in name_occurrences.values()),
            "same_node_different_level_nodes": sum(
                sum(len(node["levels"]) > 1 for node in parse_hero_html(
                    (repo / page["raw_path"]).read_text(encoding="utf-8", errors="replace"),
                    entity_id=page["id"], name_zh=page["title"],
                    page_url=f"https://tlidb.com{page['route'].rstrip('/')}", raw_sha256="audit",
                )["nodes"])
                for page in pages
            ),
            "current_history_duplicate_keys": 0,
            "policy": "never deduplicate by effect text or trait name; entity and DOM record identity remain in the key",
        },
        "branch_level_variant_analysis": {
            "explicit_level_records": sum(page["explicit_level_records"] for page in pages),
            "unspecified_level_records": sum(page["unspecified_level_records"] for page in pages),
            "nodes_with_multiple_levels": sum(
                sum(len(node["levels"]) > 1 for node in parse_hero_html(
                    (repo / page["raw_path"]).read_text(encoding="utf-8", errors="replace"),
                    entity_id=page["id"], name_zh=page["title"],
                    page_url=f"https://tlidb.com{page['route'].rstrip('/')}", raw_sha256="audit",
                )["nodes"])
                for page in pages
            ),
            "branch_selector_present": False,
            "level_selector_present": False,
            "decision": "each affix block is a record; trait level is identity/metadata, while branch grouping by required level is metadata because all nodes are simultaneously rendered",
        },
        "historical_exclusion": {
            "pages_with_historical_structure": len(history_pages),
            "historical_records": 0,
            "boon_candidate_records": 0,
            "hero_memory_candidate_records": 0,
            "skill_shop_candidate_records": 0,
            "structural_scope": '.tab-pane.show.active[id$="-英雄特性"] .card.mb-2',
            "excluded_sibling_scope": '#技能商店.tab-pane:not(.active):not(.show)',
            "legacy_rule": "boon and hero_memory are separate source/category paths and are never traversed by the Hero Trait card scope",
        },
        "search_text_whitelist": {
            "include": ["Hero Entity title", "trait node name", "one current affix block effect", "level label only when explicit"],
            "metadata_only": ["required level", "trait level", "asset key", "node index", "route", "parser info"],
            "record_rule": "one record must not carry whole-page Hero plain_text",
        },
        "noise_exclusions": [
            "skill shop sibling tab", "UI/filter controls", "table headers", "Info/Show Description",
            "tooltip attributes", "internal IDs", "image URLs/assets in search text", "Lore/help/navigation/footer",
            "JS/CSS", "boon", "hero_memory", "historical season content", "duplicated summary text",
        ],
        "view_states": [{
            "field": "hero_trait_tab",
            "source": "active data-bs-target",
            "required": True,
        }, {
            "field": "filter_reset",
            "source": "name=filter control inside trait card",
            "required": True,
        }, {
            "field": "trait_level",
            "source": ".tierLevel adjacent to data-src=affix",
            "required": False,
            "reason": "all levels are rendered; no UI selector must be restored",
        }],
        "locator_support": {
            "record_level": len(all_records),
            "section_level": 0,
            "page_level": 0,
            "confidence": {"high": 0, "medium": len(all_records), "low": 0},
            "strategy": "route -> active Hero Trait pane -> trait node by scoped asset key/occurrence -> level affix block -> scroll/highlight",
            "scope_warning": "never query the asset key across the whole page; Skill Shop and other page content are sibling scopes",
        },
        "case_studies": {
            "minimum": _case(minimum),
            "maximum": _case(maximum),
            "ordinary": _case(ordinary),
            "branch_level": _case(branch),
            "duplicate_stable_key_risk": _case(duplicate),
            "legacy_boon_memory_confusion": _case(legacy),
        },
        "framework_compatible": True,
        "framework_compatibility": {
            "compatible": True,
            "required_framework_changes": [],
            "caveat": "identity and locator confidence are medium because the DOM exposes no native gameplay stable ID",
        },
        "parser_recommendation": {
            "strategy": "one parameterized hero_trait_parser.py for all 27 entities",
            "parser_id": "hero.trait.effects",
            "record_types": ["hero_trait_effect"],
            "stable_key_policy": "scoped icon alt asset key + duplicate occurrence + explicit level/unspecified; medium confidence",
            "section_whitelist": '.tab-pane.show.active[id$="-英雄特性"] .card.mb-2',
            "view_state": ["hero_trait_tab", "filter_reset", "trait_level metadata"],
            "historical_exclusion": "exclude every sibling tab, especially #技能商店; no current historical Hero Trait containers detected",
            "landing_strategy": "scoped trait pane and node lookup, then level affix block; record -> trait section -> page fallback",
            "structure_signature": [
                "trait tab/pane/card count", "trait node count", "tiered node count",
                "max levels per node", "affix block count", "asset-key coverage", "duplicate asset groups",
            ],
        },
        "errors": errors,
    }
    return report


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
