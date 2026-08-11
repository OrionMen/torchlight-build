from __future__ import annotations

import argparse
import json
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SITE_PREFIX = "/local_wiki/ss13/site/"


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href is not None:
                self.hrefs.append(href)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_web_path(url_or_path):
    path = urlsplit(url_or_path).path
    return quote(unquote(path), safe="/-_.~").rstrip("/") or "/"


def route_file(site_root, web_path):
    decoded = unquote(urlsplit(web_path).path).strip("/")
    return site_root / decoded / "index.html"


def classify_missing_route(generated, expected_paths):
    generated = canonical_web_path(generated)
    parts = [part for part in generated.split("/") if part]
    if len(parts) > 2 and parts[0] == "cn":
        child = parts[-1]
        parent = parts[-2]
        flat = canonical_web_path("/cn/" + child)
        if unquote(child).startswith(unquote(parent) + ":"):
            return "wrong_directory", flat
        if flat in expected_paths:
            return "wrong_namespace", flat
    return "missing", None


def manifest_routes(system_manifest_path):
    records = []
    by_path = defaultdict(list)
    for system in load_json(system_manifest_path).get("systems", []):
        status = system.get("discovery_status") or system.get("status")
        if status != "confirmed":
            continue
        path = Path(system["manifest_path"])
        if not path.is_absolute():
            path = ROOT / path
        for entry in load_json(path).get("entries", []):
            url = entry.get("url")
            if not url:
                continue
            record = {
                "system_id": system.get("system_id"), "id": entry.get("id"),
                "source_url": url, "expected": canonical_web_path(url),
                "known_missing": entry.get("validation", {}).get("status") == "not_found",
            }
            records.append(record)
            by_path[record["expected"]].append(record)
    duplicates = [
        {"route": route, "sources": [{"system_id": item["system_id"], "id": item["id"]} for item in items]}
        for route, items in by_path.items() if len(items) > 1
    ]
    return records, by_path, duplicates


def local_link_path(href, source_route):
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc or href.startswith(("#", "mailto:", "javascript:", "data:")):
        return None
    path = parsed.path
    if path.startswith(SITE_PREFIX):
        path = "/" + path[len(SITE_PREFIX):]
    elif not path.startswith("/"):
        path = urlsplit(urljoin("https://mirror.invalid/" + source_route, href)).path
    if not path.startswith("/cn/"):
        return None
    return path


def bucket(values, limit=50):
    return {"count": len(values), "examples": values[:limit]}


def audit(system_manifest_path, site_root, catalog_path, search_path, build_report_path):
    records, by_path, duplicates = manifest_routes(system_manifest_path)
    expected_paths = set(by_path)
    catalog = load_json(catalog_path).get("pages", [])
    search = load_json(search_path).get("pages", [])
    build_report = load_json(build_report_path)

    missing = []
    known_missing_generated = []
    for record in records:
        exists = route_file(site_root, record["expected"]).is_file()
        if record["known_missing"]:
            if exists:
                known_missing_generated.append(record)
        elif not exists:
            missing.append(record)

    catalog_mismatch = []
    for page in catalog:
        expected = canonical_web_path(page.get("source_url", ""))
        actual = canonical_web_path("/" + page.get("route", ""))
        if expected != actual:
            catalog_mismatch.append({"system_id": page.get("system_id"), "id": page.get("id"),
                                     "actual": actual, "expected": expected})
    search_by_key = {(page.get("system_id"), page.get("id")): page for page in search}
    search_mismatch = []
    for page in catalog:
        match = search_by_key.get((page.get("system_id"), page.get("id")))
        if not match or canonical_web_path("/" + match.get("route", "")) != canonical_web_path("/" + page.get("route", "")):
            search_mismatch.append({"system_id": page.get("system_id"), "id": page.get("id")})

    checked = existing = 0
    wrong_namespace = []; wrong_directory = []; encoding_mismatch = []; link_missing = []
    for html_path in site_root.rglob("*.html"):
        parser = LinkParser()
        try:
            parser.feed(html_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        relative = html_path.relative_to(site_root).as_posix()
        source_route = relative.removesuffix("index.html")
        for href in parser.hrefs:
            target = local_link_path(href, source_route)
            if target is None:
                continue
            checked += 1
            canonical = canonical_web_path(target)
            exists = route_file(site_root, canonical).is_file()
            raw_path = urlsplit(target).path.rstrip("/")
            if exists:
                existing += 1
                if raw_path != canonical and unquote(raw_path) == unquote(canonical):
                    encoding_mismatch.append({"generated": raw_path, "canonical": canonical,
                                              "source": relative})
                continue
            kind, expected = classify_missing_route(canonical, expected_paths)
            item = {"generated": canonical, "expected": expected, "source": relative}
            if kind == "wrong_namespace": wrong_namespace.append(item)
            elif kind == "wrong_directory": wrong_directory.append(item)
            else: link_missing.append(item)

    report_duplicates = build_report.get("duplicate_route_conflicts", [])
    duplicate_keys = {item["route"] for item in duplicates}
    for item in report_duplicates:
        route = canonical_web_path("/" + item.get("route", "").removesuffix("index.html"))
        if route not in duplicate_keys:
            duplicates.append({"route": route, "sources": item.get("sources", [])})

    return {
        "total_routes_checked": checked,
        "existing_routes": existing,
        "missing_routes": bucket(link_missing + missing),
        "wrong_namespace_routes": bucket(wrong_namespace),
        "wrong_directory_routes": bucket(wrong_directory),
        "encoding_mismatch_routes": bucket(encoding_mismatch),
        "duplicate_routes": bucket(duplicates),
        "manifest_route_count": len(records),
        "catalog_route_count": len(catalog),
        "catalog_mismatches": bucket(catalog_mismatch),
        "search_index_mismatches": bucket(search_mismatch),
        "known_missing_generated_routes": bucket(known_missing_generated),
        "build_report_pages_failed": build_report.get("pages_failed"),
        "warnings": [], "errors": [],
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Audit Full Mirror canonical route mappings")
    parser.add_argument("--system-manifest", type=Path, default=Path("sources/system_manifest.json"))
    parser.add_argument("--site", type=Path, default=Path("local_wiki/ss13/site"))
    parser.add_argument("--output", type=Path, default=Path("data/reports/local-wiki/route-audit.json"))
    return parser.parse_args(argv)


def resolve(path):
    return path if path.is_absolute() else ROOT / path


def main(argv=None):
    args = parse_args(argv); site = resolve(args.site)
    report = audit(resolve(args.system_manifest), site, site / "catalog.json",
                   site / "search-index.json", site / "mirror-build-report.json")
    output = resolve(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Routes checked: {report['total_routes_checked']}")
    print(f"Missing: {report['missing_routes']['count']}")
    print(f"Wrong namespace: {report['wrong_namespace_routes']['count']}")
    print(f"Wrong directory: {report['wrong_directory_routes']['count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
