from __future__ import annotations

import argparse
import html
import json
import os
import posixpath
import re
import shutil
import sys
import time
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]


class PageInspector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored = 0
        self.text = []
        self.headings = []
        self.heading = None
        self.heading_parts = []
        self.images = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style", "nav", "footer"}:
            self.ignored += 1
        if self.ignored:
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.heading = tag
            self.heading_parts = []
        if tag == "img":
            self.images.append(attrs.get("src", ""))

    def handle_endtag(self, tag):
        if tag in {"script", "style", "nav", "footer"} and self.ignored:
            self.ignored -= 1
            return
        if not self.ignored and self.heading == tag:
            value = normalize(" ".join(self.heading_parts))
            if value:
                self.headings.append(value)
            self.heading = None
            self.heading_parts = []

    def handle_data(self, data):
        if self.ignored:
            return
        self.text.append(data)
        if self.heading:
            self.heading_parts.append(data)


class LinkRewriter(HTMLParser):
    HREF = re.compile(r"(\bhref\s*=\s*)(['\"])(.*?)\2", re.I | re.S)

    def __init__(self, current_path, slug_index):
        super().__init__(convert_charrefs=False)
        self.current_path = current_path
        self.slug_index = slug_index
        self.output = []
        self.skip_script = 0
        self.rewritten = 0
        self.unresolved = 0
        self.warnings = []
        self.unresolved_slugs = set()
        self.ambiguous_slugs = set()

    def rewrite_href(self, match):
        href = html.unescape(match.group(3))
        parsed = urlparse(href)
        obvious_internal = parsed.netloc.lower() in {"tlidb.com", "www.tlidb.com"} or parsed.path.startswith("/cn/")
        slug = None
        if parsed.netloc.lower() in {"tlidb.com", "www.tlidb.com"} or parsed.path.startswith("/cn/"):
            parts = [unquote(part) for part in parsed.path.split("/") if part]
            if len(parts) == 2 and parts[0] == "cn":
                slug = parts[1]
        elif not parsed.scheme and not parsed.netloc and "/" not in parsed.path.strip("/"):
            slug = unquote(parsed.path.strip("/")) or None
        matches = self.slug_index.get(slug, []) if slug else []
        if len(matches) == 1:
            target = matches[0]["local_path"]
            relative = posixpath.relpath(target, posixpath.dirname(self.current_path))
            relative = quote(relative, safe="/-_.")
            if parsed.fragment:
                relative += "#" + parsed.fragment
            self.rewritten += 1
            return match.group(1) + match.group(2) + relative + match.group(2)
        if len(matches) > 1:
            self.ambiguous_slugs.add(slug)
        elif obvious_internal and slug:
            self.unresolved += 1
            self.unresolved_slugs.add(slug)
        return match.group(0)

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.skip_script += 1
            return
        if self.skip_script:
            return
        raw = self.get_starttag_text()
        self.output.append(self.HREF.sub(self.rewrite_href, raw) if tag == "a" else raw)

    def handle_startendtag(self, tag, attrs):
        if not self.skip_script:
            raw = self.get_starttag_text()
            self.output.append(self.HREF.sub(self.rewrite_href, raw) if tag == "a" else raw)

    def handle_endtag(self, tag):
        if tag == "script" and self.skip_script:
            self.skip_script -= 1
            return
        if not self.skip_script:
            self.output.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip_script:
            self.output.append(data)

    def handle_entityref(self, name):
        if not self.skip_script:
            self.output.append(f"&{name};")

    def handle_charref(self, name):
        if not self.skip_script:
            self.output.append(f"&#{name};")

    def handle_comment(self, data):
        if not self.skip_script:
            self.output.append(f"<!--{data}-->")

    def handle_decl(self, decl):
        if not self.skip_script:
            self.output.append(f"<!{decl}>")


def normalize(value):
    return " ".join(value.split())


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(path):
    return path if path.is_absolute() else ROOT / path


def selected_systems(system_manifest, system_id=None):
    systems = [item for item in system_manifest.get("systems", []) if item.get("discovery_status") == "confirmed"]
    if system_id:
        systems = [item for item in systems if item.get("system_id") == system_id]
        if len(systems) != 1:
            raise ValueError(f"unknown confirmed system_id: {system_id}")
    return systems


def collect_pages(systems, raw_root, warnings, errors):
    pages = []
    seen = set()
    for system in systems:
        system_id = system["system_id"]
        manifest_path = resolve(Path(system.get("manifest_path") or f"sources/{system_id}_manifest.json"))
        try:
            entries = load_json(manifest_path).get("entries", [])
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"Unable to load {system_id} manifest: {exc}")
            continue
        for entry in entries:
            slug = entry.get("slug") or entry.get("id")
            key = (system_id, slug)
            if not slug or key in seen:
                warnings.append(f"Duplicate or missing page in {system_id}: {slug!r}")
                continue
            seen.add(key)
            filename = quote(slug, safe="-_.")
            raw_path = raw_root / system_id / "raw_html" / f"{filename}.html"
            if not raw_path.is_file():
                warnings.append(f"Missing raw page: {system_id}/{slug}.html")
                continue
            pages.append({
                "system_id": system_id, "id": entry.get("id") or slug, "slug": slug,
                "title": entry.get("name_zh") or slug, "source_url": entry.get("url"),
                "local_path": f"pages/{system_id}/{filename}.html", "raw_path": raw_path,
            })
    return pages


