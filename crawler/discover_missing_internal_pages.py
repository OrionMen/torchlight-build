from __future__ import annotations

import argparse
import json
import threading
import time
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request, urlopen

from crawler.build_full_wiki_mirror import canonical_page_key, tracking_url
from crawler.fetch_all_manifests import RateLimiter
from crawler.fetch_manifest import USER_AGENT, request_url_for, ssl_context, write_json


ROOT = Path(__file__).resolve().parents[1]
STATIC_SUFFIXES = {
    ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".mp4", ".webm", ".pdf",
}
STABLE_VALIDATION = {"available", "not_found", "redirected", "invalid"}


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


def semantic_url(value, base):
    key = canonical_page_key(value, base)
    if not key or tracking_url(key):
        return None
    parsed = urlsplit(key)
    path = unquote(parsed.path)
    if path.rstrip("/") == "/cn" or Path(path).suffix.lower() in STATIC_SUFFIXES:
        return None
    return "https://tlidb.com" + path.rstrip("/")


def raw_file(raw_root, system_id, slug):
    return raw_root / system_id / "raw_html" / f"{quote(slug, safe='-_.')}.html"


def collect_manifest_pages(system_manifest_path, raw_root):
    pages = []
    existing = set()
    for system in load_json(system_manifest_path).get("systems", []):
        status = system.get("discovery_status") or system.get("status")
        if status != "confirmed":
            continue
        manifest_path = Path(system["manifest_path"])
        if not manifest_path.is_absolute():
            manifest_path = ROOT / manifest_path
        for entry in load_json(manifest_path).get("entries", []):
            source_url = entry.get("url")
            slug = entry.get("slug") or entry.get("id")
            if not source_url or not slug:
                continue
            html_path = raw_file(raw_root, system["system_id"], slug)
            if html_path.is_file():
                existing.add(canonical_page_key(source_url))
                pages.append({"system_id": system["system_id"], "page_id": entry.get("id"),
                              "source_url": source_url, "html_path": html_path})
    return pages, existing


def collect_meta_existing(raw_root):
    existing = set()
    for meta_path in raw_root.glob("*/meta/*.meta.json"):
        try:
            meta = load_json(meta_path)
        except (OSError, json.JSONDecodeError):
            continue
        source_url = meta.get("source_url") or meta.get("url") or meta.get("final_url")
        key = canonical_page_key(source_url) if source_url else None
        html_path = meta_path.parents[1] / "raw_html" / meta_path.name.removesuffix(".meta.json").replace(".meta", "")
        if key and (html_path.with_suffix(".html").is_file() or
                    (meta_path.parents[1] / "raw_html" / (meta_path.stem.removesuffix(".meta") + ".html")).is_file()):
            existing.add(key)
    return existing


