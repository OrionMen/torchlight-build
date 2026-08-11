from __future__ import annotations

import argparse
import json
from collections import OrderedDict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from crawler.build_full_wiki_mirror import canonical_page_key, route_for_source
from crawler.fetch_manifest import write_json


ROOT = Path(__file__).resolve().parents[1]
STATIC_SUFFIXES = {".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".webp",
                   ".svg", ".ico", ".woff", ".woff2", ".ttf", ".otf"}


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


def external_tlidb_canonical(href):
    parsed = urlsplit(href)
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() not in {"tlidb.com", "www.tlidb.com"}:
        return None
    if not parsed.path.startswith("/cn/") or Path(unquote(parsed.path)).suffix.lower() in STATIC_SUFFIXES:
        return None
    return canonical_page_key(href)


def audit(site_root, catalog_path):
    catalog = load_json(catalog_path)
    catalog_routes = {}
    for page in catalog.get("pages", []):
        key = canonical_page_key(page.get("source_url"))
        if key:
            catalog_routes[key] = page.get("route")

    found = OrderedDict()
    total = 0
    for html_path in site_root.rglob("*.html"):
        parser = LinkParser()
        try:
            parser.feed(html_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        page = html_path.relative_to(site_root).as_posix()
        for href in parser.hrefs:
            canonical = external_tlidb_canonical(href)
            if canonical is None:
                continue
            total += 1
            route = catalog_routes.get(canonical)
            item = found.setdefault(canonical, {
                "canonical_url": canonical,
                "occurrence_count": 0,
                "example_pages": [],
                "exists_in_catalog": route is not None,
                "expected_local_route": ("/local_wiki/ss13/site/" + route)
                                        if route else "/local_wiki/ss13/site/" + route_for_source(canonical).removesuffix("index.html"),
            })
            item["occurrence_count"] += 1
            if page not in item["example_pages"] and len(item["example_pages"]) < 5:
                item["example_pages"].append(page)

    values = list(found.values())
    rewrite_bug = [item for item in values if item["exists_in_catalog"]]
    catalog_missing = [item for item in values if not item["exists_in_catalog"]]
    return {
        "total_external_tlidb_internal_links": total,
        "unique_urls": len(values),
        "classification": {
            "catalog_entry_still_external": {"count": len(rewrite_bug), "urls": rewrite_bug},
            "catalog_incomplete_candidates": {"count": len(catalog_missing), "urls": catalog_missing},
            "special_or_excluded": {"count": 0, "urls": []},
        },
        "urls": values,
        "warnings": ["Catalog-missing URLs were not network-validated by this audit."],
        "errors": [],
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Audit public TLIDB /cn/ links retained in Full Mirror HTML")
    parser.add_argument("--site", type=Path, default=Path("local_wiki/ss13/site"))
    parser.add_argument("--output", type=Path,
                        default=Path("data/reports/local-wiki/external-tlidb-links.json"))
    return parser.parse_args(argv)


def resolve(path):
    return path if path.is_absolute() else ROOT / path


def main(argv=None):
    args = parse_args(argv); site = resolve(args.site)
    report = audit(site, site / "catalog.json")
    write_json(resolve(args.output), report)
    print(f"External TLIDB internal links: {report['total_external_tlidb_internal_links']}")
    print(f"Unique URLs: {report['unique_urls']}")
    print(f"Rewrite bugs: {report['classification']['catalog_entry_still_external']['count']}")
    print(f"Catalog incomplete candidates: {report['classification']['catalog_incomplete_candidates']['count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
