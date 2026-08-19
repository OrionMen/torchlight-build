from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, OrderedDict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

from crawler.fetch_manifest import write_json
from crawler.season_context import DEFAULT_SEASON, SeasonContext


ROOT = Path(__file__).resolve().parents[1]
JSON_REFERENCE = re.compile(r"(?P<url>(?:https?:)?//[^\s\"'`]+\.json(?:\?[^\s\"'`]*)?|/?[A-Za-z0-9_./${}-]+\.json(?:\?[^\s\"'`]*)?)")


class EvidenceParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.languages = set(); self.data_i18n = Counter()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "html" and attrs.get("lang"):
            self.languages.add(attrs["lang"])
        if attrs.get("data-i18n"):
            self.data_i18n[attrs["data-i18n"]] += 1


def scan(roots, base_url="https://tlidb.com/"):
    html_files = []; js_files = []
    for root in roots:
        if not root.is_dir():
            continue
        html_files.extend(root.rglob("*.html")); js_files.extend(root.rglob("*.js"))
    languages = set(); keys = Counter(); references = []
    for path in html_files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        parser = EvidenceParser(); parser.feed(text)
        if parser.data_i18n:
            languages.update(parser.languages)
        keys.update(parser.data_i18n)
        references.extend((path, match.group("url")) for match in JSON_REFERENCE.finditer(text))
    for path in js_files:
        try:
            text = path.read_text(encoding="utf-8")
            references.extend((path, match.group("url")) for match in JSON_REFERENCE.finditer(text))
        except (OSError, UnicodeDecodeError):
            continue

    resources = OrderedDict(); templates = []
    for path, raw in references:
        if "/i18n/" not in raw.lower() and not raw.lower().startswith("i18n/") and not re.search(r"(?:lang|locale|translation)", raw, re.I):
            continue
        values = []
        if "${lang}" in raw:
            templates.append({"template": raw, "source": str(path)})
            values = [raw.replace("${lang}", lang) for lang in sorted(languages)]
        else:
            values = [raw]
        for value in values:
            url = urljoin(base_url, value)
            item = resources.setdefault(url, {"resource_url": url, "source_pages": [],
                                               "reference_type": "runtime_language_loader" if "${lang}" in raw else "direct_json"})
            source = str(path)
            if source not in item["source_pages"] and len(item["source_pages"]) < 5:
                item["source_pages"].append(source)
    return {
        "resource_count": len(resources), "resources": list(resources.values()),
        "languages_observed": sorted(languages),
        "data_i18n_key_count": len(keys), "data_i18n_occurrences": sum(keys.values()),
        "data_i18n_examples": [{"key": key, "occurrences": count} for key, count in keys.most_common(20)],
        "runtime_loader_templates": templates[:20], "warnings": [], "errors": [],
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Discover TLIDB native i18n JSON references")
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--asset-files", type=Path)
    parser.add_argument("--site", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def resolve(path): return path if path.is_absolute() else ROOT / path


def main(argv=None):
    args = parse_args(argv); context = SeasonContext(ROOT, args.season)
    raw_root = resolve(args.raw_root) if args.raw_root else context.readable_raw_manifest_root()
    asset_files = resolve(args.asset_files) if args.asset_files else context.asset_root / "files"
    site = resolve(args.site) if args.site is not None else None
    output = resolve(args.output) if args.output else context.report_root / "i18n-discovery.json"
    if not raw_root.is_dir():
        print(f"i18n discovery failed: Raw root is not a directory: {raw_root}", file=sys.stderr)
        return 1
    roots = [raw_root]
    if asset_files.is_dir():
        roots.append(asset_files)
    if site is not None and site.is_dir():
        roots.append(site)
    report = scan(roots)
    inputs = ["raw"]
    if asset_files.is_dir(): inputs.append("assets")
    if site is not None and site.is_dir(): inputs.append("site")
    report["input_mode"] = "raw_only" if inputs == ["raw"] else "_plus_".join(inputs)
    report["raw_root"] = str(raw_root)
    report["asset_files_root"] = str(asset_files)
    report["asset_files_available"] = asset_files.is_dir()
    report["site_root"] = str(site) if site is not None else None
    report["site_available"] = site is not None and site.is_dir()
    if site is not None and not site.is_dir():
        report["warnings"].append(
            "Optional generated site is unavailable; discovery completed without it."
        )
    write_json(output, report)
    print(f"i18n resources: {report['resource_count']}")
    return 0


if __name__ == "__main__": raise SystemExit(main())
