from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from crawler.discover_inventory_manifest import (
    INDEX_URL,
    LinkParser,
    build_manifest,
    extract_index_entries,
    inventory_url,
)
from crawler.discover_manifest import USER_AGENT, download_index, ssl_context


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_ROUTE = re.compile(r"(?:https?://(?:www\.)?tlidb\.com)?/cn/[A-Za-z0-9_.%:()\-]+", re.I)
RUNTIME = re.compile(r"fetch\s*\(|XMLHttpRequest|\$\.(?:ajax|get|getJSON|post)\s*\(|serverSide\s*:\s*true", re.I)
SAMPLES = ("STR_Helmet", "DEX_Helmet", "STR_Chest_Armor", "One-Handed_Sword", "Vorax_Season")


class ScriptParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.in_script = False; self.parts = []; self.scripts = []
    def handle_starttag(self, tag, attrs):
        if tag == "script" and not dict(attrs).get("src"):
            self.in_script = True; self.parts = []
    def handle_data(self, data):
        if self.in_script: self.parts.append(data)
    def handle_endtag(self, tag):
        if tag == "script" and self.in_script:
            self.scripts.append("".join(self.parts)); self.in_script = False


class DetailParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.in_title = False; self.title = []; self.canonical = None; self.text = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title": self.in_title = True
        if tag == "link" and "canonical" in attrs.get("rel", "").lower(): self.canonical = attrs.get("href")
    def handle_endtag(self, tag):
        if tag == "title": self.in_title = False
    def handle_data(self, data):
        if self.in_title: self.title.append(data)
        if len(self.text) < 100: self.text.append(data)


def route_path(value):
    parsed = urlsplit(value)
    return "/" + "/".join(unquote(part) for part in parsed.path.split("/") if part)


def audit_index_html(document, index_url=INDEX_URL):
    parser = LinkParser(); parser.feed(document)
    occurrences = 0; direct = set(); deeper = set(); query = 0; fragment = 0; invalid = []
    inventory_links = []
    for link in parser.links:
        raw = html.unescape((link["href"] or "").strip()); raw_parts = urlsplit(raw)
        if (raw and not raw.startswith(("/", "#")) and not raw_parts.scheme
                and not raw_parts.netloc and raw_parts.path and "/" not in raw_parts.path):
            inventory_links.append(link)
    for link in inventory_links:
        raw = html.unescape(link["href"]); parsed_raw = urlsplit(urljoin(index_url, raw))
        entry, reason = inventory_url(raw, index_url)
        if reason != "accepted":
            if "inventory" in raw.lower() and reason not in {"not_inventory", "external"}: invalid.append(raw)
            continue
        occurrences += 1; query += int(bool(parsed_raw.query)); fragment += int(bool(parsed_raw.fragment))
        if entry["depth"] == 2: direct.add(entry["path"])
        else: deeper.add(entry["path"])
    scripts = ScriptParser(); scripts.feed(document)
    dynamic_scripts = [script for script in scripts.scripts if RUNTIME.search(script) and "inventory" in script.lower()]
    hidden = []
    for script in dynamic_scripts:
        for match in INVENTORY_ROUTE.findall(html.unescape(script)):
            entry, reason = inventory_url(match, index_url)
            if reason == "accepted" and entry["path"] not in direct:
                hidden.append(entry["path"])
    hidden = sorted(set(hidden))
    lower = document.lower()
    pagination = bool(
        re.search(r'class=["\'][^"\']*\bpagination\b', lower)
        or re.search(r'rel=["\']next["\']', lower)
        or re.search(r'href=["\'][^"\']*(?:[?&](?:page|offset)=)', lower)
        or any(term in lower for term in ("下一页", "load more", "加载更多", "infinite scroll"))
    )
    tab_markers = len(re.findall(r'data-bs-toggle=["\']tab["\']|data-toggle=["\']tab["\']', lower))
    return {
        "index_inventory_occurrences": occurrences,
        "index_unique_direct_children": len(direct),
        "direct_children": sorted(direct),
        "index_deeper_routes": len(deeper),
        "deeper_route_examples": sorted(deeper)[:20],
        "index_query_variants": query,
        "index_fragment_variants": fragment,
        "invalid_routes": invalid,
        "pagination_detected": pagination,
        "dynamic_loading_detected": bool(dynamic_scripts),
        "dynamic_loading_script_count": len(dynamic_scripts),
        "tab_markers": tab_markers,
        "hidden_route_evidence": hidden,
        "all_embedded_inventory_routes_exposed_in_html_links": not hidden,
    }


