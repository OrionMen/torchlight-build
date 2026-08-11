from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import posixpath
import re
import shutil
import sys
import time
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urldefrag, urljoin, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
ASSET_ATTRS = {"img": ("src", "srcset"), "link": ("href",), "script": ("src",),
               "source": ("src", "srcset"), "video": ("poster",), "object": ("data",)}
TRACKING = ("google-analytics", "googletagmanager", "doubleclick", "facebook.net", "hotjar",
            "clarity.ms", "adservice", "analytics", "nitropay", "cloudflareinsights")
CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I)
CSS_IMPORT = re.compile(r"(@import\s+)(['\"])(.*?)\2", re.I)
ATTR = r"(?P<prefix>\b%s\s*=\s*)(?P<quote>['\"]?)(?P<value>.*?)(?P=quote)(?=\s|/?>)"
RUNTIME = re.compile(r"\bfetch\s*\(|\bXMLHttpRequest\b|\$\.(?:ajax|get|post|getJSON)\s*\(|\baxios(?:\.|\s*\()", re.I)
RUNTIME_URL = re.compile(r"(?:fetch|axios(?:\.get|\.post)?|\$\.(?:get|post|getJSON))\s*\(\s*['\"]([^'\"]+)|\.open\s*\(\s*['\"][A-Z]+['\"]\s*,\s*['\"]([^'\"]+)", re.I)
AJAX_URL = re.compile(r"\$\.ajax\s*\(\s*\{[^}]*?\burl\s*:\s*['\"]([^'\"]+)", re.I | re.S)


def runtime_urls(text):
    values = [(match.group(1) or match.group(2)) for match in RUNTIME_URL.finditer(text)]
    values.extend(match.group(1) for match in AJAX_URL.finditer(text))
    return values


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(path):
    return path if path.is_absolute() else ROOT / path


def normalized_url(value, base, stats=None):
    value = html.unescape(value.strip())
    if not value or value.startswith(("#", "data:", "blob:", "javascript:", "mailto:")): return None
    resolved = urldefrag(urljoin(base, value))[0]
    parsed = urlsplit(value)
    if not parsed.scheme and not parsed.netloc and not parsed.path.startswith("/"):
        if stats is not None:
            stats["relative_url_resolutions"] += 1
            legacy_directory_join = urldefrag(urljoin(base.rstrip("/") + "/", value))[0]
            stats["wrong_directory_join_prevented"] += int(legacy_directory_join != resolved)
    return resolved


def tracking_url(value):
    host = (urlsplit(value).hostname or "").lower()
    return any(part in host for part in TRACKING)


def canonical_page_key(value, base="https://tlidb.com/cn/", stats=None):
    resolved = normalized_url(value, base, stats)
    if not resolved: return None
    parsed = urlsplit(resolved)
    host = (parsed.hostname or "").lower()
    if host not in {"tlidb.com", "www.tlidb.com"} or not parsed.path.startswith("/cn/"): return None
    path = "/" + "/".join(quote(unquote(part), safe="-_.~%:") for part in parsed.path.split("/") if part)
    return "https://tlidb.com" + path.rstrip("/")


def route_for_source(source_url):
    key = canonical_page_key(source_url)
    if not key: raise ValueError(f"Unsupported page URL: {source_url}")
    parts = [unquote(part) for part in urlsplit(key).path.split("/") if part]
    if any(part in {".", ".."} or "/" in part for part in parts): raise ValueError(f"Unsafe page URL: {source_url}")
    path = "/".join(parts)
    return f"{path}/index.html"


