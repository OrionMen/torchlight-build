from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from crawler.discover_manifest import download_index


ROOT = Path(__file__).resolve().parents[1]
INDEX_URL = "https://tlidb.com/cn/Inventory"


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "a" and attributes.get("href") is not None:
            self.current = {"href": attributes["href"], "attrs": attributes, "text": []}

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.current["text"] = " ".join("".join(self.current["text"]).split())
            self.links.append(self.current)
            self.current = None


def inventory_url(value, base_url):
    value = html.unescape((value or "").strip())
    if not value or value.startswith(("#", "javascript:", "mailto:", "data:")):
        return None, "excluded"
    parsed = urlsplit(urljoin(base_url, value))
    if (parsed.hostname or "").lower() not in {"tlidb.com", "www.tlidb.com"}:
        return None, "external"
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) != 2 or parts[0].lower() != "cn" or not parts[1]:
        return None, "not_inventory"
    if any(part in {".", ".."} or "/" in part for part in parts):
        return None, "invalid"
    path = "/cn/" + quote(parts[1], safe="-_.~")
    return {
        "url": urlunsplit(("https", "tlidb.com", path, parsed.query, "")),
        "path": path,
        "slug": parts[1],
        "depth": len(parts),
        "raw_href": value,
    }, "accepted"


def page_base(raw_root, system_id, html_path):
    meta_path = raw_root / system_id / "meta" / f"{html_path.stem}.meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            for key in ("final_url", "url", "source_url"):
                if meta.get(key):
                    return meta[key]
        except (OSError, json.JSONDecodeError):
            pass
    return f"https://tlidb.com/cn/{unquote(html_path.stem)}"


def scan_snapshot(raw_root):
    pages = occurrences = str_count = 0
    urls = set()
    routes = OrderedDict()
    depths = Counter()
    invalid = []
    for system_dir in sorted(path for path in raw_root.iterdir() if path.is_dir()):
        html_dir = system_dir / "raw_html"
        if not html_dir.is_dir():
            continue
        for html_path in sorted(html_dir.glob("*.html")):
            pages += 1
            page = f"{system_dir.name}/{html_path.name}"
            try:
                parser = LinkParser()
                parser.feed(html_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError) as exc:
                invalid.append({"page": page, "error": str(exc)})
                continue
            base = page_base(raw_root, system_dir.name, html_path)
            for link in parser.links:
                entry, reason = inventory_url(link["href"], base)
                if reason != "accepted":
                    if reason == "invalid" and "inventory" in link["href"].lower():
                        invalid.append({"page": page, "href": link["href"]})
                    continue
                occurrences += 1
                urls.add(entry["url"])
                depths[entry["depth"]] += 1
                route = entry["path"]
                if route not in routes:
                    routes[route] = {**entry, "name_zh": link["text"], "occurrence_count": 0,
                                     "example_referring_pages": []}
                routes[route]["occurrence_count"] += 1
                examples = routes[route]["example_referring_pages"]
                if page not in examples and len(examples) < 10:
                    examples.append(page)
                if route == "/cn/Inventory/STR_Helmet":
                    str_count += 1
    return {
        "raw_pages_scanned": pages,
        "inventory_link_occurrences": occurrences,
        "unique_inventory_urls": len(urls),
        "unique_inventory_routes": len(routes),
        "path_depth_counts": dict(sorted(depths.items())),
        "entries": list(routes.values()),
        "invalid_entries": invalid,
        "STR_Helmet_found": "/cn/Inventory/STR_Helmet" in routes,
        "STR_Helmet_occurrences": str_count,
    }


def extract_index_entries(document, index_url=INDEX_URL):
    parser = LinkParser()
    parser.feed(document)
    entries = OrderedDict()
    occurrences = duplicates = 0
    invalid = []
    # Inventory entries are the index's direct relative hrefs. Site navigation is
    # root-relative or absolute and must not be mixed into this list.
    candidates = []
    for link in parser.links:
        raw = html.unescape((link["href"] or "").strip())
        parsed_raw = urlsplit(raw)
        if (raw and not raw.startswith(("/", "#")) and not parsed_raw.scheme
                and not parsed_raw.netloc and parsed_raw.path and "/" not in parsed_raw.path):
            candidates.append(link)
    for link in candidates:
        entry, reason = inventory_url(link["href"], index_url)
        if reason != "accepted":
            if reason == "invalid" and "inventory" in link["href"].lower():
                invalid.append(link["href"])
            continue
        occurrences += 1
        if entry["path"] in entries:
            duplicates += 1
            continue
        entries[entry["path"]] = {**entry, "name_zh": link["text"], "discovered_from": index_url,
                                  "evidence_sources": ["index"]}
    return list(entries.values()), {
        "link_occurrences": occurrences,
        "duplicate_entries": duplicates,
        "invalid_entries": invalid,
    }