def discover(system_manifest_path, raw_root, catalog_path):
    pages, raw_existing = collect_manifest_pages(system_manifest_path, raw_root)
    raw_existing.update(collect_meta_existing(raw_root))
    catalog = load_json(catalog_path)
    catalog_existing = {canonical_page_key(page.get("source_url")) for page in catalog.get("pages", [])}
    catalog_existing.discard(None)
    existing_keys = raw_existing | catalog_existing
    targets = OrderedDict()
    internal_occurrences = 0
    existing_occurrences = 0

    for page in pages:
        parser = LinkParser()
        try:
            parser.feed(page["html_path"].read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        for raw_href in parser.hrefs:
            canonical = semantic_url(raw_href, page["source_url"])
            if canonical is None:
                continue
            internal_occurrences += 1
            key = canonical_page_key(canonical)
            if key in existing_keys:
                existing_occurrences += 1
            item = targets.setdefault(key, {"canonical_url": canonical,
                "canonical_path": unquote(urlsplit(canonical).path),
                "request_url": request_url_for(canonical), "slug": unquote(urlsplit(canonical).path).rstrip("/").rsplit("/", 1)[-1],
                "occurrence_count": 0, "source_examples": [], "existing": key in existing_keys})
            item["occurrence_count"] += 1
            example = {"system_id": page["system_id"], "page_id": page["page_id"],
                       "source_url": page["source_url"], "raw_href": raw_href}
            if len(item["source_examples"]) < 5 and example not in item["source_examples"]:
                item["source_examples"].append(example)

    candidates = [item for item in targets.values() if not item["existing"]]
    return {
        "internal_link_occurrences": internal_occurrences,
        "unique_internal_targets": len(targets),
        "existing_targets": sum(item["existing"] for item in targets.values()),
        "existing_target_occurrences": existing_occurrences,
        "missing_candidate_occurrences": sum(item["occurrence_count"] for item in candidates),
        "unique_missing_candidates": len(candidates),
        "validation": {"status": "not_run", "validated": 0, "available": 0,
                       "not_found": 0, "redirected": 0, "network_error": 0, "invalid": 0},
        "candidates": candidates,
        "warnings": [], "errors": [],
    }


def classify_response(candidate, status, final_url, document):
    if status == 404:
        return {"status": "not_found", "http_status": 404, "final_url": final_url}
    if status >= 500:
        return {"status": "network_error", "http_status": status, "final_url": final_url}
    canonical_final = semantic_url(final_url, candidate["canonical_url"])
    if canonical_final and canonical_final != candidate["canonical_url"]:
        return {"status": "redirected", "http_status": status, "final_url": final_url}
    lower = document[:20000].lower()
    if status != 200 or any(marker in lower for marker in ("<title>404", "not found</title>", "页面不存在")):
        return {"status": "invalid", "http_status": status, "final_url": final_url}
    return {"status": "available", "http_status": 200, "final_url": final_url}


def validate_one(candidate, timeout, opener=urlopen):
    request = Request(candidate["request_url"], headers={"User-Agent": USER_AGENT,
                                                         "Referer": "https://tlidb.com/cn/"})
    try:
        with opener(request, timeout=timeout, context=ssl_context()) as response:
            body = response.read(); encoding = response.headers.get_content_charset() or "utf-8"
            return classify_response(candidate, response.status, response.geturl(),
                                     body.decode(encoding, errors="replace"))
    except HTTPError as exc:
        if exc.code == 404:
            return {"status": "not_found", "http_status": 404, "final_url": exc.geturl()}
        return {"status": "network_error", "http_status": exc.code,
                "final_url": exc.geturl(), "error": str(exc)}
    except (URLError, TimeoutError, OSError) as exc:
        return {"status": "network_error", "http_status": None,
                "final_url": None, "error": str(exc)}


def validate_candidates(report, cache_path, max_workers, rate_limit, timeout,
                        validator=validate_one):
    cache = load_json(cache_path) if cache_path.is_file() else {"results": {}}
    results = cache.setdefault("results", {})
    pending = [item for item in report["candidates"]
               if results.get(item["canonical_url"], {}).get("status") not in STABLE_VALIDATION]
    limiter = RateLimiter(rate_limit)
    lock = threading.Lock()

    def run(item):
        limiter.wait()
        return validator(item, timeout)

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(run, item): item for item in pending}
            completed = 0
            for future in as_completed(futures):
                item = futures[future]
                result = future.result()
                with lock:
                    results[item["canonical_url"]] = result
                    write_json(cache_path, cache)
                completed += 1
                print(f"Validated {completed}/{len(pending)}: {result['status']}")
    except KeyboardInterrupt:
        write_json(cache_path, cache)
        raise

    counts = Counter()
    for item in report["candidates"]:
        result = results.get(item["canonical_url"])
        if result:
            item["validation"] = result
            counts[result["status"]] += 1
    report["validation"] = {"status": "completed", "validated": sum(counts.values()),
                            **{name: counts[name] for name in ("available", "not_found", "redirected", "network_error", "invalid")}}
    return report


def preview(report):
    entries = []
    for item in report["candidates"]:
        validation = item.get("validation", {})
        if validation.get("status") != "available":
            continue
        entries.append({"id": item["slug"], "slug": item["slug"], "path": item["canonical_path"],
                        "url": item["canonical_url"], "request_url": item["request_url"],
                        "validation": {"status": "available", "http_status": 200},
                        "discovered_from": item["source_examples"]})
    return {"schema_version": 1, "entry_count": len(entries), "entries": entries}


def summary_markdown(report):
    validation = report["validation"]
    return ("# Missing Internal Pages\n\n"
            f"- Internal link occurrences: {report['internal_link_occurrences']}\n"
            f"- Unique internal targets: {report['unique_internal_targets']}\n"
            f"- Existing targets: {report['existing_targets']}\n"
            f"- Missing candidate occurrences: {report['missing_candidate_occurrences']}\n"
            f"- Unique missing candidates: {report['unique_missing_candidates']}\n"
            f"- Validation: {validation['status']}\n")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Discover missing TLIDB internal pages from local Raw HTML")
    parser.add_argument("--system-manifest", type=Path, default=Path("sources/system_manifest.json"))
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw/manifests"))
    parser.add_argument("--catalog", type=Path, default=Path("local_wiki/ss13/site/catalog.json"))
    parser.add_argument("--output", type=Path, default=Path("data/reports/local-wiki/missing-internal-pages.json"))
    parser.add_argument("--cache", type=Path, default=Path("data/reports/local-wiki/missing-page-validation-cache.json"))
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--rate-limit", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args(argv)


def resolve(path):
    return path if path.is_absolute() else ROOT / path


def main(argv=None):
    args = parse_args(argv)
    report = discover(resolve(args.system_manifest), resolve(args.raw_root), resolve(args.catalog))
    if args.validate:
        report = validate_candidates(report, resolve(args.cache), args.max_workers, args.rate_limit, args.timeout)
    output = resolve(args.output); write_json(output, report)
    output.with_name("missing-internal-pages-summary.md").write_text(summary_markdown(report), encoding="utf-8")
    if args.validate:
        write_json(output.with_name("recovered-internal-pages-preview.json"), preview(report))
    print(f"Internal occurrences: {report['internal_link_occurrences']}")
    print(f"Unique targets: {report['unique_internal_targets']}")
    print(f"Existing: {report['existing_targets']}")
    print(f"Missing candidates: {report['unique_missing_candidates']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