def pages_from_system_manifest(system_manifest_path, requested_system_id=None):
    system_manifest = load_json(system_manifest_path)
    pages = []
    systems_included = []
    known_missing = []
    for system in system_manifest.get("systems", []):
        status = system.get("discovery_status") or system.get("status")
        system_id = system.get("system_id")
        if status != "confirmed" or (requested_system_id and system_id != requested_system_id):
            continue
        manifest_value = system.get("manifest_path")
        if not manifest_value:
            raise ValueError(f"Confirmed system {system_id!r} has no manifest_path")
        manifest_path = Path(manifest_value)
        if not manifest_path.is_absolute():
            manifest_path = ROOT / manifest_path
        manifest = load_json(manifest_path)
        systems_included.append(system_id)
        for entry in manifest.get("entries", []):
            if entry.get("validation", {}).get("status") == "not_found":
                known_missing.append({"system_id": system_id, "id": entry.get("id")})
                continue
            pages.append({
                "system_id": system_id,
                "source_type": "official_system",
                "id": entry.get("id") or entry.get("slug"),
                "slug": entry.get("slug") or entry.get("id"),
                "title": entry.get("name_zh") or entry.get("name") or entry.get("id"),
                "source_url": entry.get("url"),
            })
    return pages, systems_included, known_missing


def pages_from_supplemental_manifest(manifest_path, requested_system_id=None):
    if manifest_path is None or not manifest_path.is_file():
        return []
    manifest = load_json(manifest_path)
    system_id = manifest.get("system_id") or "recovered_internal_pages"
    if requested_system_id and requested_system_id != system_id:
        return []
    pages = []
    for entry in manifest.get("entries", []):
        if entry.get("validation", {}).get("status") != "available":
            continue
        pages.append({
            "system_id": system_id, "source_type": "recovered_internal",
            "id": entry.get("id") or entry.get("slug"),
            "slug": entry.get("slug") or entry.get("id"),
            "title": entry.get("name_zh") or entry.get("name") or entry.get("id"),
            "source_url": entry.get("url"),
        })
    return pages


def supplemental_route_for_source(source_url):
    key = canonical_page_key(source_url)
    if not key:
        raise ValueError(f"Unsupported page URL: {source_url}")
    parts = [quote(unquote(part), safe="-_.~") for part in urlsplit(key).path.split("/") if part]
    return "/".join(parts) + "/index.html"


def output_path_for_route(output, route):
    return output / unquote(route)


def replace_attribute(raw, name, callback):
    pattern = re.compile(ATTR % re.escape(name), re.I | re.S)
    def replace(match):
        value = callback(match.group("value"))
        if value is None: return match.group(0)
        quote_char = match.group("quote") or '"'
        return match.group("prefix") + quote_char + html.escape(value, quote=True) + quote_char
    return pattern.sub(replace, raw, count=1)


def append_or_replace_attribute(raw, name, value):
    changed = replace_attribute(raw, name, lambda _: value)
    if changed != raw: return changed
    return re.sub(r"\s*/?>$", lambda m: f' {name}="{html.escape(value, quote=True)}"{m.group(0)}', raw)


class TextInspector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.skip = 0; self.text = []; self.title = ""; self.in_title = False
    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "nav", "footer"}: self.skip += 1
        if tag == "title": self.in_title = True
    def handle_endtag(self, tag):
        if tag in {"script", "style", "nav", "footer"} and self.skip: self.skip -= 1
        if tag == "title": self.in_title = False
    def handle_data(self, data):
        if self.in_title: self.title += data
        if not self.skip: self.text.append(data)


class CSSRewriter:
    def __init__(self, asset_map, web_prefix):
        self.asset_map = asset_map; self.web_prefix = web_prefix; self.rewrites = 0; self.unresolved = Counter(); self.stats = Counter()

    def target(self, value, source_url, relative_from=None):
        absolute = normalized_url(value, source_url, self.stats)
        if not absolute: return None
        asset = self.asset_map.get(absolute)
        if not asset:
            if urlsplit(absolute).scheme in {"http", "https"} and not tracking_url(absolute): self.unresolved[urlsplit(absolute).hostname or ""] += 1
            return None
        fragment = urlsplit(html.unescape(value)).fragment
        target = "assets/" + asset["local_relative_path"]
        rewritten = posixpath.relpath(target, posixpath.dirname(relative_from)) if relative_from else self.web_prefix + target
        if fragment: rewritten += "#" + fragment
        self.rewrites += 1
        return rewritten

    def rewrite(self, text, source_url, relative_from=None):
        def css_url(match):
            target = self.target(match.group(2), source_url, relative_from)
            return match.group(0) if target is None else f"url({match.group(1)}{target}{match.group(1)})"
        text = CSS_URL.sub(css_url, text)
        def css_import(match):
            target = self.target(match.group(3), source_url, relative_from)
            return match.group(0) if target is None else match.group(1) + match.group(2) + target + match.group(2)
        return CSS_IMPORT.sub(css_import, text)