def inject_local_shell(document, season, page):
    header = (
        '<div class="local-wiki-header"><a href="../../../app/">← Search</a>'
        f'<span>Season: {html.escape(season.upper())}</span>'
        f'<span>System: {html.escape(page["system_id"])}</span>'
        f'<a href="{html.escape(page["source_url"] or "#", quote=True)}" target="_blank" rel="noopener">Source: TLIDB</a></div>'
    )
    assets = '<link rel="stylesheet" href="../../../app/styles.css"><script defer src="../../../app/app.js"></script>'
    if re.search(r"<body\b[^>]*>", document, re.I):
        document = re.sub(r"(<body\b[^>]*>)", r"\1" + header, document, count=1, flags=re.I)
    else:
        document = header + document
    if re.search(r"</head>", document, re.I):
        document = re.sub(r"</head>", assets + "</head>", document, count=1, flags=re.I)
    else:
        document = assets + document
    return document


def app_assets():
    return {
        "index.html": """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Torchlight Local Wiki</title><link rel="stylesheet" href="styles.css"><script defer src="app.js"></script></head><body><main class="wiki-app"><h1>Torchlight Local Wiki</h1><p>Season: SS13</p><input id="search" type="search" placeholder="搜索全部本地页面" autocomplete="off"><p id="status">输入至少 1 个字符开始搜索。</p><div id="results"></div></main></body></html>""",
        "styles.css": """body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#20242a;background:#f5f6f8}.wiki-app{max-width:1000px;margin:auto;padding:24px}#search{width:100%;font-size:18px;padding:12px}.result{background:#fff;margin:10px 0;padding:12px;border-radius:6px}.result a{margin-right:12px}mark{background:#ffe58f}.local-wiki-header{position:relative;z-index:9999;display:flex;gap:18px;align-items:center;padding:9px 14px;background:#1f2937;color:#fff;font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.local-wiki-header a{color:#9dd6ff}.local-tooltip{position:fixed;z-index:10000;max-width:420px;padding:8px 10px;background:#111827;color:#fff;border-radius:4px;white-space:pre-wrap;pointer-events:none}h2{margin-top:28px}""",
        "app.js": """(()=>{const q=document.querySelector('#search'),out=document.querySelector('#results'),status=document.querySelector('#status');if(q){let index=[];fetch('../ss13/search-index.json').then(r=>r.json()).then(v=>{index=v.pages||v;status.textContent=`已载入 ${index.length} 个页面。`;}).catch(e=>status.textContent=`索引加载失败：${e}`);const esc=s=>s.replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));const hi=(s,k)=>{const i=s.toLocaleLowerCase().indexOf(k);return i<0?esc(s):esc(s.slice(0,i))+'<mark>'+esc(s.slice(i,i+k.length))+'</mark>'+esc(s.slice(i+k.length));};q.addEventListener('input',()=>{const raw=q.value.trim(),k=raw.toLocaleLowerCase();out.innerHTML='';if(!k){status.textContent='输入至少 1 个字符开始搜索。';return;}const hits=index.map(x=>{const t=x.title.toLocaleLowerCase(),p=x.plain_text.toLocaleLowerCase(),ti=t.indexOf(k),pi=p.indexOf(k);return {x,score:ti>=0?0:1,pos:pi};}).filter(v=>v.score===0||v.pos>=0).sort((a,b)=>a.score-b.score||a.x.title.localeCompare(b.x.title));status.textContent=`找到 ${hits.length} 个页面。`;const groups=new Map();hits.forEach(v=>{if(!groups.has(v.x.system_id))groups.set(v.x.system_id,[]);groups.get(v.x.system_id).push(v);});groups.forEach((items,id)=>{const h=document.createElement('h2');h.textContent=`${id} (${items.length})`;out.append(h);items.forEach(({x,pos})=>{const d=document.createElement('div');d.className='result';const start=Math.max(0,(pos<0?0:pos)-60),context=x.plain_text.slice(start,start+140);d.innerHTML=`<strong>${hi(x.title,k)}</strong><p>${hi(context,k)}</p><a href="../ss13/${encodeURI(x.local_path)}">本地打开</a><a href="${esc(x.source_url)}" target="_blank" rel="noopener">TLIDB Source</a>`;out.append(d);});});});}let tip;const hide=()=>{if(tip){tip.remove();tip=null;}};document.querySelectorAll('[data-bs-toggle="tooltip"],[data-bs-title],[title]').forEach(el=>{const show=()=>{const raw=el.getAttribute('data-bs-title')||el.getAttribute('title');if(!raw)return;const box=document.createElement('div');box.innerHTML=raw;tip=document.createElement('div');tip.className='local-tooltip';tip.textContent=box.textContent;document.body.append(tip);const r=el.getBoundingClientRect();tip.style.left=Math.max(8,Math.min(r.left,innerWidth-tip.offsetWidth-8))+'px';tip.style.top=Math.max(8,r.bottom+6)+'px';};el.addEventListener('mouseenter',show);el.addEventListener('mouseleave',hide);el.addEventListener('focus',show);el.addEventListener('blur',hide);});})();""",
    }