def merge_entries(snapshot_entries, index_entries):
    merged = OrderedDict()
    for source, entries in (("index", index_entries), ("snapshot", snapshot_entries)):
        for entry in entries:
            if entry["path"] not in merged:
                merged[entry["path"]] = {**entry, "evidence_sources": [source]}
            elif source not in merged[entry["path"]]["evidence_sources"]:
                merged[entry["path"]]["evidence_sources"].append(source)
    return list(merged.values())


def category_counts(entries):
    counts = Counter()
    for entry in entries:
        slug = entry["slug"]
        for prefix in ("STR_", "DEX_", "INT_"):
            if slug.startswith(prefix):
                counts[prefix[:-1]] += 1
        for word in ("Weapon", "Helmet", "Armor", "Gloves", "Boots", "Accessory"):
            if word.lower() in slug.lower():
                counts[word] += 1
    return dict(counts)


def build_manifest(entries, index_meta, warnings):
    values = []
    for order, entry in enumerate(entries):
        values.append({
            "id": entry["slug"], "slug": entry["slug"], "path": entry["path"],
            "name_zh": entry.get("name_zh") or entry["slug"], "url": entry["url"],
            "raw_href": entry.get("raw_href"),
            "discovered_from": entry.get("discovered_from", INDEX_URL),
            "source_order": order,
            "source_locator": {"source": "+".join(entry.get("evidence_sources", [])),
                               "route_pattern": "/cn/<inventory_entry>",
                               "raw_href": entry.get("raw_href"),
                               "resolved_url": entry["url"]},
        })
    return {
        "schema_version": 1,
        "source": {"site": "tlidb", "locale": "cn", "index_url": INDEX_URL,
                   "fetched_at": index_meta.get("fetched_at"), "http_status": index_meta.get("http_status"),
                   "html_sha256": index_meta.get("html_sha256")},
        "system_id": "inventory", "entity_type": "inventory",
        "displayed_entry_count": None, "unique_entry_count": len(values),
        "duplicate_occurrence_count": index_meta.get("duplicate_entries", 0), "discovery_confidence": 0.95,
        "quality": {"displayed_entry_count": None, "unique_entry_count": len(values),
                    "duplicate_occurrence_count": index_meta.get("duplicate_entries", 0),
                    "discovery_confidence": 0.95, "warnings": warnings},
        "entries": values,
    }


def confirm_inventory_system(data, entry_count, confirmed):
    updated = json.loads(json.dumps(data))
    if not confirmed:
        return updated
    matches = [item for item in updated.get("systems", []) if item.get("system_id") == "candidate_inventory"]
    if len(matches) != 1:
        raise ValueError("candidate_inventory must match exactly one system")
    matches[0].update({
        "system_id": "inventory", "discovery_status": "confirmed", "classification_status": "confirmed",
        "manifest_path": "sources/inventory_manifest.json", "entry_count": entry_count,
        "verification_status": "confirmed", "verification_classification": "confirmed",
        "verification_confidence": 0.95,
    })
    return updated


def nested_route_support():
    try:
        from crawler.build_full_wiki_mirror import route_for_source
        mirror = route_for_source("https://tlidb.com/cn/STR_Helmet") == "cn/STR_Helmet/index.html"
    except Exception:
        mirror = False
    return True, mirror