class HTMLRewriter(HTMLParser):
    def __init__(self, base_url, route_map, asset_map, web_prefix, css_rewriter):
        super().__init__(convert_charrefs=False)
        self.base_url = base_url; self.route_map = route_map; self.asset_map = asset_map
        self.web_prefix = web_prefix; self.search_url = web_prefix + "_local/search/"; self.css = css_rewriter
        self.output = []; self.skip_tag = None; self.skip_depth = 0; self.in_style = False; self.in_script = False
        self.stats = Counter(); self.unresolved_internal = set(); self.runtime_examples = []

    def asset_value(self, value):
        absolute = normalized_url(value, self.base_url, self.stats)
        if not absolute: return None
        asset = self.asset_map.get(absolute)
        if not asset:
            if urlsplit(absolute).scheme in {"http", "https"} and not tracking_url(absolute):
                self.stats["remaining_remote_asset_references"] += 1
                self.stats[f"remote_domain:{urlsplit(absolute).hostname or ''}"] += 1
            return None
        self.stats["html_asset_rewrites"] += 1
        fragment = urlsplit(html.unescape(value)).fragment
        target = self.web_prefix + "assets/" + asset["local_relative_path"]
        return target + (("#" + fragment) if fragment else "")

    def srcset(self, value):
        parts = []
        for entry in value.split(","):
            pieces = entry.strip().split(None, 1)
            if not pieces: continue
            target = self.asset_value(pieces[0]) or pieces[0]
            parts.append(target + ((" " + pieces[1]) if len(pieces) > 1 else ""))
        return ", ".join(parts)

    def internal_href(self, value):
        parsed = urlsplit(html.unescape(value)); key = canonical_page_key(value, self.base_url, self.stats)
        if not key: return None
        route = self.route_map.get(key)
        if not route:
            self.unresolved_internal.add(key); self.stats["internal_page_links_unresolved"] += 1
            if not parsed.scheme and not parsed.netloc and not parsed.path.startswith("/"):
                self.stats["relative_catalog_miss_canonicalized"] += 1
                suffix = (("?" + parsed.query) if parsed.query else "") + (("#" + parsed.fragment) if parsed.fragment else "")
                return key + suffix
            return None
        self.stats["internal_page_links_rewritten"] += 1
        suffix = (("?" + parsed.query) if parsed.query else "") + (("#" + parsed.fragment) if parsed.fragment else "")
        return self.web_prefix + route.removesuffix("index.html") + suffix

    def is_tracking_element(self, raw):
        lower = html.unescape(raw).lower()
        return any(part in lower for part in TRACKING)

    def handle_starttag(self, tag, attrs):
        if self.skip_tag:
            if tag == self.skip_tag: self.skip_depth += 1
            return
        raw = self.get_starttag_text()
        if tag in {"script", "iframe", "ins"} and self.is_tracking_element(raw):
            self.skip_tag = tag; self.skip_depth = 1; self.stats["tracking_elements_removed"] += 1; return
        if tag in {"link", "img", "source"} and self.is_tracking_element(raw):
            self.stats["tracking_elements_removed"] += 1; return
        for attr in ASSET_ATTRS.get(tag, ()):
            raw = replace_attribute(raw, attr, self.srcset if attr == "srcset" else self.asset_value)
        if tag == "a": raw = replace_attribute(raw, "href", self.internal_href)
        if tag == "form":
            before = raw; raw = replace_attribute(raw, "action", lambda _: self.search_url)
            if raw != before:
                raw = append_or_replace_attribute(raw, "method", "get"); self.stats["search_forms_rewritten"] += 1
        before = raw
        raw = replace_attribute(raw, "style", lambda value: self.css.rewrite(value, self.base_url))
        self.output.append(raw)
        self.in_style = tag == "style"; self.in_script = tag == "script"

    def handle_startendtag(self, tag, attrs):
        if self.skip_tag: return
        raw = self.get_starttag_text()
        if self.is_tracking_element(raw): self.stats["tracking_elements_removed"] += 1; return
        for attr in ASSET_ATTRS.get(tag, ()):
            raw = replace_attribute(raw, attr, self.srcset if attr == "srcset" else self.asset_value)
        self.output.append(raw)

    def handle_endtag(self, tag):
        if self.skip_tag:
            if tag == self.skip_tag:
                self.skip_depth -= 1
                if self.skip_depth == 0: self.skip_tag = None
            return
        self.output.append(f"</{tag}>")
        if tag == "style": self.in_style = False
        if tag == "script": self.in_script = False

    def handle_data(self, data):
        if self.skip_tag: return
        if self.in_style:
            data = self.css.rewrite(data, self.base_url)
        if self.in_script:
            count = len(RUNTIME.findall(data)); self.stats["runtime_http_reference_count"] += count
            if count and len(self.runtime_examples) < 20:
                for value in runtime_urls(data):
                    if value: self.runtime_examples.append({"page": self.base_url, "reference": value})
            data = rewrite_i18n_runtime_paths(data, self.web_prefix)
        self.output.append(data)
    def handle_entityref(self, name): self.output.append(f"&{name};") if not self.skip_tag else None
    def handle_charref(self, name): self.output.append(f"&#{name};") if not self.skip_tag else None
    def handle_comment(self, data): self.output.append(f"<!--{data}-->") if not self.skip_tag else None
    def handle_decl(self, decl): self.output.append(f"<!{decl}>") if not self.skip_tag else None
    def handle_pi(self, data): self.output.append(f"<?{data}>") if not self.skip_tag else None