def build(season, system_manifest_path, raw_root, output, system_id=None, force=False):
    started = time.monotonic()
    warnings, errors = [], []
    systems = selected_systems(load_json(system_manifest_path), system_id)
    pages = collect_pages(systems, raw_root, warnings, errors)
    if force and output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    app_dir = output.parent / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    for name, content in app_assets().items():
        (app_dir / name).write_text(content, encoding="utf-8")
    slug_index = defaultdict(list)
    for page in pages:
        slug_index[page["slug"]].append(page)
    duplicate_conflicts = sum(1 for matches in slug_index.values() if len(matches) > 1)
    ambiguous_slugs, unresolved_slugs = set(), set()
    catalog_pages, search_pages = [], []
    stats = {"generated": 0, "failed": 0, "rewritten": 0, "unresolved": 0, "remote": 0, "local": 0}
    by_system = defaultdict(list)
    for page in pages:
        by_system[page["system_id"]].append(page)
    print("Local Wiki Build")
    print(f"- systems: {len(systems)}")
    print(f"- pages: {len(pages)}")
    overall = 0
    for system in systems:
        system_pages = by_system[system["system_id"]]
        completed = 0
        for page in system_pages:
            try:
                raw = page["raw_path"].read_text(encoding="utf-8")
                inspector = PageInspector(); inspector.feed(raw)
                rewriter = LinkRewriter(page["local_path"], slug_index); rewriter.feed(raw)
                rendered = inject_local_shell("".join(rewriter.output), season, page)
                target = output / page["local_path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(rendered, encoding="utf-8")
                public = {key: page[key] for key in ("system_id", "id", "slug", "title", "source_url", "local_path")}
                if inspector.headings:
                    public["title"] = inspector.headings[0]
                catalog_pages.append(public)
                search_pages.append({key: public[key] for key in ("system_id", "id", "title", "source_url", "local_path")} | {
                    "headings": inspector.headings, "plain_text": normalize(" ".join(inspector.text))})
                stats["rewritten"] += rewriter.rewritten; stats["unresolved"] += rewriter.unresolved
                ambiguous_slugs.update(rewriter.ambiguous_slugs)
                unresolved_slugs.update(rewriter.unresolved_slugs)
                stats["remote"] += sum(urlparse(src).scheme in {"http", "https"} or src.startswith("//") for src in inspector.images)
                stats["local"] += sum(bool(src) and not (urlparse(src).scheme in {"http", "https"} or src.startswith("//")) for src in inspector.images)
                stats["generated"] += 1
            except Exception as exc:
                stats["failed"] += 1
                errors.append(f"Failed {page['system_id']}/{page['slug']}: {exc}")
            completed += 1; overall += 1
        print(f"[{system['system_id']}] {completed}/{len(system_pages)} | Overall: {overall}/{len(pages)}", flush=True)
    for slug in sorted(ambiguous_slugs):
        warnings.append(f"Duplicate slug conflict preserved without rewrite: {slug!r}.")
    for slug in sorted(unresolved_slugs):
        warnings.append(f"Unresolved internal slug preserved: {slug!r}.")
    catalog = {"season": season, "page_count": len(catalog_pages), "systems": [s["system_id"] for s in systems], "pages": catalog_pages}
    search_index = {"season": season, "page_count": len(search_pages), "pages": search_pages}
    report = {
        "season": season, "systems_processed": len(systems), "raw_pages_found": len(pages),
        "pages_generated": stats["generated"], "pages_failed": stats["failed"],
        "search_index_pages": len(search_pages), "rewritten_internal_links": stats["rewritten"],
        "unresolved_internal_links": stats["unresolved"], "duplicate_slug_conflicts": duplicate_conflicts,
        "remote_image_count": stats["remote"], "local_image_count": stats["local"],
        "elapsed": round(time.monotonic() - started, 3), "warnings": warnings, "errors": errors,
    }
    for name, value in (("catalog.json", catalog), ("search-index.json", search_index), ("build-report.json", report)):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Build an offline local wiki from raw HTML snapshots")
    parser.add_argument("--season", default="ss13")
    parser.add_argument("--system-manifest", type=Path, default=Path("sources/system_manifest.json"))
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw/manifests"))
    parser.add_argument("--output", type=Path, default=Path("local_wiki/ss13"))
    parser.add_argument("--system-id")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        report = build(args.season, resolve(args.system_manifest), resolve(args.raw_root), resolve(args.output), args.system_id, args.force)
        print(f"Generated: {report['pages_generated']}; Failed: {report['pages_failed']}")
        return 1 if report["errors"] else 0
    except Exception as exc:
        print(f"Local Wiki build failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
