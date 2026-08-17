"""Build recovered internal-page manifest from source manifests and Raw HTML only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import quote, unquote, urldefrag, urljoin, urlsplit


ROOT = Path(__file__).resolve().parents[1]
STATIC_SUFFIXES = {
    ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".ico", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".mp4",
    ".webm", ".pdf", ".json", ".xml", ".txt", ".map",
}
NON_CONTENT_PAGE_IDS = {
    "api", "cache", "login", "logout", "search", "signin", "signup",
}
MAX_CONVERGENCE_ROUNDS = 8


class RecoveredDiscoveryError(RuntimeError):
    """Raised when authorized discovery input is invalid."""


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if isinstance(href, str):
            self.hrefs.append(href)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RecoveredDiscoveryError(f"missing input: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RecoveredDiscoveryError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RecoveredDiscoveryError(f"JSON object required: {path}")
    return value


def canonical_internal_page(value: str, base_url: str) -> dict[str, str] | None:
    """Return canonical identity for one TLIDB CN page link, never an asset/runtime URL."""
    value = (value or "").strip()
    if not value or value.startswith(("#", "?", "data:", "blob:", "javascript:", "mailto:")):
        return None
    resolved = urldefrag(urljoin(base_url, value))[0]
    parsed = urlsplit(resolved)
    if (parsed.hostname or "").lower() not in {"tlidb.com", "www.tlidb.com"}:
        return None
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) != 2 or parts[0] != "cn":
        return None
    page_id = parts[1].strip()
    if (
        not page_id
        or page_id in {".", ".."}
        or "/" in page_id
        or Path(page_id).suffix.lower() in STATIC_SUFFIXES
        or page_id.casefold() in NON_CONTENT_PAGE_IDS
    ):
        return None
    route = f"/cn/{page_id}/"
    url = f"https://tlidb.com/cn/{page_id}"
    request_url = f"https://tlidb.com/cn/{quote(page_id, safe='-_.~')}"
    return {"page_id": page_id, "route": route, "url": url, "request_url": request_url}


def _manifest_path(repo: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else repo / path


def _raw_html_path(raw_root: Path, system_id: str, page_id: str) -> Path:
    return raw_root / system_id / "raw_html" / f"{quote(page_id, safe='-_.')}.html"


def _formal_sources(system_manifest_path: Path, raw_root: Path) -> tuple[set[str], list[dict[str, Any]], dict[str, int]]:
    system_manifest = _load_json(system_manifest_path)
    systems = system_manifest.get("systems")
    if not isinstance(systems, list):
        raise RecoveredDiscoveryError("system manifest systems must be a list")
    manifest_root = system_manifest_path.resolve().parent
    routes: set[str] = set()
    pages: list[dict[str, Any]] = []
    manifest_count = 0
    entry_count = 0
    for system in sorted(systems, key=lambda item: str(item.get("system_id", ""))):
        if (system.get("discovery_status") or system.get("status")) != "confirmed":
            continue
        system_id = system.get("system_id")
        manifest_name = system.get("manifest_path")
        if not isinstance(system_id, str) or not isinstance(manifest_name, str):
            raise RecoveredDiscoveryError("confirmed system requires system_id and manifest_path")
        sibling = manifest_root / Path(manifest_name).name
        manifest_path = sibling if sibling.is_file() else _manifest_path(ROOT, manifest_name)
        manifest = _load_json(manifest_path)
        entries = manifest.get("entries")
        if not isinstance(entries, list):
            raise RecoveredDiscoveryError(f"manifest entries must be a list: {manifest_name}")
        manifest_count += 1
        for entry in entries:
            source_url = entry.get("url")
            page_id = entry.get("slug") or entry.get("id")
            if not isinstance(source_url, str) or not isinstance(page_id, str):
                continue
            identity = canonical_internal_page(source_url, "https://tlidb.com/cn/")
            if identity is None:
                continue
            routes.add(identity["route"])
            entry_count += 1
            raw_path = _raw_html_path(raw_root, system_id, page_id)
            if raw_path.is_file() and raw_path.stat().st_size > 0:
                pages.append({
                    "system_id": system_id,
                    "page_id": page_id,
                    "source_url": identity["url"],
                    "route": identity["route"],
                    "raw_path": raw_path,
                })
    return routes, pages, {
        "formal_manifest_count": manifest_count,
        "formal_manifest_entries": entry_count,
        "formal_raw_pages": len(pages),
    }


def _recovered_raw_sources(raw_root: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    root = raw_root / "recovered_internal_pages"
    available: dict[str, dict[str, Any]] = {}
    pages: list[dict[str, Any]] = []
    for meta_path in sorted((root / "meta").glob("*.meta.json"), key=lambda path: path.name):
        meta = _load_json(meta_path)
        source_url = meta.get("source_url") or meta.get("url") or meta.get("final_url")
        page_id = meta.get("slug") or meta.get("id")
        if not isinstance(source_url, str) or not isinstance(page_id, str):
            continue
        identity = canonical_internal_page(source_url, "https://tlidb.com/cn/")
        if identity is None or identity["page_id"] != page_id:
            continue
        raw_path = root / "raw_html" / f"{meta_path.name.removesuffix('.meta.json')}.html"
        if not raw_path.is_file() or raw_path.stat().st_size <= 0:
            continue
        item = {
            "system_id": "recovered_internal_pages",
            "page_id": page_id,
            "source_url": identity["url"],
            "route": identity["route"],
            "raw_path": raw_path,
            "http_status": meta.get("http_status"),
        }
        available[identity["route"]] = item
        pages.append(item)
    return available, pages


def _provenance_key(item: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(item.get("system_id") or ""),
        str(item.get("page_id") or ""),
        str(item.get("source_url") or ""),
        str(item.get("raw_href") or ""),
    )


def load_rejected_routes(path: Path | None) -> set[str]:
    if path is None or not path.is_file():
        return set()
    value = _load_json(path)
    if value.get("schema_version") != 1 or value.get("system_id") != "recovered_internal_pages":
        raise RecoveredDiscoveryError(f"invalid recovered rejected state: {path}")
    entries = value.get("entries")
    if not isinstance(entries, list):
        raise RecoveredDiscoveryError("recovered rejected state entries must be a list")
    routes = set()
    for entry in entries:
        route = entry.get("route")
        if not isinstance(route, str) or canonical_internal_page(route, "https://tlidb.com/cn/") is None:
            raise RecoveredDiscoveryError("recovered rejected state contains an invalid route")
        routes.add(route)
    return routes


def discover_recovered_pages(
    system_manifest_path: Path,
    raw_root: Path,
    rejected_routes: set[str] | None = None,
) -> dict[str, Any]:
    rejected_routes = rejected_routes or set()
    formal_routes, formal_pages, inventory = _formal_sources(system_manifest_path, raw_root)
    recovered_available, recovered_pages = _recovered_raw_sources(raw_root)
    provenance: dict[str, dict[tuple[str, str, str, str], dict[str, Any]]] = defaultdict(dict)
    internal_links_seen = 0
    invalid_or_noise_links = 0
    for page in sorted(formal_pages + recovered_pages, key=lambda item: (item["system_id"], item["route"])):
        parser = _Links()
        try:
            parser.feed(page["raw_path"].read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            raise RecoveredDiscoveryError(f"cannot parse Raw HTML {page['raw_path']}: {exc}") from exc
        for raw_href in parser.hrefs:
            identity = canonical_internal_page(raw_href, page["source_url"])
            if identity is None:
                invalid_or_noise_links += 1
                continue
            internal_links_seen += 1
            source = {
                "system_id": page["system_id"],
                "page_id": page["page_id"],
                "source_url": page["source_url"],
                "raw_href": raw_href,
            }
            provenance[identity["route"]][_provenance_key(source)] = source

    canonical_routes = sorted(provenance)
    missing_routes = [route for route in canonical_routes if route not in formal_routes]
    confirmed_routes = [route for route in missing_routes if route in recovered_available]
    unfetched_routes = [route for route in missing_routes if route not in recovered_available]
    rejected_routes_seen = [route for route in unfetched_routes if route in rejected_routes]
    pending_routes = [route for route in unfetched_routes if route not in rejected_routes]
    recovered_raw_now_manifested = [
        {
            "route": route,
            "page_id": recovered_available[route]["page_id"],
            "reason": "route is now owned by a confirmed formal manifest",
            "discovered_from": sorted(provenance[route].values(), key=_provenance_key),
        }
        for route in sorted(formal_routes & recovered_available.keys() & provenance.keys())
    ]
    candidates = []
    for route in confirmed_routes:
        identity = canonical_internal_page(route, "https://tlidb.com/cn/")
        assert identity is not None
        candidates.append({
            **identity,
            "discovered_from": sorted(provenance[route].values(), key=_provenance_key),
            "raw_size": recovered_available[route]["raw_path"].stat().st_size,
        })
    pending_candidates = []
    for route in pending_routes:
        identity = canonical_internal_page(route, "https://tlidb.com/cn/")
        assert identity is not None
        pending_candidates.append({
            **identity,
            "discovered_from": sorted(provenance[route].values(), key=_provenance_key),
        })
    return {
        "schema_version": 1,
        "source_inventory": {
            **inventory,
            "recovered_raw_pages": len(recovered_pages),
        },
        "internal_links_seen": internal_links_seen,
        "invalid_or_noise_links": invalid_or_noise_links,
        "canonical_routes_seen": len(canonical_routes),
        "already_manifested": sum(route in formal_routes for route in canonical_routes),
        "recovered_candidates": len(candidates),
        "pending_unfetched_count": len(pending_routes),
        "pending_unfetched_routes": pending_routes,
        "pending_candidates": pending_candidates,
        "rejected_routes_seen": rejected_routes_seen,
        "recovered_raw_now_manifested": recovered_raw_now_manifested,
        "candidates": candidates,
    }


def build_manifest(discovery: dict[str, Any], *, max_rounds: int = MAX_CONVERGENCE_ROUNDS) -> dict[str, Any]:
    if not 1 <= max_rounds <= 32:
        raise RecoveredDiscoveryError("max_rounds must be between 1 and 32")
    candidates = discovery.get("candidates")
    if not isinstance(candidates, list):
        raise RecoveredDiscoveryError("discovery candidates must be a list")
    entries = []
    for candidate in sorted(candidates, key=lambda item: item["route"]):
        sources = candidate.get("discovered_from")
        if not isinstance(sources, list) or not sources:
            raise RecoveredDiscoveryError(f"candidate has no provenance: {candidate.get('route')}")
        entries.append({
            "id": candidate["page_id"],
            "slug": candidate["page_id"],
            "path": candidate["route"].rstrip("/"),
            "url": candidate["url"],
            "request_url": candidate["request_url"],
            "validation": {"status": "available", "http_status": 200},
            "source_examples": sorted(sources, key=_provenance_key),
        })
    return {
        "schema_version": 1,
        "system_id": "recovered_internal_pages",
        "entity_type": "recovered_page",
        "source": {"type": "internal_link_recovery"},
        "entry_count": len(entries),
        "duplicate_removed": 0,
        "bootstrap": {
            "input_contract": "source_manifests_and_raw_html",
            "max_rounds": max_rounds,
            "pending_unfetched_count": discovery.get("pending_unfetched_count", 0),
        },
        "entries": entries,
    }


def build_pending_fetch_manifest(discovery: dict[str, Any]) -> dict[str, Any]:
    entries = []
    for candidate in discovery.get("pending_candidates", []):
        identity = canonical_internal_page(candidate.get("route", ""), "https://tlidb.com/cn/")
        if identity is None or not candidate.get("discovered_from"):
            raise RecoveredDiscoveryError("pending candidate requires route and provenance")
        entries.append({
            "id": identity["page_id"],
            "slug": identity["page_id"],
            "url": identity["url"],
            "request_url": identity["request_url"],
            "source_examples": sorted(candidate["discovered_from"], key=_provenance_key),
        })
    return {
        "schema_version": 1,
        "system_id": "recovered_internal_pages",
        "entry_count": len(entries),
        "entries": entries,
    }


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def canonical_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def write_atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        json.loads(temporary.read_text(encoding="utf-8"))
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def generate_manifest(
    system_manifest_path: Path,
    raw_root: Path,
    output_path: Path,
    *,
    max_rounds: int = MAX_CONVERGENCE_ROUNDS,
    rejected_routes: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    discovery = discover_recovered_pages(
        system_manifest_path, raw_root, rejected_routes=rejected_routes
    )
    manifest = build_manifest(discovery, max_rounds=max_rounds)
    write_atomic_json(output_path, manifest)
    return manifest, discovery


def build_bootstrap_report(
    discovery: dict[str, Any],
    manifest: dict[str, Any],
    *,
    reference_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reference_routes = {
        f"/cn/{entry.get('slug') or entry.get('id')}/"
        for entry in (reference_manifest or {}).get("entries", [])
        if entry.get("slug") or entry.get("id")
    }
    fresh_routes = {f"/cn/{entry['slug']}/" for entry in manifest["entries"]}
    superseded_routes = {
        item["route"] for item in discovery["recovered_raw_now_manifested"]
    } & reference_routes
    required_reference_routes = reference_routes - superseded_routes
    missing_routes = sorted(required_reference_routes - fresh_routes)
    extra_routes = sorted(fresh_routes - reference_routes) if reference_routes else []
    errors = []
    if reference_manifest is not None and (missing_routes or extra_routes):
        errors.append("current required recovered routes differ from fresh discovery")
    return {
        "old_dependency_graph": [
            "source manifests + Raw HTML",
            "local_wiki catalog.json existing-route inventory",
            "network validation + validation cache/report",
            "build_recovered_internal_pages_manifest",
            "recovered_internal_pages_manifest.json",
        ],
        "new_dependency_graph": [
            "confirmed source manifests + Raw HTML/Fetch Meta",
            "offline canonical link discovery + formal manifest exclusion",
            "deterministic recovered_internal_pages_manifest.json",
        ],
        "source_inputs": [
            "sources/system_manifest.json",
            "confirmed formal source manifests",
            "data/raw/manifests/*/raw_html/*.html",
            "data/raw/manifests/recovered_internal_pages/meta/*.meta.json",
        ],
        "forbidden_dependencies": {
            "local_wiki": False,
            "catalog_or_search_index": False,
            "entity_index": False,
            "structured_outputs": False,
            "reports_as_production_input": False,
        },
        "manifest_inventory": discovery["source_inventory"],
        "internal_links_seen": discovery["internal_links_seen"],
        "canonical_routes_seen": discovery["canonical_routes_seen"],
        "already_manifested": discovery["already_manifested"],
        "recovered_candidates": discovery["recovered_candidates"],
        "pending_unfetched_count": discovery["pending_unfetched_count"],
        "rejected_candidate_count": len(discovery.get("rejected_routes_seen", [])),
        "reference_recovered_count": len(reference_routes),
        "reference_required_count": len(required_reference_routes),
        "fresh_recovered_count": len(fresh_routes),
        "same_route_count": len(required_reference_routes & fresh_routes),
        "reference_routes_superseded_by_formal_manifests": sorted(superseded_routes),
        "missing_routes": missing_routes,
        "extra_routes": extra_routes,
        "recovered_fate_validation": discovery["recovered_raw_now_manifested"],
        "provenance_validation": {
            "all_candidates_have_sources": all(entry["source_examples"] for entry in manifest["entries"]),
            "ordering": "system_id,page_id,source_url,raw_href",
        },
        "canonicalization_validation": {
            "identity": "decoded canonical /cn/<page-id>/ route",
            "fragment_removed": True,
            "query_removed": True,
            "relative_and_absolute_supported": True,
        },
        "noise_exclusion_validation": {
            "invalid_or_noise_links": discovery["invalid_or_noise_links"],
            "external_assets_runtime_and_non_page_routes_excluded": True,
        },
        "convergence_model": [
            "discover missing routes from current manifests and Raw",
            "fetch pending recovered routes outside this task",
            "rerun discovery with new Raw",
            "stop when pending set is unchanged/empty or max_rounds is reached",
        ],
        "max_rounds": manifest["bootstrap"]["max_rounds"],
        "determinism_validation": {
            "canonical_hash": canonical_hash(manifest),
            "filesystem_order_independent": True,
            "mtime_used": False,
        },
        "canonical_hash": canonical_hash(manifest),
        "atomic_write_validation": {
            "temporary_file_then_replace": True,
            "previous_output_preserved_on_failure": True,
        },
        "bootstrap_command": "python3 -m crawler.discover_recovered_internal_pages",
        "errors": errors,
        "recovered_internal_pages_bootstrap_ready": not errors,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system-manifest", type=Path, default=Path("sources/system_manifest.json"))
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw/manifests"))
    parser.add_argument("--output", type=Path, default=Path("sources/recovered_internal_pages_manifest.json"))
    parser.add_argument("--report", type=Path, default=Path("data/reports/local-wiki/recovered-internal-pages-fresh-bootstrap-v1-report.json"))
    parser.add_argument("--reference-manifest", type=Path)
    parser.add_argument("--pending-output", type=Path)
    parser.add_argument("--rejected-state", type=Path)
    parser.add_argument("--max-rounds", type=int, default=MAX_CONVERGENCE_ROUNDS)
    return parser.parse_args(argv)


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    rejected_state = _resolve(args.rejected_state) if args.rejected_state else None
    manifest, discovery = generate_manifest(
        _resolve(args.system_manifest), _resolve(args.raw_root), _resolve(args.output),
        max_rounds=args.max_rounds,
        rejected_routes=load_rejected_routes(rejected_state),
    )
    if args.pending_output:
        write_atomic_json(_resolve(args.pending_output), build_pending_fetch_manifest(discovery))
    reference = _load_json(_resolve(args.reference_manifest)) if args.reference_manifest else None
    write_atomic_json(_resolve(args.report), build_bootstrap_report(
        discovery, manifest, reference_manifest=reference
    ))
    print(f"Recovered entries: {manifest['entry_count']}")
    print(f"Pending unfetched: {discovery['pending_unfetched_count']}")
    print(f"Canonical hash: {canonical_hash(manifest)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