def local_assets():
    return {
        "_local/search/index.html": """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TLIDB Local Search</title><link rel="stylesheet" href="styles.css"><script defer src="app.js"></script></head><body><main><h1>TLIDB Local Search</h1><input id="search" type="search" placeholder="搜索全部本地页面" autocomplete="off"><p id="status">正在载入索引……</p><div id="results"></div></main></body></html>""",
        "_local/search/styles.css": """body{margin:0;background:#f5f6f8;color:#20242a;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1000px;margin:auto;padding:24px}#search{box-sizing:border-box;width:100%;padding:12px;font-size:18px}.group{margin-top:24px}.result{margin:10px 0;padding:12px;background:#fff;border-radius:6px}.result a{color:#075985;text-decoration:none}mark{background:#ffe58f}""",
        "_local/search/app.js": """(()=>{const q=document.querySelector('#search'),out=document.querySelector('#results'),status=document.querySelector('#status'),esc=s=>String(s).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c])),hi=(s,k)=>{const i=s.toLocaleLowerCase().indexOf(k);return i<0?esc(s):esc(s.slice(0,i))+'<mark>'+esc(s.slice(i,i+k.length))+'</mark>'+esc(s.slice(i+k.length))};let pages=[];const run=()=>{const raw=q.value.trim(),k=raw.toLocaleLowerCase();out.innerHTML='';if(!k){status.textContent=`已载入 ${pages.length} 个页面。`;return}const hits=pages.map(x=>{const t=x.title.toLocaleLowerCase(),p=x.plain_text.toLocaleLowerCase(),ti=t.indexOf(k),pi=p.indexOf(k);return{x,score:ti>=0?0:1,pos:pi}}).filter(v=>v.score===0||v.pos>=0).sort((a,b)=>a.score-b.score||a.x.title.localeCompare(b.x.title));status.textContent=`找到 ${hits.length} 个页面。`;const groups=new Map;hits.forEach(v=>{if(!groups.has(v.x.system_id))groups.set(v.x.system_id,[]);groups.get(v.x.system_id).push(v)});groups.forEach((items,id)=>{const section=document.createElement('section');section.className='group';section.innerHTML=`<h2>${esc(id)} (${items.length})</h2>`;items.forEach(({x,pos})=>{const start=Math.max(0,(pos<0?0:pos)-60),d=document.createElement('div');d.className='result';d.innerHTML=`<a href=\"${encodeURI('../../'+x.route)}?local_search=${encodeURIComponent(raw)}\"><strong>${hi(x.title,k)}</strong></a><p>${hi(x.plain_text.slice(start,start+140),k)}</p>`;section.append(d)});out.append(section)})};fetch('../../search-index.json').then(r=>r.json()).then(v=>{pages=v.pages||v;const initial=new URLSearchParams(location.search).get('q')||'';q.value=initial;run()}).catch(e=>status.textContent=`索引加载失败：${e}`);q.addEventListener('input',run)})();""",
        "_local/mirror.js": """(()=>{const term=new URLSearchParams(location.search).get('local_search');if(!term)return;const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT,{acceptNode:n=>n.parentElement&& !/^(SCRIPT|STYLE|MARK)$/.test(n.parentElement.tagName)&&n.data.toLocaleLowerCase().includes(term.toLocaleLowerCase())?NodeFilter.FILTER_ACCEPT:NodeFilter.FILTER_REJECT});const node=walker.nextNode();if(!node)return;const i=node.data.toLocaleLowerCase().indexOf(term.toLocaleLowerCase()),mark=document.createElement('mark');mark.textContent=node.data.slice(i,i+term.length);node.parentNode.insertBefore(document.createTextNode(node.data.slice(0,i)),node);node.parentNode.insertBefore(mark,node);node.data=node.data.slice(i+term.length);mark.scrollIntoView({block:'center'})})();""",
    }


