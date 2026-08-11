from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse


ROOT = Path(__file__).resolve().parents[1]
CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I)
CSS_IMPORT = re.compile(r"@import\s+(?:url\(\s*)?(['\"])(.*?)\1\s*\)?", re.I)
REMOTE_URL = re.compile(r"https?://[^\s'\"<>)]+", re.I)
RUNTIME_PATTERNS = {
    "fetch": re.compile(r"\bfetch\s*\(", re.I),
    "XMLHttpRequest": re.compile(r"\bXMLHttpRequest\b"),
    "$.ajax": re.compile(r"\$\.ajax\s*\(", re.I),
    "$.get": re.compile(r"\$\.get\s*\(", re.I),
    "$.post": re.compile(r"\$\.post\s*\(", re.I),
    "axios": re.compile(r"\baxios(?:\.|\s*\()", re.I),
    "WebSocket": re.compile(r"\bWebSocket\s*\(", re.I),
    "EventSource": re.compile(r"\bEventSource\s*\(", re.I),
}
URL_HINTS = ("/api/", "/ajax/", "/search", "/cn/", "/tooltip", "/json")
CALL_URL = re.compile(r"(?:fetch|axios(?:\.get|\.post)?|\$\.(?:get|post))\s*\(\s*['\"]([^'\"]+)", re.I)
OPEN_URL = re.compile(r"\.open\s*\(\s*['\"][A-Z]+['\"]\s*,\s*['\"]([^'\"]+)", re.I)
AJAX_URL = re.compile(r"\$\.ajax\s*\(\s*\{[^}]*?\burl\s*:\s*['\"]([^'\"]+)", re.I | re.S)
SOCKET_URL = re.compile(r"(?:WebSocket|EventSource)\s*\(\s*['\"]([^'\"]+)", re.I)
JS_NAV = re.compile(r"(?:window\.)?location(?:\.href)?\s*=|window\.open\s*\(", re.I)
TRACKING_PARTS = ("google-analytics", "googletagmanager", "doubleclick", "analytics", "hotjar", "clarity.ms", "nitropay", "cloudflareinsights")


def example_add(mapping, key, value, limit=10):
    values = mapping[key]
    if value not in values and len(values) < limit: values.append(value)


def normalize_url(value, base):
    value = value.strip()
    if not value or value.startswith(("#", "data:", "blob:", "javascript:")): return None
    return urldefrag(urljoin(base, value))[0]


def is_tracking(url):
    host = (urlparse(url).hostname or "").lower()
    return any(part in host for part in TRACKING_PARTS)


class HTMLAuditParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.counts = Counter(); self.deps = {"stylesheets": [], "scripts": [], "images": [], "icons": []}
        self.inline_scripts = []; self.in_script = False; self.script_parts = []
        self.inline_styles = []; self.in_style = False; self.style_parts = []; self.interactions = set(); self.navigation = Counter()
        self.shell = {"navbar": False, "sidebar": False, "footer": False}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs); classes = attrs.get("class", "").lower(); identifier = attrs.get("id", "").lower()
        if tag == "link" and attrs.get("href"):
            rel = attrs.get("rel", "").lower(); key = "icons" if "icon" in rel else "stylesheets" if "stylesheet" in rel else None
            if key: self.deps[key].append(attrs["href"]); self.counts[f"{key[:-1]}_references"] += 1
        if tag == "script":
            if attrs.get("src"): self.deps["scripts"].append(attrs["src"]); self.counts["script_src_references"] += 1
            else: self.in_script = True; self.script_parts = []; self.counts["inline_script_blocks"] += 1
        if tag == "style": self.in_style = True; self.style_parts = []; self.counts["inline_style_blocks"] += 1
        if "style" in attrs:
            self.counts["inline_style_attributes"] += 1; self.inline_styles.append(attrs["style"])
        if tag == "img" and attrs.get("src"): self.deps["images"].append(attrs["src"]); self.counts["image_references"] += 1
        if tag == "img" and attrs.get("srcset"): self.counts["image_references"] += len([x for x in attrs["srcset"].split(",") if x.strip()])
        for key in ("data-bs-toggle", "data-bs-target", "data-bs-title", "data-toggle", "data-target"):
            if key in attrs: self.counts[f"attribute:{key}"] += 1
        toggle = (attrs.get("data-bs-toggle") or attrs.get("data-toggle") or "").lower()
        if toggle in {"tooltip", "collapse", "modal", "tab", "dropdown"}: self.interactions.add(toggle)
        if "data-bs-title" in attrs: self.interactions.add("tooltip_embedded")
        if "title" in attrs: self.counts["title_attributes"] += 1; self.interactions.add("title_tooltip")
        if "datatable" in classes.lower(): self.interactions.add("datatables")
        if tag == "a" and attrs.get("href"):
            href = attrs["href"]
            if href.startswith("#"): self.navigation["fragment"] += 1
            elif href.startswith("/cn/") or "tlidb.com/cn/" in href: self.navigation["internal_rewrite"] += 1
            elif not urlparse(href).scheme and not href.startswith(("//", "mailto:", "javascript:")): self.navigation["relative_rewrite"] += 1
            else: self.navigation["external"] += 1
            if re.search(r"(?:[?&]page=|/page/)",href,re.I): self.navigation["pagination"] += 1
        if tag == "form" and attrs.get("action"):
            self.navigation["form_action"] += 1
            if "search" in attrs["action"].lower(): self.navigation["search_action"] += 1
        if tag == "nav" or "navbar" in classes or "navbar" in identifier: self.shell["navbar"] = True
        if "sidebar" in classes or "sidebar" in identifier: self.shell["sidebar"] = True
        if tag == "footer": self.shell["footer"] = True

    def handle_endtag(self, tag):
        if tag == "script" and self.in_script:
            self.inline_scripts.append("".join(self.script_parts)); self.in_script = False
        if tag == "style" and self.in_style:
            self.inline_styles.append("".join(self.style_parts)); self.in_style = False

    def handle_data(self, data):
        if self.in_script: self.script_parts.append(data)
        if self.in_style: self.style_parts.append(data)


