from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, OrderedDict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urldefrag, urljoin, urlparse


ROOT = Path(__file__).resolve().parents[1]
TRACKING_HOST_PARTS = ("google-analytics", "googletagmanager", "doubleclick", "facebook.net", "hotjar", "clarity.ms", "adservice", "analytics", "nitropay", "cloudflareinsights")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif", ".bmp"}
FONT_EXT = {".woff", ".woff2", ".ttf", ".otf", ".eot"}
MEDIA_EXT = {".mp4", ".webm", ".mp3", ".ogg", ".wav", ".m4a"}
CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I)
CSS_IMPORT = re.compile(r"@import\s+(?:url\(\s*)?(['\"]?)([^'\"\s;)]+)\1\s*\)?", re.I)


def normalize_url(value, base_url):
    value = value.strip()
    if not value or value.startswith(("#", "data:", "blob:", "javascript:", "mailto:")):
        return None
    absolute = urljoin(base_url, value)
    return urldefrag(absolute)[0]


def srcset_urls(value):
    return [part.strip().split()[0] for part in value.split(",") if part.strip()]


def extension_for(url):
    suffix = Path(unquote(urlparse(url).path)).suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix) else ""


def infer_type(url, hint="other", rel="", as_value=""):
    ext = extension_for(url)
    rels = set(rel.lower().split())
    as_value = as_value.lower()
    if hint != "other":
        return hint
    if "stylesheet" in rels or ext == ".css" or as_value == "style": return "stylesheet"
    if "icon" in rels or "apple-touch-icon" in rels: return "icon"
    if ext == ".js" or as_value == "script": return "javascript"
    if ext in FONT_EXT or as_value == "font": return "font"
    if ext in IMAGE_EXT or as_value == "image": return "image"
    if ext in MEDIA_EXT or as_value in {"audio", "video"}: return "media"
    return "other"


def domain_category(url):
    host = (urlparse(url).hostname or "").lower()
    if host in {"tlidb.com", "www.tlidb.com"}: return "tlidb.com"
    if host.endswith(".tlidb.com"): return "tlidb_cdn"
    return "other_external"


def is_tracking(url):
    host = (urlparse(url).hostname or "").lower()
    return any(part in host for part in TRACKING_HOST_PARTS)


def local_path(asset_id, asset_type, extension):
    folder = {"stylesheet": "css", "javascript": "js"}.get(asset_type, asset_type)
    return f"{folder}/{asset_id[:2]}/{asset_id[2:4]}/{asset_id}{extension}"


def css_references(text):
    references = []; import_spans = []
    for match in CSS_IMPORT.finditer(text):
        references.append((match.group(2), "css.import", "stylesheet")); import_spans.append(match.span())
    for match in CSS_URL.finditer(text):
        if any(start <= match.start() and match.end() <= end for start, end in import_spans): continue
        prefix = text[:match.start()].lower()
        attribute = "css.font-face" if prefix.rfind("@font-face") > prefix.rfind("}") else "css.url"
        references.append((match.group(2), attribute, "other"))
    return references


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.references = []
        self.in_style = False

    def add(self, value, attribute, hint="other", rel="", as_value=""):
        if value:
            self.references.append((value, attribute, hint, rel, as_value))

    def css(self, value, attribute):
        for match in CSS_URL.finditer(value): self.add(match.group(2), attribute)
        for match in CSS_IMPORT.finditer(value): self.add(match.group(2), attribute, "stylesheet")

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs); rel = attrs.get("rel", ""); as_value = attrs.get("as", "")
        if tag == "img":
            self.add(attrs.get("src"), "img.src", "image")
            for url in srcset_urls(attrs.get("srcset", "")): self.add(url, "img.srcset", "image")
        elif tag == "link": self.add(attrs.get("href"), "link.href", "other", rel, as_value)
        elif tag == "script": self.add(attrs.get("src"), "script.src", "javascript")
        elif tag == "source":
            self.add(attrs.get("src"), "source.src")
            for url in srcset_urls(attrs.get("srcset", "")): self.add(url, "source.srcset", "image")
        elif tag == "video": self.add(attrs.get("poster"), "video.poster", "image")
        elif tag == "object": self.add(attrs.get("data"), "object.data")
        if "style" in attrs: self.css(attrs["style"], f"{tag}.style")
        if tag == "style": self.in_style = True

    def handle_endtag(self, tag):
        if tag == "style": self.in_style = False

    def handle_data(self, data):
        if self.in_style: self.css(data, "style.url")


def page_base(raw_root, system_id, html_path):
    meta_path = raw_root / system_id / "meta" / f"{html_path.stem}.meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            for key in ("final_url", "url", "source_url"):
                if meta.get(key): return meta[key]
        except (OSError, json.JSONDecodeError): pass
    return f"https://tlidb.com/cn/{unquote(html_path.stem)}"