def inject_local_tools(document, web_prefix):
    script = f'<script defer src="{web_prefix}_local/mirror.js"></script>'
    if re.search(r"</head\s*>", document, re.I): document = re.sub(r"</head\s*>", script + "</head>", document, count=1, flags=re.I)
    else: document = script + document
    button = f'<a href="{web_prefix}_local/search/" style="position:fixed;right:12px;bottom:12px;z-index:2147483647;padding:8px 12px;background:#111827;color:white;border-radius:6px;text-decoration:none;font:14px sans-serif">🔍 Local Search</a>'
    if re.search(r"</body\s*>", document, re.I): return re.sub(r"</body\s*>", button + "</body>", document, count=1, flags=re.I)
    return document + button


def rewrite_i18n_runtime_paths(script, web_prefix):
    return re.sub(r"(?P<quote>['\"`])/i18n/", lambda match: match.group("quote") + web_prefix + "i18n/", script)


def copy_i18n_files(i18n_root, output):
    if i18n_root is None or not i18n_root.is_dir(): return 0
    copied = 0
    for source in i18n_root.rglob("*.json"):
        target = output / source.relative_to(i18n_root)
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target); copied += 1
    return copied


def build(season, raw_root, asset_manifest_path, asset_root, output, system_id=None, force=False,
          catalog_path=None, search_index_path=None, system_manifest_path=None,
          supplemental_manifest_path=None, i18n_root=None):
    started = time.monotonic(); warnings = []; errors = []
    catalog_path = catalog_path or output.parent / "catalog.json"
    search_index_path = search_index_path or output.parent / "search-index.json"
    catalog = load_json(catalog_path); old_search = load_json(search_index_path)
    known_missing = []
    if system_manifest_path is not None:
        catalog_pages, systems_included, known_missing = pages_from_system_manifest(
            system_manifest_path, system_id
        )
        supplemental_pages = pages_from_supplemental_manifest(supplemental_manifest_path, system_id)
        catalog_pages.extend(supplemental_pages)
    else:
        catalog_pages = [p for p in catalog.get("pages", []) if not system_id or p["system_id"] == system_id]
        systems_included = sorted({page["system_id"] for page in catalog_pages})
    search_by_key = {(p["system_id"], p["id"]): p for p in old_search.get("pages", [])}
    asset_manifest = load_json(asset_manifest_path); assets = asset_manifest.get("assets", [])
    asset_map = {item["source_url"]: item for item in assets}
    web_prefix = f"/local_wiki/{season}/site/"
    if force and output.exists(): shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    print("=" * 60); print("TLIDB Full Mirror Build"); print(f"Season: {season}"); print(f"Pages: {len(catalog_pages)}"); print(f"Assets: {len(assets)}"); print("=" * 60)
    assets_copied = 0; assets_missing = []; css_rewrites = 0; css_unresolved = Counter(); runtime_examples = []; runtime_asset_count = 0
    resolution_totals = Counter()
    for item in assets:
        source = asset_root / item["local_relative_path"]; target = output / "assets" / item["local_relative_path"]
        if not source.is_file(): assets_missing.append(item["source_url"]); continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if item.get("asset_type") == "stylesheet":
            text = source.read_text(encoding="utf-8", errors="replace"); css = CSSRewriter(asset_map, web_prefix)
            target.write_text(css.rewrite(text, item["source_url"], "assets/" + item["local_relative_path"]), encoding="utf-8")
            css_rewrites += css.rewrites; css_unresolved.update(css.unresolved); resolution_totals.update(css.stats)
        else:
            if item.get("asset_type") == "javascript":
                script = source.read_text(encoding="utf-8", errors="replace"); runtime_asset_count += len(RUNTIME.findall(script))
                for value in runtime_urls(script):
                    if len(runtime_examples) >= 20: break
                    if value: runtime_examples.append({"asset": item["source_url"], "reference": value})
                target.write_text(rewrite_i18n_runtime_paths(script, web_prefix), encoding="utf-8")
            else: shutil.copy2(source, target)
        assets_copied += 1
    i18n_files_copied = copy_i18n_files(i18n_root, output)
    print(f"[Assets] {assets_copied}/{len(assets)}")
    candidates = []; routes = defaultdict(list); known_missing_raw_pages = []; available_keys = set()
    for page in catalog_pages:
        source_url = page.get("source_url") or f"https://tlidb.com/cn/{page.get('slug') or page['id']}"
        slug = page.get("slug") or page.get("id"); raw_path = raw_root / page["system_id"] / "raw_html" / f"{quote(slug, safe='-_.')}.html"
        source_key = canonical_page_key(source_url)
        if not raw_path.is_file():
            if source_key in available_keys:
                continue
            known_missing_raw_pages.append({
                "system_id": page["system_id"], "id": page.get("id"),
                "reason": "manifest_entry_without_raw_snapshot",
            })
            continue
        available_keys.add(source_key)
        try:
            route = (supplemental_route_for_source(source_url)
                     if page.get("source_type") == "recovered_internal" else route_for_source(source_url))
        except ValueError as exc: errors.append(str(exc)); continue
        record = dict(page, source_url=source_url, route=route, raw_path=raw_path)
        candidates.append(record); routes[canonical_page_key(source_url)].append(record)
    route_map = {key: matches[0]["route"] for key, matches in routes.items()}
    duplicate_conflicts = []; canonical_pages = []
    for key, matches in routes.items():
        canonical_pages.append(matches[0])
        if len(matches) > 1:
            hashes = {hashlib.sha256(p["raw_path"].read_bytes()).hexdigest() for p in matches}
            if len(hashes) > 1:
                duplicate_conflicts.append({"route": matches[0]["route"], "sources": [f"{p['system_id']}/{p.get('slug') or p['id']}" for p in matches]})
    totals = Counter({"runtime_http_reference_count": runtime_asset_count}); pages_failed = 0; unresolved_examples = set(); search_pages = []; by_system = defaultdict(list)
    for page in canonical_pages: by_system[page["system_id"]].append(page)
    overall = 0
    for sid in sorted(by_system):
        completed = 0
        for page in by_system[sid]:
            try:
                raw = page["raw_path"].read_text(encoding="utf-8"); inspector = TextInspector(); inspector.feed(raw)
                css = CSSRewriter(asset_map, web_prefix); rewriter = HTMLRewriter(page["source_url"], route_map, asset_map, web_prefix, css); rewriter.feed(raw); rewriter.close()
                rendered = inject_local_tools("".join(rewriter.output), web_prefix)
                target = output_path_for_route(output, page["route"])
                target.parent.mkdir(parents=True, exist_ok=True); target.write_text(rendered, encoding="utf-8")
                totals.update(rewriter.stats); totals["inline_css_rewrites"] += css.rewrites
                resolution_totals.update(css.stats)
                for host, count in css.unresolved.items(): totals[f"remote_domain:{host}"] += count
                unresolved_examples.update(rewriter.unresolved_internal); runtime_examples.extend(rewriter.runtime_examples[:20-len(runtime_examples)])
                old = search_by_key.get((page["system_id"], page["id"]), {})
                title = old.get("title") or " ".join(inspector.title.split()) or page.get("title") or page["id"]
                plain = old.get("plain_text") or " ".join(" ".join(inspector.text).split())
                search_pages.append({"system_id": page["system_id"], "id": page["id"], "title": title,
                                     "source_type": page.get("source_type", "official_system"),
                                     "source_url": page["source_url"], "route": page["route"].removesuffix("index.html"), "plain_text": plain})
                totals["routes_generated"] += 1
                lower = raw.lower()
                totals["tooltip_pages"] += int("data-bs-title" in lower or 'data-bs-toggle="tooltip"' in lower or " title=" in lower)
                totals["collapse_pages"] += int('data-bs-toggle="collapse"' in lower)
                totals["tab_pages"] += int('data-bs-toggle="tab"' in lower)
                totals["dropdown_pages"] += int('data-bs-toggle="dropdown"' in lower)
                totals["datatable_pages"] += int(bool(re.search(r'class=["\'][^"\']*datatable', lower)))
            except Exception as exc:
                pages_failed += 1; errors.append(f"Failed {page['system_id']}/{page.get('slug') or page['id']}: {exc}")
            completed += 1; overall += 1
        print(f"[{sid}] {completed}/{len(by_system[sid])}")
    print(f"Overall pages: {overall}/{len(canonical_pages)}")
    for name, content in local_assets().items():
        target = output / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(content, encoding="utf-8")
    index_target = output / "cn/index.html"; index_target.parent.mkdir(parents=True, exist_ok=True)
    first_route = canonical_pages[0]["route"].removesuffix("index.html") if canonical_pages else "../_local/search/"
    index_target.write_text(f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=/{web_prefix.strip("/")}/{first_route}"><a href="{web_prefix}_local/search/">Local Search</a>', encoding="utf-8")
    output.joinpath("catalog.json").write_text(json.dumps({"season": season, "page_count": len(search_pages), "pages": [{k:p[k] for k in ("system_id","source_type","id","title","source_url","route")} for p in search_pages]}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    output.joinpath("search-index.json").write_text(json.dumps({"season": season, "page_count": len(search_pages), "pages": search_pages}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    remaining_domains = Counter(css_unresolved)
    for key, value in totals.items():
        if key.startswith("remote_domain:"): remaining_domains[key.split(":",1)[1]] += value
    if remaining_domains:
        warnings.append(f"{sum(remaining_domains.values())} remote static asset references could not be mapped through the Asset Manifest.")
    if totals["runtime_http_reference_count"]:
        warnings.append(f"{totals['runtime_http_reference_count']} retained runtime HTTP patterns require local offline review; no responses were simulated.")
    report = {"season": season, "system_count": len(systems_included),
              "systems_included": systems_included, "inventory_included": "inventory" in systems_included,
              "supplemental_pages_included": sum(page["source_type"] == "recovered_internal" for page in search_pages),
              "recovered_pages_included": sum(page["source_type"] == "recovered_internal" for page in search_pages),
              "known_missing_pages": len(known_missing), "known_missing_entries": known_missing,
              "known_missing_detail_pages": known_missing,
              "known_missing_raw_pages": known_missing_raw_pages,
              "raw_pages_missing_count": len(known_missing_raw_pages),
              "raw_pages": len(catalog_pages), "routes_generated": totals["routes_generated"], "pages_failed": pages_failed,
              "assets_expected": len(assets), "assets_copied": assets_copied, "assets_missing": len(assets_missing), "assets_missing_examples": assets_missing[:20],
              "i18n_files_copied": i18n_files_copied,
              "html_asset_rewrites": totals["html_asset_rewrites"], "css_asset_rewrites": css_rewrites,
              "inline_css_rewrites": totals["inline_css_rewrites"], "internal_page_links_rewritten": totals["internal_page_links_rewritten"],
              "internal_page_links_unresolved": totals["internal_page_links_unresolved"], "unresolved_internal_examples": sorted(unresolved_examples)[:20],
              "search_forms_rewritten": totals["search_forms_rewritten"], "duplicate_route_conflicts": duplicate_conflicts,
              "tooltip_pages": totals["tooltip_pages"], "collapse_pages": totals["collapse_pages"], "tab_pages": totals["tab_pages"],
              "dropdown_pages": totals["dropdown_pages"], "datatable_pages": totals["datatable_pages"],
              "runtime_http_reference_count": totals["runtime_http_reference_count"], "runtime_http_examples": runtime_examples,
              "tracking_elements_removed": totals["tracking_elements_removed"],
              "relative_url_resolutions": totals["relative_url_resolutions"] + resolution_totals["relative_url_resolutions"],
              "wrong_directory_join_prevented": totals["wrong_directory_join_prevented"] + resolution_totals["wrong_directory_join_prevented"],
              "remaining_remote_asset_references": sum(remaining_domains.values()), "remaining_remote_domains": dict(remaining_domains),
              "elapsed": round(time.monotonic()-started,3), "warnings": warnings, "errors": errors}
    if duplicate_conflicts: report["warnings"].append(f"{len(duplicate_conflicts)} duplicate canonical routes had differing Raw HTML; first source order retained.")
    output.joinpath("mirror-build-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"Finished: Pages: {report['routes_generated']} Failed: {pages_failed} Assets: {assets_copied} Elapsed: {report['elapsed']}s")
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Build the offline TLIDB SS13 Full Mirror from Raw HTML and Raw Assets")
    parser.add_argument("--season", default="ss13"); parser.add_argument("--raw-root", type=Path, default=Path("data/raw/manifests"))
    parser.add_argument("--asset-manifest", type=Path, default=Path("data/raw/assets/ss13/asset-manifest.json"))
    parser.add_argument("--asset-root", type=Path, default=Path("data/raw/assets/ss13/files")); parser.add_argument("--output", type=Path, default=Path("local_wiki/ss13/site"))
    parser.add_argument("--system-manifest", type=Path, default=Path("sources/system_manifest.json"))
    parser.add_argument("--supplemental-manifest", type=Path,
                        default=Path("sources/recovered_internal_pages_manifest.json"))
    parser.add_argument("--i18n-root", type=Path, default=Path("data/raw/i18n/ss13/files"))
    parser.add_argument("--system-id"); parser.add_argument("--force", action="store_true"); return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        report = build(args.season, resolve(args.raw_root), resolve(args.asset_manifest), resolve(args.asset_root), resolve(args.output), args.system_id, args.force,
                       system_manifest_path=resolve(args.system_manifest),
                       supplemental_manifest_path=resolve(args.supplemental_manifest),
                       i18n_root=resolve(args.i18n_root))
        return 1 if report["errors"] else 0
    except Exception as exc:
        print(f"Full Mirror build failed: {exc}", file=sys.stderr); return 1


if __name__ == "__main__": raise SystemExit(main())