class RuntimeAudit:
    def __init__(self):
        self.pattern_counts = Counter(); self.pattern_sources = defaultdict(list); self.endpoints = set(); self.endpoint_sources = defaultdict(list)
        self.external_domains = Counter(); self.tracking_urls = set(); self.tracking_domains = Counter(); self.url_hint_counts = Counter()
        self.hardcoded_remote_static = set(); self.js_navigation_sources = set(); self.tooltip_sources = set()

    def scan(self, text, source, base):
        for hint in URL_HINTS: self.url_hint_counts[hint] += text.lower().count(hint)
        for name, pattern in RUNTIME_PATTERNS.items():
            count = len(pattern.findall(text)); self.pattern_counts[name] += count
            if count: example_add(self.pattern_sources, name, source)
        urls = []
        for pattern in (CALL_URL, OPEN_URL, AJAX_URL, SOCKET_URL): urls.extend(pattern.findall(text))
        for value in urls:
            url = normalize_url(value, base)
            if not url: continue
            if is_tracking(url):
                self.tracking_urls.add(url)
                host = urlparse(url).hostname
                if host: self.tracking_domains[host] += 1
                continue
            self.endpoints.add(url); example_add(self.endpoint_sources, url, source)
            host = urlparse(url).hostname
            if host: self.external_domains[host] += 1
        for url in REMOTE_URL.findall(text):
            if not is_tracking(url): self.hardcoded_remote_static.add(url.rstrip(".,;"))
        if JS_NAV.search(text): self.js_navigation_sources.add(source)
        if re.search(r"\btooltip\b",text,re.I): self.tooltip_sources.add(source)


def interaction_record(feature, pages, dependency, evidence, risk):
    return {"feature": feature, "dependency": dependency, "pages_affected": len(pages),
            "example_pages": sorted(pages)[:10], "evidence": evidence, "classification": "requires_dom_js",
            "reconstruction_risk": risk}