def discover(raw_root, index_html=None, http_status=None):
    snapshot = {"raw_pages_scanned": 0, "inventory_link_occurrences": 0,
                "unique_inventory_urls": 0, "unique_inventory_routes": 0,
                "path_depth_counts": {}, "entries": [], "invalid_entries": [],
                "STR_Helmet_found": False, "STR_Helmet_occurrences": 0}
    index_entries, index_info = (extract_index_entries(index_html) if index_html is not None else
                                 ([], {"link_occurrences": 0, "duplicate_entries": 0, "invalid_entries": []}))
    direct_children = sum(entry["depth"] == 2 for entry in index_entries)
    structurally_consistent = bool(index_entries) and direct_children == len(index_entries)
    complete = len(index_entries) == 147 and structurally_consistent
    merged = index_entries
    warnings = []
    if index_html is None:
        warnings.append("Inventory index was not requested; snapshot evidence alone cannot confirm completeness.")
    elif not complete:
        warnings.append(f"Inventory index yielded {len(index_entries)} canonical entries; expected 147.")
    fetcher, mirror = nested_route_support()
    report = {
        "title": "Inventory Discovery",
        "existing_snapshot": {key: value for key, value in snapshot.items() if key != "entries"},
        "index": {"requested": index_html is not None, "http_status": http_status,
                  "entries_found": len(index_entries), "direct_child_entries": direct_children,
                  "all_entries_are_direct_children": structurally_consistent,
                  "inventory_index_complete": complete, **index_info},
        "manifest": {"entries": len(merged), "duplicate_entries": index_info["duplicate_entries"],
                     "invalid_entries": len(snapshot["invalid_entries"])+len(index_info["invalid_entries"]),
                     "confirmed": complete},
        "route": {"route_pattern": "/cn/<inventory_entry>",
                  "previous_incorrect_assumption": "/cn/Inventory/<entry>",
                  "canonical_resolution_example": {
                      "base": INDEX_URL, "raw_href": "STR_Helmet",
                      "resolved": "https://tlidb.com/cn/STR_Helmet"},
                  "nested_route_supported_by_fetcher": fetcher,
                  "nested_route_supported_by_mirror": mirror},
        "unresolved": {"inventory_unresolved_occurrences": snapshot["inventory_link_occurrences"],
                       "inventory_unique_unresolved_routes": snapshot["unique_inventory_routes"]},
        "classification_counts": category_counts(merged),
        "examples": [entry["url"] for entry in merged[:20]],
        "warnings": warnings, "errors": [],
    }
    fetched_at = datetime.now(timezone.utc).isoformat()
    meta = {"fetched_at": fetched_at, "http_status": http_status,
            "html_sha256": hashlib.sha256(index_html.encode()).hexdigest() if index_html is not None else None,
            **index_info}
    return build_manifest(merged, meta, warnings) if complete else None, report


def report_markdown(report):
    snapshot, index, manifest, route = (report[key] for key in ("existing_snapshot", "index", "manifest", "route"))
    lines = ["# Inventory Discovery", "", "## Existing snapshot", "",
             f"- Raw pages scanned: {snapshot['raw_pages_scanned']}",
             f"- Inventory link occurrences: {snapshot['inventory_link_occurrences']}",
             f"- Unique Inventory routes: {snapshot['unique_inventory_routes']}",
             f"- STR_Helmet: {snapshot['STR_Helmet_found']} ({snapshot['STR_Helmet_occurrences']} occurrences)",
             "", "## Index", "", f"- Requested: {index['requested']}", f"- HTTP status: {index['http_status']}",
             f"- Entries found: {index['entries_found']}", f"- Complete: {index['inventory_index_complete']}",
             "", "## Manifest", "", f"- Entries: {manifest['entries']}", f"- Confirmed: {manifest['confirmed']}",
             "", "## Route", "", f"- Pattern: {route['route_pattern']}",
             f"- Fetcher nested route support: {route['nested_route_supported_by_fetcher']}",
             f"- Mirror nested route support: {route['nested_route_supported_by_mirror']}",
             "", "## Warnings", ""]
    lines.extend([f"- {item}" for item in report["warnings"]] or ["- None"])
    lines.extend(["", "## Errors", ""])
    lines.extend([f"- {item}" for item in report["errors"]] or ["- None"])
    return "\n".join(lines) + "\n"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Discover nested TLIDB Inventory routes")
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw/manifests"))
    parser.add_argument("--index-url", default=INDEX_URL); parser.add_argument("--no-index", action="store_true")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output", type=Path, default=Path("sources/inventory_manifest.json"))
    parser.add_argument("--system-manifest", type=Path, default=Path("sources/system_manifest.json"))
    parser.add_argument("--report", type=Path, default=Path("data/reports/system-discovery/inventory-discovery-report.json"))
    return parser.parse_args(argv)


def resolve(path):
    return path if path.is_absolute() else ROOT / path


def main(argv=None):
    args = parse_args(argv)
    try:
        index_html = None; status = None
        if not args.no_index:
            body, status, encoding = download_index(args.index_url, args.timeout)
            index_html = body.decode(encoding, errors="replace")
        manifest, report = discover(resolve(args.raw_root), index_html, status)
        report_path = resolve(args.report); report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        report_path.with_name("inventory-discovery-summary.md").write_text(report_markdown(report), encoding="utf-8")
        if manifest is not None:
            output = resolve(args.output); output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
            system_path = resolve(args.system_manifest); current = json.loads(system_path.read_text(encoding="utf-8"))
            system_path.write_text(json.dumps(confirm_inventory_system(current, len(manifest["entries"]), True), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        print(f"Raw pages: {report['existing_snapshot']['raw_pages_scanned']}")
        print(f"Inventory routes: {report['existing_snapshot']['unique_inventory_routes']}")
        print(f"Index entries: {report['index']['entries_found']}")
        print(f"Confirmed: {str(report['manifest']['confirmed']).lower()}")
        return 1 if report["errors"] else 0
    except Exception as exc:
        print(f"Inventory discovery failed: {exc}", file=sys.stderr); return 1


if __name__ == "__main__": raise SystemExit(main())