def validate_static_entries(entries):
    urls = Counter(); ids = Counter(); paths = Counter(); malformed = []; valid = 0; unexpected_depth = []
    for entry in entries:
        url = entry.get("url", ""); slug = entry.get("slug", ""); path = entry.get("path", "")
        parsed = urlsplit(url); parts = [part for part in parsed.path.split("/") if part]
        reasons = []
        if parsed.scheme != "https": reasons.append("scheme")
        if (parsed.hostname or "").lower() != "tlidb.com": reasons.append("host")
        if len(parts) != 2 or parts[:1] != ["cn"]: reasons.append("depth")
        if not slug or not parts or unquote(parts[-1]) != slug: reasons.append("slug")
        if path != parsed.path: reasons.append("path")
        if reasons: malformed.append({"url": url, "reasons": reasons})
        else: valid += 1
        if "depth" in reasons: unexpected_depth.append(url)
        urls[url] += 1; ids[entry.get("id")] += 1; paths[path] += 1
    duplicates = sorted({value for counts in (urls, ids, paths) for value, count in counts.items() if count > 1})
    return {"entries": len(entries), "valid": valid, "duplicates": duplicates,
            "duplicate_count": len(duplicates), "malformed": malformed,
            "malformed_count": len(malformed), "unexpected_depth": unexpected_depth}


def validate_detail_html(url, status, final_url, document):
    parser = DetailParser(); parser.feed(document)
    title = " ".join("".join(parser.title).split()); canonical = urljoin(final_url, parser.canonical) if parser.canonical else None
    expected_path = route_path(url); final_path = route_path(final_url); canonical_path = route_path(canonical) if canonical else None
    text = " ".join("".join(parser.text).split()).lower()
    error_shell = any(term in (title + " " + text).lower() for term in ("404", "not found", "error response", "页面不存在"))
    canonical_ok = canonical_path is None or canonical_path == expected_path
    valid = status == 200 and final_path == expected_path and canonical_ok and bool(title) and not error_shell
    return {"url": url, "http_status": status, "final_url": final_url,
            "redirected": final_url != url, "canonical": canonical, "title": title,
            "valid_content_page": valid, "error_shell_detected": error_shell}


def fetch_detail(url, timeout):
    request = Request(url, headers={"User-Agent": USER_AGENT, "Referer": "https://tlidb.com/cn/"})
    try:
        with urlopen(request, timeout=timeout, context=ssl_context()) as response:
            body = response.read(); encoding = response.headers.get_content_charset() or "utf-8"
            return response.status, response.geturl(), body.decode(encoding, errors="replace")
    except HTTPError as exc:
        body = exc.read(); encoding = exc.headers.get_content_charset() or "utf-8"
        return exc.code, exc.geturl(), body.decode(encoding, errors="replace")


def choose_samples(entries):
    by_slug = {entry["slug"]: entry for entry in entries}
    return [by_slug[slug] for slug in SAMPLES if slug in by_slug][:5]


def decide(index_status, index_audit, static, samples):
    checks = {
        "index_http_200": index_status == 200,
        "direct_children_147": index_audit["index_unique_direct_children"] == 147,
        "no_pagination": not index_audit["pagination_detected"],
        "no_dynamic_loading": not index_audit["dynamic_loading_detected"],
        "no_hidden_routes": not index_audit["hidden_route_evidence"],
        "detail_samples_valid": 1 <= len(samples) <= 5 and all(item["valid_content_page"] for item in samples),
        "str_helmet_valid": any(item["url"].endswith("/STR_Helmet") and item["valid_content_page"] for item in samples),
        "static_urls_valid": static["entries"] == 147 and static["valid"] == 147 and
                             static["duplicate_count"] == 0 and static["malformed_count"] == 0,
    }
    ready = all(checks.values())
    failed = [name for name, passed in checks.items() if not passed]
    return {"inventory_manifest_ready": ready, "confirmed": ready,
            "checks": checks, "reason": "all validation criteria passed" if ready else "blocked: " + ", ".join(failed)}