def audit(season, raw_root, asset_manifest_path, asset_root):
    manifest = json.loads(asset_manifest_path.read_text(encoding="utf-8")); assets = manifest.get("assets", [])
    asset_urls = {a["source_url"]: a for a in assets}; missing_files=[]; missing_meta=[]; present=0
    for asset in assets:
        path=asset_root/asset["local_relative_path"]
        meta=asset_root/"meta"/asset["asset_id"][:2]/asset["asset_id"][2:4]/f"{asset['asset_id']}.meta.json"
        if path.is_file(): present += 1
        else: missing_files.append(asset["asset_id"])
        if not meta.is_file(): missing_meta.append(asset["asset_id"])
    html_counts=Counter(); interaction_pages=defaultdict(set); shell_patterns=Counter(); shell_examples=defaultdict(list)
    runtime=RuntimeAudit(); pages=0; warnings=[]; errors=[]; page_deps=Counter(); nav=Counter()
    secondary_refs=0; missing_secondary=set(); remote_css_urls=set(); remote_imports=set()
    for system_dir in sorted(p for p in raw_root.iterdir() if p.is_dir()):
        html_dir=system_dir/"raw_html"
        if not html_dir.is_dir(): continue
        for path in sorted(html_dir.glob("*.html")):
            pages += 1; page=f"{system_dir.name}/{path.name}"; base=f"https://tlidb.com/cn/{path.stem}"
            try: text=path.read_text(encoding="utf-8"); parser=HTMLAuditParser(); parser.feed(text)
            except (OSError,UnicodeDecodeError) as exc: errors.append(f"Unable to audit {page}: {exc}"); continue
            html_counts.update(parser.counts); nav.update(parser.navigation)
            for key,values in parser.deps.items(): page_deps[key] += len(values)
            for feature in parser.interactions: interaction_pages[feature].add(page)
            for script in parser.inline_scripts: runtime.scan(script,page,base)
            for style in parser.inline_styles:
                refs=[m.group(2) for m in CSS_URL.finditer(style)]+[m.group(2) for m in CSS_IMPORT.finditer(style)]
                imports={m.group(2) for m in CSS_IMPORT.finditer(style)}
                for value in refs:
                    url=normalize_url(value,base)
                    if not url: continue
                    secondary_refs += 1
                    if urlparse(url).scheme in {"http","https"}: remote_css_urls.add(url)
                    if value in imports and urlparse(url).scheme in {"http","https"}: remote_imports.add(url)
                    target=asset_urls.get(url)
                    if target is None or not (asset_root/target["local_relative_path"]).is_file(): missing_secondary.add(url)
            signature=json.dumps({"stylesheets":parser.deps["stylesheets"],"scripts":parser.deps["scripts"],**parser.shell},sort_keys=True,ensure_ascii=False)
            shell_id=hashlib.sha256(signature.encode()).hexdigest()[:12]; shell_patterns[shell_id]+=1
            if len(shell_examples[shell_id])<5: shell_examples[shell_id].append(page)
    font_face_files=0; local_js_files=0; local_css_files=0
    for asset in assets:
        path=asset_root/asset["local_relative_path"]
        if not path.is_file() or asset.get("asset_type") not in {"stylesheet","javascript"}: continue
        try: text=path.read_text(encoding="utf-8",errors="replace")
        except OSError as exc: warnings.append(f"Unable to read asset {asset['asset_id']}: {exc}"); continue
        if asset["asset_type"]=="stylesheet":
            local_css_files += 1; font_face_files += int("@font-face" in text.lower())
            refs=[m.group(2) for m in CSS_URL.finditer(text)]+[m.group(2) for m in CSS_IMPORT.finditer(text)]
            imports={m.group(2) for m in CSS_IMPORT.finditer(text)}
            for value in refs:
                url=normalize_url(value,asset["source_url"])
                if not url: continue
                secondary_refs += 1
                if urlparse(url).scheme in {"http","https"}: remote_css_urls.add(url)
                if value in imports and urlparse(url).scheme in {"http","https"}: remote_imports.add(url)
                target=asset_urls.get(url)
                if target is None or not (asset_root/target["local_relative_path"]).is_file(): missing_secondary.add(url)
        else:
            local_js_files += 1; runtime.scan(text,f"asset:{asset['asset_id']}",asset["source_url"])
    interactions=[
        interaction_record("tooltip",interaction_pages["tooltip"]|interaction_pages["tooltip_embedded"]|interaction_pages["title_tooltip"],"Bootstrap tooltip or native title","title/data-bs-title/data-bs-toggle", "medium"),
        interaction_record("collapse",interaction_pages["collapse"],"Bootstrap Collapse","data-bs-toggle=collapse", "medium"),
        interaction_record("modal",interaction_pages["modal"],"Bootstrap Modal","data-bs-toggle=modal", "medium"),
        interaction_record("tabs",interaction_pages["tab"],"Bootstrap Tab","data-bs-toggle=tab", "medium"),
        interaction_record("dropdown",interaction_pages["dropdown"],"Bootstrap Dropdown","data-bs-toggle=dropdown", "medium"),
        interaction_record("datatables",interaction_pages["datatables"],"DataTables JS/CSS","DataTable class", "medium"),
    ]
    runtime_endpoints=sorted(runtime.endpoints); blocking=[]; non_blocking=[]
    dependency_classes=defaultdict(Counter)
    for asset in assets:
        host=(urlparse(asset["source_url"]).hostname or "").lower()
        if is_tracking(asset["source_url"]): category="tracking/ads"
        elif asset.get("asset_type")=="javascript": category="required_for_interaction"
        else: category="required_for_rendering"
        dependency_classes[category][host] += 1
    for host,count in runtime.external_domains.items(): dependency_classes["required_for_interaction"][host] += count
    if missing_files: blocking.append(f"{len(missing_files)} manifest assets are missing local files.")
    if missing_meta: blocking.append(f"{len(missing_meta)} manifest assets are missing meta files.")
    if missing_secondary: blocking.append(f"{len(missing_secondary)} CSS secondary asset URLs are missing from the local snapshot.")
    if runtime_endpoints: blocking.append(f"{len(runtime_endpoints)} concrete runtime HTTP endpoints require review or response mirroring.")
    if remote_css_urls: non_blocking.append(f"{len(remote_css_urls)} CSS URLs still require local URL rewrite after dependency closure.")
    non_blocking.append("External stylesheet/script/image references must be rewritten to downloaded local assets.")
    status="not_ready" if blocking else "ready_with_minor_gaps" if non_blocking else "ready"
    if missing_secondary and runtime_endpoints:
        recommendation=f"Mirror {len(missing_secondary)} missing CSS secondary assets and audit {len(runtime_endpoints)} concrete runtime endpoints before Full Mirror Builder."
    elif missing_secondary:
        recommendation=f"Mirror the {len(missing_secondary)} missing CSS secondary assets, then proceed to Full Mirror Builder with deterministic URL rewrite."
    elif runtime_endpoints:
        recommendation=f"Audit and mirror {len(runtime_endpoints)} concrete runtime endpoints before Full Mirror Builder."
    else:
        recommendation="Proceed to Full Mirror Builder with deterministic HTML/CSS/JS URL rewrite."
    dominant=shell_patterns.most_common(1)[0] if shell_patterns else (None,0)
    result={
        "schema_version":1,"season":season,"pages":pages,
        "assets":{"expected":len(assets),"present":present,"missing_files":missing_files,"missing_meta":missing_meta,
                  "type_counts":dict(Counter(a.get("asset_type","other") for a in assets))},
        "html_dependencies":dict(html_counts|page_deps),
        "css_audit":{"local_css_files":local_css_files,"secondary_asset_reference_count":secondary_refs,
                     "missing_secondary_assets":sorted(missing_secondary),"remote_url_count":len(remote_css_urls),
                     "remote_import_count":len(remote_imports),"font_face_file_count":font_face_files,
                     "remote_urls":sorted(remote_css_urls)[:200],"remote_imports":sorted(remote_imports)[:200]},
        "javascript_audit":{"local_js_files":local_js_files,"runtime_pattern_counts":dict(runtime.pattern_counts),
                            "runtime_url_pattern_counts":dict(runtime.url_hint_counts),
                            "runtime_pattern_examples":dict(runtime.pattern_sources),"runtime_http_endpoints":runtime_endpoints,
                            "endpoint_examples":dict(runtime.endpoint_sources),"external_runtime_domains":dict(runtime.external_domains),
                            "tracking_runtime_urls":sorted(runtime.tracking_urls),"tracking_runtime_domains":dict(runtime.tracking_domains),
                            "hardcoded_remote_static_url_count":len(runtime.hardcoded_remote_static),
                            "js_navigation_source_count":len(runtime.js_navigation_sources)},
        "interactions":interactions,
        "tooltip":{"title_attribute_count":html_counts["title_attributes"],
                   "data_bs_title_count":html_counts["attribute:data-bs-title"],
                   "embedded_pages":len(interaction_pages["tooltip_embedded"]),
                   "title_pages":len(interaction_pages["title_tooltip"]),
                   "js_runtime_source_count":len(runtime.tooltip_sources),
                   "runtime_http_endpoint_count":sum("tooltip" in url.lower() for url in runtime_endpoints),
                   "offline_assessment":"Detected tooltips are embedded in HTML or generated by downloaded JS; no tooltip runtime HTTP endpoint was found."
                   if not any("tooltip" in url.lower() for url in runtime_endpoints)
                   else "Embedded tooltips are reproducible offline, but runtime HTTP tooltip responses must also be mirrored."},
        "navigation":{"pure_rewrite_count":nav["internal_rewrite"]+nav["relative_rewrite"]+nav["fragment"],
                      "internal_url_count":nav["internal_rewrite"],"relative_url_count":nav["relative_rewrite"],
                      "fragment_count":nav["fragment"],"external_url_count":nav["external"],
                      "pagination_url_count":nav["pagination"],
                      "form_action_count":nav["form_action"],"search_action_count":nav["search_action"],
                      "js_navigation_source_count":len(runtime.js_navigation_sources),
                      "requires_replacement_count":nav["form_action"]+len(runtime.endpoints)},
        "page_shell":{"pattern_count":len(shell_patterns),"dominant_pattern":dominant[0],"dominant_page_count":dominant[1],
                      "patterns":[{"pattern_id":key,"page_count":count,"examples":shell_examples[key]} for key,count in shell_patterns.most_common()]},
        "external_dependencies":{"asset_domains":dict(Counter((urlparse(a["source_url"]).hostname or "") for a in assets)),
                                 "runtime_domains":dict(runtime.external_domains),
                                 "classifications":{key:dict(value) for key,value in dependency_classes.items()},
                                 "offline_impact":"Unrewritten external asset URLs break rendering/interaction offline; concrete runtime HTTP calls may break dynamic content."},
        "mirror_readiness":status,"blocking_dependencies":blocking,"non_blocking_dependencies":non_blocking,
        "recommended_next_step":recommendation,"warnings":warnings,"errors":errors,
    }
    return result