def discover(season, raw_root, previous_manifest=None, files_root=None):
    assets = OrderedDict(); warnings = []; errors = []; pages = 0; references = 0; excluded = 0
    html_urls = set(); css_urls = set(); css_references_count = 0; css_scanned = 0; css_not_downloaded = 0
    previous_assets = {item["source_url"]: item for item in (previous_manifest or {}).get("assets", [])}

    def ensure_asset(source_url, asset_type):
        item = assets.get(source_url)
        if item is not None: return item, False
        previous = previous_assets.get(source_url)
        if previous is not None:
            item = dict(previous); ext = item.setdefault("extension", extension_for(source_url))
            item.setdefault("asset_type", asset_type); item.setdefault("domain_category", domain_category(source_url))
            item.setdefault("local_relative_path", local_path(item["asset_id"], item["asset_type"], ext))
            item["referenced_by_count"] = 0; item["referenced_by"] = []
        else:
            asset_id = hashlib.sha256(source_url.encode("utf-8")).hexdigest(); ext = extension_for(source_url)
            item = {"asset_id": asset_id, "source_url": source_url, "asset_type": asset_type,
                    "extension": ext, "domain_category": domain_category(source_url),
                    "referenced_by_count": 0, "referenced_by": [],
                    "local_relative_path": local_path(asset_id, asset_type, ext)}
        assets[source_url] = item
        return item, previous is None

    def add_reference(source_url, asset_type, reference):
        nonlocal references
        item, created = ensure_asset(source_url, asset_type); references += 1
        item["referenced_by_count"] += 1
        if reference not in item["referenced_by"] and len(item["referenced_by"]) < 20:
            item["referenced_by"].append(reference)
        return created

    for source_url, previous in previous_assets.items():
        ensure_asset(source_url, previous.get("asset_type", "other"))
    for system_dir in sorted(path for path in raw_root.iterdir() if path.is_dir()):
        html_dir = system_dir / "raw_html"
        if not html_dir.is_dir(): continue
        for html_path in sorted(html_dir.glob("*.html")):
            pages += 1; base = page_base(raw_root, system_dir.name, html_path)
            try:
                parser = AssetParser(); parser.feed(html_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(f"Unable to scan {system_dir.name}/{html_path.name}: {exc}"); continue
            for value, attribute, hint, rel, as_value in parser.references:
                source_url = normalize_url(value, base)
                if not source_url: continue
                if is_tracking(source_url): excluded += 1; continue
                asset_type = infer_type(source_url, hint, rel, as_value)
                reference = {"system_id": system_dir.name, "page_id": unquote(html_path.stem), "attribute": attribute}
                add_reference(source_url, asset_type, reference); html_urls.add(source_url)
    assets_before_css = set(assets)
    if files_root:
        for stylesheet in list(assets.values()):
            if stylesheet.get("asset_type") != "stylesheet": continue
            css_path = files_root / stylesheet.get("local_relative_path", "")
            if not css_path.is_file(): css_not_downloaded += 1; continue
            css_scanned += 1
            try: css_text = css_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                warnings.append(f"Unable to scan local CSS {css_path.name}: {exc}"); continue
            for value, attribute, hint in css_references(css_text):
                source_url = normalize_url(value, stylesheet["source_url"])
                if not source_url: continue
                if is_tracking(source_url): excluded += 1; continue
                css_references_count += 1; css_urls.add(source_url); asset_type = infer_type(source_url, hint)
                reference = {"system_id": "_asset_css", "page_id": stylesheet["asset_id"], "attribute": attribute,
                             "source_kind": "stylesheet", "source_asset_id": stylesheet["asset_id"]}
                add_reference(source_url, asset_type, reference)
    new_assets_from_css = len(css_urls - assets_before_css)
    values = list(assets.values()); types = Counter(item["asset_type"] for item in values)
    referenced_unique = sum(item["referenced_by_count"] > 0 for item in values)
    domains = Counter((urlparse(item["source_url"]).hostname or "") for item in values)
    categories = Counter(item["domain_category"] for item in values)
    manifest = {"schema_version": 1, "season": season, "source_page_count": pages,
                "asset_reference_count": references, "unique_asset_count": len(values), "assets": values,
                "warnings": warnings, "errors": errors}
    report = {"season": season, "pages_scanned": pages, "asset_reference_count": references,
              "unique_asset_count": len(values), "html_discovered_unique_assets": len(html_urls),
              "css_scanned": css_scanned, "css_not_downloaded": css_not_downloaded,
              "css_secondary_reference_count": css_references_count,
              "css_secondary_unique_asset_count": len(css_urls),
              "new_assets_from_css": new_assets_from_css,
              "total_unique_asset_count": len(values), "discovery_converged": new_assets_from_css == 0,
              "image_count": types["image"],
              "css_count": types["stylesheet"], "js_count": types["javascript"],
              "font_count": types["font"], "icon_count": types["icon"],
              "media_count": types["media"], "other_count": types["other"],
              "unique_domain_count": len(domains), "counts_by_domain": dict(sorted(domains.items())),
              "counts_by_domain_category": dict(sorted(categories.items())),
              "excluded_tracking_count": excluded,
              "duplicate_reference_count": references - referenced_unique, "warnings": warnings, "errors": errors}
    return manifest, report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Discover static assets referenced by local TLIDB raw HTML")
    parser.add_argument("--season", default="ss13")
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw/manifests"))
    parser.add_argument("--output", type=Path, default=Path("data/raw/assets/ss13/asset-manifest.json"))
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv); raw_root = args.raw_root if args.raw_root.is_absolute() else ROOT / args.raw_root
    output = args.output if args.output.is_absolute() else ROOT / args.output
    try:
        previous = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else None
        manifest, report = discover(args.season, raw_root, previous, output.parent / "files"); output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report_path = output.parent / "asset-discovery-report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Pages: {report['pages_scanned']}"); print(f"References: {report['asset_reference_count']}")
        print(f"Unique assets: {report['unique_asset_count']}"); print(f"New assets from CSS: {report['new_assets_from_css']}")
        print(f"Discovery converged: {str(report['discovery_converged']).lower()}"); print(f"Manifest: {output}")
        return 1 if report["errors"] else 0
    except Exception as exc:
        print(f"Asset discovery failed: {exc}", file=sys.stderr); return 1


if __name__ == "__main__": raise SystemExit(main())