def markdown(report):
    index, static, decision = report["index"], report["static_validation"], report["decision"]
    lines = ["# Inventory Manifest Final Validation", "", "## Index", "",
             f"- HTTP: {index['http_status']}", f"- Occurrences: {index['index_inventory_occurrences']}",
             f"- Unique direct children: {index['index_unique_direct_children']}",
             f"- Deeper routes: {index['index_deeper_routes']}", f"- Pagination detected: {index['pagination_detected']}",
             f"- Dynamic loading detected: {index['dynamic_loading_detected']}",
             f"- Hidden route evidence: {len(index['hidden_route_evidence'])}", "", "## Samples", ""]
    lines.extend(f"- {item['url']}: HTTP {item['http_status']}, valid={item['valid_content_page']}" for item in report["sample_validation"])
    lines.extend(["", "## Static validation", "", f"- Entries: {static['entries']}", f"- Valid: {static['valid']}",
                  f"- Duplicates: {static['duplicate_count']}", f"- Malformed: {static['malformed_count']}",
                  "", "## Decision", "", f"- Manifest ready: {decision['inventory_manifest_ready']}",
                  f"- Confirmed: {decision['confirmed']}", f"- Reason: {decision['reason']}"])
    return "\n".join(lines) + "\n"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Final validation for the 147-entry TLIDB Inventory manifest")
    parser.add_argument("--manifest", type=Path, default=Path("sources/inventory_manifest.json"))
    parser.add_argument("--report", type=Path, default=Path("data/reports/system-discovery/inventory-validation-report.json"))
    parser.add_argument("--timeout", type=float, default=20.0); return parser.parse_args(argv)


def resolve(path): return path if path.is_absolute() else ROOT / path


def main(argv=None):
    args = parse_args(argv)
    try:
        body, status, encoding = download_index(INDEX_URL, args.timeout); document = body.decode(encoding, errors="replace")
        index_audit = audit_index_html(document); index_audit["http_status"] = status
        discovered_entries, index_info = extract_index_entries(document)
        manifest = build_manifest(discovered_entries, {
            "fetched_at": None, "http_status": status, "html_sha256": None, **index_info,
        }, [])
        entries = manifest["entries"]
        samples = []
        for entry in choose_samples(entries):
            detail_status, final_url, detail_html = fetch_detail(entry["url"], args.timeout)
            samples.append(validate_detail_html(entry["url"], detail_status, final_url, detail_html))
        static = validate_static_entries(entries); decision = decide(status, index_audit, static, samples)
        report = {"title":"Inventory Manifest Final Validation", "index":index_audit,
                  "sample_validation":samples, "static_validation":static, "decision":decision,
                  "url_resolution": {
                      "previous_incorrect_assumption": "/cn/Inventory/<entry>",
                      "route_pattern": "/cn/<inventory_entry>",
                      "base": INDEX_URL, "raw_href": "STR_Helmet",
                      "resolved": "https://tlidb.com/cn/STR_Helmet",
                  },
                  "validated_manifest": manifest,
                  "network_requests":{"index":1,"detail_pages":len(samples),"assets":0}, "warnings":[], "errors":[]}
        report_path = resolve(args.report); report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        report_path.with_name("inventory-validation-summary.md").write_text(markdown(report),encoding="utf-8")
        print(f"Index direct children: {index_audit['index_unique_direct_children']}")
        print(f"Detail samples valid: {sum(item['valid_content_page'] for item in samples)}/{len(samples)}")
        print(f"Manifest ready: {str(decision['inventory_manifest_ready']).lower()}")
        return 0 if decision["inventory_manifest_ready"] and not report["errors"] else 1
    except Exception as exc:
        print(f"Inventory validation failed: {exc}",file=sys.stderr); return 1


if __name__ == "__main__": raise SystemExit(main())