def markdown(result):
    a=result["assets"]; css=result["css_audit"]; js=result["javascript_audit"]; shell=result["page_shell"]; tooltip=result["tooltip"]
    lines=["# TLIDB Frontend Dependency Audit","",f"Pages: {result['pages']}",f"Assets expected: {a['expected']}",
           f"Assets present: {a['present']}",f"External runtime domains: {len(js['external_runtime_domains'])}",
           f"Runtime HTTP dependencies: {len(js['runtime_http_endpoints'])}",
           f"Tooltip: {tooltip['offline_assessment']}",f"Missing secondary assets: {len(css['missing_secondary_assets'])}",
           f"Page shell patterns: {shell['pattern_count']} (dominant: {shell['dominant_page_count']} pages)",
           f"Mirror readiness: {result['mirror_readiness']}","", "## Blocking",""]
    lines += [f"- {item}" for item in result["blocking_dependencies"]] or ["- None"]
    lines += ["","## Non-blocking","",*([f"- {item}" for item in result["non_blocking_dependencies"]] or ["- None"]),
              "","## Recommended next step","",result["recommended_next_step"],"","## Runtime HTTP endpoints",""]
    lines += [f"- {url}" for url in js["runtime_http_endpoints"]] or ["- None"]
    lines += ["","## Interactions",""]
    lines += [f"- {item['feature']}: {item['pages_affected']} pages; risk {item['reconstruction_risk']}" for item in result["interactions"]]
    return "\n".join(lines)+"\n"


