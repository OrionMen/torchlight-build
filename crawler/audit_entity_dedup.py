"""Audit duplicate TLIDB entities without modifying source data."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


PRIMARY_SYSTEMS = {"inventory", "legendary_gear", "craft"}
SECONDARY_SYSTEMS = {"hyperlink"}
SUPPORT_SYSTEMS = {"help", "tip", "codex"}
FOCUS_IDS = (
    "STR_Helmet",
    "Trinity",
    "Frozen_Flame",
    "Burning_Ice",
    "Windbreath_Convergence",
)


class _PageText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: list[str] = []
        self.body: list[str] = []
        self._title = False
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._title = True
        if tag in {"script", "style", "noscript"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._title = False
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text or self._skip:
            return
        if self._title:
            self.title.append(text)
        self.body.append(text)


def canonical_route(url_or_path: str) -> str:
    path = urlsplit(url_or_path).path if "://" in url_or_path else url_or_path
    path = unquote(path)
    if not path.startswith("/"):
        path = "/" + path
    return path.rstrip("/") + "/"


def source_role(system_id: str) -> str:
    if system_id in PRIMARY_SYSTEMS:
        return "primary"
    if system_id in SECONDARY_SYSTEMS:
        return "secondary"
    if system_id in SUPPORT_SYSTEMS:
        return "support"
    return "entry"


def load_category_map(path: Path) -> dict[str, dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, dict[str, str]] = {}
    for category in data.get("categories", []):
        for system_id in category.get("systems", []):
            result[system_id] = {
                "id": category["id"],
                "name_zh": category["name_zh"],
            }
    return result


def _page_fingerprint(path: Path) -> dict[str, str] | None:
    if not path.is_file():
        return None
    parser = _PageText()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    title = " ".join(parser.title).strip()
    body = " ".join(parser.body).strip()
    return {
        "title_sha256": hashlib.sha256(title.encode()).hexdigest(),
        "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
    }


def _raw_path(repo: Path, system_id: str, entry: dict[str, Any]) -> Path:
    slug = str(entry.get("slug") or entry.get("id") or "")
    candidates = [
        repo / "data/raw/manifests" / system_id / "raw_html" / f"{slug}.html",
        repo / "data/raw/manifests" / system_id / "raw_html" / f"{entry.get('id', slug)}.html",
    ]
    return next((path for path in candidates if path.is_file()), candidates[0])


def build_audit(repo: Path) -> dict[str, Any]:
    system_manifest = json.loads((repo / "sources/system_manifest.json").read_text(encoding="utf-8"))
    category_map = load_category_map(repo / "config/game_category_mapping.json")
    search = json.loads((repo / "local_wiki/ss13/site/search-index.json").read_text(encoding="utf-8"))
    build_report = json.loads((repo / "local_wiki/ss13/site/mirror-build-report.json").read_text(encoding="utf-8"))
    route_audit = json.loads((repo / "data/reports/local-wiki/route-audit.json").read_text(encoding="utf-8"))

    search_by_route = {
        canonical_route(page["route"]): page for page in search.get("pages", []) if page.get("route")
    }
    manifests: list[tuple[str, Path]] = []
    warnings: list[str] = []
    for system in system_manifest.get("systems", []):
        manifest_path = system.get("manifest_path")
        if manifest_path:
            path = repo / manifest_path
            if path.is_file():
                manifests.append((system["system_id"], path))
            else:
                warnings.append(f"Manifest not found and skipped: {manifest_path}")
    recovered = repo / "sources/recovered_internal_pages_manifest.json"
    if recovered.is_file():
        manifests.append(("recovered_internal_pages", recovered))

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_routes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for system_id, manifest_path in manifests:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        seen: set[tuple[str, str]] = set()
        for entry in data.get("entries", []):
            url = entry.get("url") or entry.get("path")
            if not url:
                continue
            route = canonical_route(str(url))
            identity = (route, str(entry.get("id") or entry.get("slug") or ""))
            if identity in seen:
                continue
            seen.add(identity)
            source = {
                "system_id": system_id,
                "id": entry.get("id") or entry.get("slug"),
                "role": source_role(system_id),
                "canonical_route": route,
                "title": entry.get("name_zh") or entry.get("name") or entry.get("id"),
                "raw_fingerprint": _page_fingerprint(_raw_path(repo, system_id, entry)),
            }
            all_routes[route].append(source)
            grouped[route].append(source)

    duplicates = {route: sources for route, sources in grouped.items() if len(sources) > 1}
    candidates: list[dict[str, Any]] = []
    confidence_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    hyperlink_count = 0
    for route in sorted(duplicates):
        sources = duplicates[route]
        fingerprints = [source["raw_fingerprint"] for source in sources]
        comparable = all(fingerprints)
        same_title = comparable and len({item["title_sha256"] for item in fingerprints if item}) == 1
        same_body = comparable and len({item["body_sha256"] for item in fingerprints if item}) == 1
        confidence = "high" if same_title and same_body else "medium"
        confidence_counts[confidence] += 1
        categories = {
            category_map[source["system_id"]]["id"]
            for source in sources
            if source["system_id"] in category_map
        }
        category = next(iter(categories)) if len(categories) == 1 else ("mixed" if categories else None)
        if category:
            category_counts[category] += 1
        if any(source["system_id"] == "hyperlink" for source in sources):
            hyperlink_count += 1
        search_page = search_by_route.get(route, {})
        candidate_sources = []
        for source in sources:
            clean = {key: value for key, value in source.items() if key != "raw_fingerprint"}
            clean["raw_page_available"] = source["raw_fingerprint"] is not None
            candidate_sources.append(clean)
        candidates.append({
            "canonical_route": route,
            "title": search_page.get("title_display") or search_page.get("title") or sources[0]["title"],
            "category": category,
            "sources": candidate_sources,
            "confidence": confidence,
            "evidence": {
                "canonical_route_identical": True,
                "page_title_identical": bool(same_title),
                "page_body_identical": bool(same_body),
            },
        })

    focus_cases = []
    for entity_id in FOCUS_IDS:
        route = canonical_route(f"/cn/{entity_id}")
        sources = all_routes.get(route, [])
        focus_cases.append({
            "id": entity_id,
            "canonical_route": route,
            "is_duplicate_candidate": route in duplicates,
            "source_count": len(sources),
            "systems": [source["system_id"] for source in sources],
        })

    source_occurrences = sum(len(sources) for sources in duplicates.values())
    max_sources = max((len(sources) for sources in duplicates.values()), default=0)
    max_routes = [route for route, sources in duplicates.items() if len(sources) == max_sources]
    return {
        "schema_version": 1,
        "inputs": {
            "search_index_schema_version": search.get("schema_version"),
            "mirror_routes_generated": build_report.get("routes_generated"),
            "route_audit_duplicate_count": route_audit.get("duplicate_routes", {}).get("count"),
        },
        "duplicate_routes": {
            "count": len(duplicates),
            "source_occurrence_count": source_occurrences,
            "extra_source_occurrence_count": source_occurrences - len(duplicates),
            "maximum_source_count": max_sources,
            "maximum_source_routes": sorted(max_routes),
        },
        "entity_candidates": candidates,
        "statistics": {
            "confidence": {
                "high": confidence_counts["high"],
                "medium": confidence_counts["medium"],
                "low": confidence_counts["low"],
            },
            "by_game_category": dict(sorted(category_counts.items())),
            "hyperlink_duplicate_routes": hyperlink_count,
            "hyperlink_share": round(hyperlink_count / len(duplicates), 6) if duplicates else 0,
            "inventory_craft_legendary_overlap": sum(
                1 for sources in duplicates.values()
                if len({source["system_id"] for source in sources} & PRIMARY_SYSTEMS) >= 2
            ),
        },
        "focus_cases": focus_cases,
        "recommendation": "Treat high-confidence rows as merge candidates only; preserve every source and require review before entity-layer changes.",
        "warnings": warnings,
        "errors": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/reports/local-wiki/entity-dedup-audit.json"),
    )
    args = parser.parse_args()
    report = build_audit(args.repo.resolve())
    output = args.output if args.output.is_absolute() else args.repo.resolve() / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
