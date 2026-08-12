"""Design-audit Entity Layer v1 from existing local reports only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


FOCUS_SLUGS = (
    "Trinity",
    "Frozen_Flame",
    "Burning_Ice",
    "Windbreath_Convergence",
)


def classify_medium(candidate: dict[str, Any]) -> tuple[str, str]:
    sources = candidate.get("sources", [])
    primary = [source for source in sources if source.get("role") == "primary"]
    primary_titles = {source.get("title") for source in primary}
    raw_complete = all(source.get("raw_page_available") for source in sources)
    if (
        candidate.get("category") not in {None, "mixed"}
        and len(primary) >= 2
        and len(primary_titles) == 1
        and raw_complete
    ):
        return (
            "A",
            "Exact route and category match; at least two primary sources share the same title. "
            "Merge identity only and retain source content variants.",
        )
    if candidate.get("category") == "mixed" or len(primary_titles) > 1:
        return "C", "Conflicting category or primary-source title; automatic merge is not advised."
    return "B", "Identity evidence is incomplete or unmapped and requires human confirmation."


def _examples(rows: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    return [
        {
            "canonical_route": row["canonical_route"],
            "title": row.get("title"),
            "category": row.get("category"),
            "systems": [source["system_id"] for source in row.get("sources", [])],
        }
        for row in rows[:limit]
    ]


def build_design_audit(repo: Path) -> dict[str, Any]:
    dedup = json.loads(
        (repo / "data/reports/local-wiki/entity-dedup-audit.json").read_text(encoding="utf-8")
    )
    mapping = json.loads((repo / "config/game_category_mapping.json").read_text(encoding="utf-8"))
    search = json.loads(
        (repo / "local_wiki/ss13/site/search-index.json").read_text(encoding="utf-8")
    )
    route_audit = json.loads(
        (repo / "data/reports/local-wiki/route-audit.json").read_text(encoding="utf-8")
    )

    candidates = dedup.get("entity_candidates", [])
    high = [row for row in candidates if row.get("confidence") == "high"]
    high_safe = [
        row
        for row in high
        if row.get("evidence", {}).get("canonical_route_identical")
        and row.get("evidence", {}).get("page_title_identical")
        and row.get("evidence", {}).get("page_body_identical")
        and row.get("category") not in {None, "mixed"}
    ]
    high_mixed = [row for row in high if row.get("category") == "mixed"]
    high_unmapped = [row for row in high if row.get("category") is None]

    medium = [row for row in candidates if row.get("confidence") == "medium"]
    medium_groups: dict[str, list[dict[str, Any]]] = {"A": [], "B": [], "C": []}
    reasons: dict[str, str] = {}
    for row in medium:
        group, reason = classify_medium(row)
        medium_groups[group].append(row)
        reasons.setdefault(group, reason)

    focus = []
    for slug in FOCUS_SLUGS:
        route = f"/cn/{slug}/"
        row = next((item for item in medium if item.get("canonical_route") == route), None)
        if row:
            group, reason = classify_medium(row)
            focus.append({
                "id": slug,
                "canonical_route": route,
                "classification": group,
                "reason": reason,
                "systems": [source["system_id"] for source in row.get("sources", [])],
            })

    return {
        "schema_version": 1,
        "design_scope": "Entity Layer v1 proposal only; no entity index is generated.",
        "input_summary": {
            "dedup_candidate_count": len(candidates),
            "search_index_schema_version": search.get("schema_version"),
            "search_index_page_count": search.get("page_count"),
            "route_audit_duplicate_count": route_audit.get("duplicate_routes", {}).get("count"),
            "configured_category_count": len(mapping.get("categories", [])),
        },
        "entity_schema_proposal": {
            "schema_version": 1,
            "required_fields": {
                "entity_id": "Stable semantic identifier derived from the canonical route.",
                "title": "Preferred display title selected from the canonical owner.",
                "category": "Mapped game category or null when unclassified.",
                "canonical_route": "Decoded semantic local route with a trailing slash.",
                "sources": [
                    {
                        "system_id": "Original source system; never discarded.",
                        "role": "primary | secondary | support | entry",
                    }
                ],
                "confidence": "high | medium | low",
            },
            "recommended_optional_fields": {
                "canonical_owner": "Selected source system and entry id.",
                "season_versions": "Season-specific page evidence kept separately from identity.",
                "review_status": "pending | reviewed | rejected",
            },
            "example": {
                "entity_id": "tlidb:cn:Trinity",
                "title": "三相",
                "category": "equipment",
                "canonical_route": "/cn/Trinity/",
                "sources": [
                    {"system_id": "legendary_gear", "role": "primary"},
                    {"system_id": "craft", "role": "primary"},
                    {"system_id": "hyperlink", "role": "secondary"},
                ],
                "confidence": "medium",
            },
        },
        "high_confidence_analysis": {
            "total": len(high),
            "route_title_body_consistent_count": sum(
                1
                for row in high
                if all(row.get("evidence", {}).get(key) for key in (
                    "canonical_route_identical", "page_title_identical", "page_body_identical"
                ))
            ),
            "high_confidence_safe_count": len(high_safe),
            "category_conflict_count": len(high_mixed),
            "category_unmapped_count": len(high_unmapped),
            "safe_criteria": "Exact route, page title, page body, and one explicit category agree.",
            "examples": _examples(high_safe),
            "category_conflict_examples": _examples(high_mixed, 5),
            "category_unmapped_examples": _examples(high_unmapped, 5),
        },
        "medium_confidence_analysis": {
            "total": len(medium),
            "classes": {
                key: {
                    "count": len(rows),
                    "meaning": {
                        "A": "Identity may be merged automatically while source content remains separate.",
                        "B": "Human confirmation is required.",
                        "C": "Do not merge without new evidence.",
                    }[key],
                    "rule": reasons.get(key, {
                        "A": "No candidates matched.",
                        "B": "No candidates matched.",
                        "C": "No candidates matched.",
                    }[key]),
                    "examples": _examples(rows),
                }
                for key, rows in medium_groups.items()
            },
            "focus_cases": focus,
        },
        "owner_selection_proposal": {
            "principle": "Owner selects presentation metadata only; all source evidence remains attached.",
            "priority": [
                "Official system whose mapped game category matches the entity category.",
                "Player-facing primary source (for equipment: legendary_gear, then inventory, then craft).",
                "Other official entry source.",
                "Secondary reference source such as hyperlink.",
                "Support source such as help, tip, or codex.",
                "Supplemental recovered source.",
            ],
            "tie_breakers": [
                "Prefer a reviewed Chinese title.",
                "Then use stable system source order and entry source order.",
                "Never use mutable fetch time or filesystem order.",
            ],
        },
        "entity_id_design": {
            "options": {
                "A_canonical_slug": {
                    "example": "tlidb:cn:Trinity",
                    "advantages": ["Readable", "Stable across seasons", "Directly traceable to canonical route"],
                    "risks": ["Requires alias/migration record if TLIDB changes the canonical slug"],
                },
                "B_internal_hash": {
                    "advantages": ["Fixed width", "Avoids unusual path characters"],
                    "risks": ["Opaque", "Normalization changes can silently change ids"],
                },
                "C_existing_page_id": {
                    "advantages": ["No new token format"],
                    "risks": ["System-dependent", "Ambiguous when the same route appears in several manifests"],
                },
            },
            "recommendation": "A_canonical_slug",
            "normalization": "Use the percent-decoded canonical path slug, Unicode NFC, and preserve case.",
            "season_policy": "Keep entity_id season-neutral; store SS13 and later snapshots as versions.",
            "collision_policy": "Use the full canonical path; add a short canonical-URL hash only for proven collisions.",
        },
        "recommendation": [
            "Start v1 with the 361 high-confidence candidates that also have one explicit category.",
            "Allow the 66 class-A medium candidates to share identity only; preserve source-specific content.",
            "Review 4 class-B medium candidates and 67 high candidates with mixed or missing categories.",
            "Do not create an Entity Index until owner and alias migration rules are approved.",
        ],
        "warnings": [],
        "errors": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/reports/local-wiki/entity-layer-design-audit.json"),
    )
    args = parser.parse_args()
    repo = args.repo.resolve()
    report = build_design_audit(repo)
    output = args.output if args.output.is_absolute() else repo / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