def parse_args(argv=None):
    p=argparse.ArgumentParser(description="Audit local TLIDB frontend dependencies without executing JavaScript or network requests")
    p.add_argument("--season",default="ss13"); p.add_argument("--raw-root",type=Path,default=Path("data/raw/manifests"))
    p.add_argument("--asset-manifest",type=Path,default=Path("data/raw/assets/ss13/asset-manifest.json")); p.add_argument("--asset-root",type=Path,default=Path("data/raw/assets/ss13/files"))
    p.add_argument("--output",type=Path,default=Path("data/reports/local-wiki/frontend-dependency-audit.json")); return p.parse_args(argv)


def resolve(path): return path if path.is_absolute() else ROOT/path


def main(argv=None):
    args=parse_args(argv)
    try:
        result=audit(args.season,resolve(args.raw_root),resolve(args.asset_manifest),resolve(args.asset_root)); output=resolve(args.output); output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); output.with_suffix(".md").write_text(markdown(result),encoding="utf-8")
        print(f"Pages: {result['pages']}"); print(f"Assets: {result['assets']['present']}/{result['assets']['expected']}")
        print(f"Missing secondary assets: {len(result['css_audit']['missing_secondary_assets'])}"); print(f"Mirror readiness: {result['mirror_readiness']}")
        return 1 if result["errors"] else 0
    except Exception as exc: print(f"Frontend dependency audit failed: {exc}",file=sys.stderr); return 1


if __name__=="__main__": raise SystemExit(main())
