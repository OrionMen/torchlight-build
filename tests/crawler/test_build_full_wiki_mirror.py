import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from crawler.build_full_wiki_mirror import (
    CSSRewriter,
    HTMLRewriter,
    build,
    canonical_page_key,
    content_tree_fields_for_system,
    load_game_category_mapping,
    load_game_content_tree,
    load_entity_index,
    local_assets,
    output_path_for_route,
    route_for_source,
    resolve_content_tree_classification,
    supplemental_route_for_source,
    system_display_name,
    TextInspector,
)


class FullWikiMirrorBuilderTest(unittest.TestCase):
    @staticmethod
    def extracted_text(raw, visible_skill_content_only=False):
        inspector = TextInspector(visible_skill_content_only=visible_skill_content_only)
        inspector.feed(raw)
        return " ".join(" ".join(inspector.text).split())

    def test_skill_text_extraction_excludes_inactive_and_npc_tabs(self):
        raw = """<html><body><h1>幽刃英灵</h1><div class="tab-pane active"><span>攻击 物理 哨卫</span></div>
        <div id="幽刃英灵_NPC" class="tab-pane fade"><span>创伤 收割 时间</span></div></body></html>"""
        before = self.extracted_text(raw)
        after = self.extracted_text(raw, visible_skill_content_only=True)
        self.assertIn("收割", before)
        self.assertNotIn("收割", after)
        for kept in ("幽刃英灵", "攻击", "物理", "哨卫"):
            self.assertIn(kept, after)

    def test_skill_text_extraction_keeps_active_tab_and_excludes_hidden_nodes(self):
        raw = """<div class="tab-pane show">技能详情</div><table class="DataTable"><tr><td>level damage 999</td></tr></table><div hidden>隐藏一</div>
        <div style="display: none">隐藏二</div><div aria-hidden="true">隐藏三</div>"""
        text = self.extracted_text(raw, visible_skill_content_only=True)
        self.assertIn("技能详情", text)
        self.assertNotIn("level damage", text)
        self.assertNotIn("隐藏一", text)
        self.assertNotIn("隐藏二", text)
        self.assertNotIn("隐藏三", text)

    def test_skill_text_extraction_excludes_alts_and_related_skill_cards(self):
        raw = """<main><h1>触媒：激活进发</h1><p>激活进发当前技能正文</p>
        <div class="card ui_item"><div class="card-header">Alts</div><div class="card-body">
        <li><a data-hover="/alt">触媒：预备</a></li><li><a data-hover="/alt2">触媒：永劫</a></li></div></div>
        <div class="card"><div class="card-header">关联技能</div><div>历史关联技能</div></div></main>"""
        text = self.extracted_text(raw, visible_skill_content_only=True)
        self.assertIn("触媒：激活进发", text)
        self.assertIn("激活进发当前技能正文", text)
        for removed in ("Alts", "触媒：预备", "触媒：永劫", "关联技能", "历史关联技能"):
            self.assertNotIn(removed, text)

    def test_skill_text_extraction_excludes_historical_season_card(self):
        raw = """<div class="card ui_item"><div class="item_ver">SS13赛季</div><p>当前技能正文</p></div>
        <div class="card ui_item previousItem"><div class="item_ver">SS12赛季</div><p>历史技能正文</p></div>"""
        text = self.extracted_text(raw, visible_skill_content_only=True)
        self.assertIn("SS13赛季", text)
        self.assertIn("当前技能正文", text)
        self.assertNotIn("SS12赛季", text)
        self.assertNotIn("历史技能正文", text)

    def test_ordinary_page_text_extraction_is_unchanged(self):
        raw = '<div class="tab-pane fade">普通页面历史内容</div><main>普通正文</main>'
        self.assertEqual(
            self.extracted_text(raw),
            "普通页面历史内容 普通正文",
        )

    def test_ghost_blade_skill_plain_text_excludes_reaping_keyword(self):
        raw_path = Path(__file__).resolve().parents[2] / "data/raw/manifests/active_skill/raw_html/Ghost_Blade_Einherjar.html"
        self.assertTrue(raw_path.is_file())
        raw = raw_path.read_text(encoding="utf-8")
        before = self.extracted_text(raw)
        after = self.extracted_text(raw, visible_skill_content_only=True)
        self.assertIn("收割", before)
        self.assertNotIn("收割", after)
        for kept in ("攻击", "物理", "哨卫"):
            self.assertIn(kept, after)

    def test_skill_build_replaces_cached_polluted_plain_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_root = root / "raw"
            page_dir = raw_root / "active_skill/raw_html"
            page_dir.mkdir(parents=True)
            page_dir.joinpath("Ghost_Blade_Einherjar.html").write_text(
                '<html><head><title>幽刃英灵</title></head><body>'
                '<div class="tab-pane active">攻击 物理 哨卫 投射物</div>'
                '<div id="幽刃英灵_NPC" class="tab-pane fade">创伤 收割 时间</div>'
                '</body></html>', encoding="utf-8",
            )
            asset_manifest = root / "asset-manifest.json"
            asset_manifest.write_text('{"assets": []}', encoding="utf-8")
            output = root / "local_wiki/ss13/site"
            output.parent.mkdir(parents=True)
            catalog_path = output.parent / "catalog.json"
            catalog_path.write_text(json.dumps({"pages": [{
                "system_id": "active_skill", "system_name_zh": "主动技能",
                "id": "Ghost_Blade_Einherjar", "slug": "Ghost_Blade_Einherjar",
                "title": "幽刃英灵", "source_url": "https://tlidb.com/cn/Ghost_Blade_Einherjar",
            }]}), encoding="utf-8")
            search_path = output.parent / "search-index.json"
            search_path.write_text(json.dumps({"pages": [{
                "system_id": "active_skill", "id": "Ghost_Blade_Einherjar",
                "title": "幽刃英灵", "plain_text": "旧缓存包含收割",
            }]}), encoding="utf-8")

            build("ss13", raw_root, asset_manifest, root / "assets", output,
                  catalog_path=catalog_path, search_index_path=search_path)

            index = json.loads(output.joinpath("search-index.json").read_text(encoding="utf-8"))
            plain_text = index["pages"][0]["plain_text"]
            self.assertNotIn("收割", plain_text)
            self.assertIn("攻击 物理 哨卫 投射物", plain_text)

    def test_inventory_equipment_search_uses_entity_clean_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_root = root / "raw"
            page_dir = raw_root / "inventory/raw_html"
            page_dir.mkdir(parents=True)
            page_dir.joinpath("STR_Helmet.html").write_text(
                '<html><head><title>STR_Helmet</title></head><body>'
                '<table><tr><td>Tier Weight Library 完整词缀表</td></tr></table>'
                '</body></html>', encoding="utf-8",
            )
            asset_manifest = root / "asset-manifest.json"
            asset_manifest.write_text('{"assets": []}', encoding="utf-8")
            output = root / "local_wiki/ss13/site"
            output.parent.mkdir(parents=True)
            catalog_path = output.parent / "catalog.json"
            catalog_path.write_text(json.dumps({"pages": [{
                "system_id": "inventory", "system_name_zh": "仓库",
                "id": "STR_Helmet", "slug": "STR_Helmet", "title": "STR_Helmet",
                "source_url": "https://tlidb.com/cn/STR_Helmet",
            }]}), encoding="utf-8")
            search_path = output.parent / "search-index.json"
            search_path.write_text(json.dumps({"pages": []}), encoding="utf-8")
            entity_path = root / "entity-index-v3.json"
            entity_path.write_text(json.dumps({"entities": [{
                "entity_id": "tlidb:cn:STR_Helmet", "canonical_route": "/cn/STR_Helmet/",
                "entity_title_zh": "力量头部", "entity_visibility": "visible",
                "entity_type": "equipment", "clean_summary": "力量头部 蛮兵护盔 +168 该装备护甲值",
                "sources": [{"source_type": "inventory", "role": "base_equipment"},
                            {"source_type": "craft", "role": "craft_affixes"}],
                "content_category_id": "equipment", "content_category_name_zh": "装备",
                "content_subcategory_id": "equipment_craft", "content_subcategory_name_zh": "打造装备",
            }]}), encoding="utf-8")

            build("ss13", raw_root, asset_manifest, root / "assets", output,
                  catalog_path=catalog_path, search_index_path=search_path,
                  entity_index_path=entity_path)

            page = json.loads(output.joinpath("search-index.json").read_text(encoding="utf-8"))["pages"][0]
            self.assertEqual("力量头部 蛮兵护盔 +168 该装备护甲值", page["plain_text"])
            self.assertEqual("equipment", page["entity_type"])
            self.assertEqual("craft_affixes", page["entity_sources"][1]["role"])
            self.assertNotRegex(page["plain_text"], r"Tier|Weight|Library|完整词缀表")

    def test_memory_system_search_uses_entity_clean_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_root = root / "raw"
            page_dir = raw_root / "inventory/raw_html"
            page_dir.mkdir(parents=True)
            page_dir.joinpath("Hero_Memories.html").write_text(
                '<html><head><title>Hero Memories</title></head><body>'
                '<nav>仓库 Item 材料</nav><div>页面原始正文不含目标复苏词条</div>'
                '</body></html>', encoding="utf-8",
            )
            asset_manifest = root / "asset-manifest.json"
            asset_manifest.write_text('{"assets": []}', encoding="utf-8")
            output = root / "local_wiki/ss13/site"
            output.parent.mkdir(parents=True)
            catalog_path = output.parent / "catalog.json"
            catalog_path.write_text(json.dumps({"pages": [{
                "system_id": "inventory", "system_name_zh": "仓库",
                "id": "Hero_Memories", "slug": "Hero_Memories",
                "title": "Hero Memories",
                "source_url": "https://tlidb.com/cn/Hero_Memories",
            }]}), encoding="utf-8")
            search_path = output.parent / "search-index.json"
            search_path.write_text(json.dumps({"pages": [{
                "system_id": "inventory", "id": "Hero_Memories",
                "title": "旧追忆", "plain_text": "旧缓存没有复苏词缀",
            }]}), encoding="utf-8")
            entity_path = root / "entity-index-v3.json"
            clean_summary = (
                "英雄追忆 基础属性 固有词缀 随机词缀 "
                "普通复苏词缀 +100 全属性 复苏词缀（月相） 英雄的多谋"
            )
            entity_path.write_text(json.dumps({"entities": [{
                "entity_id": "tlidb:cn:Hero_Memories",
                "canonical_route": "/cn/Hero_Memories/",
                "entity_title_zh": "英雄追忆", "entity_visibility": "visible",
                "entity_type": "memory_system", "clean_summary": clean_summary,
                "sources": [
                    {"source_type": "hero_memory", "role": "base_memory_affixes"},
                    {"source_type": "revival", "role": "revival_affixes"},
                ],
                "content_category_id": "memory", "content_category_name_zh": "追忆",
                "content_subcategory_id": "hero_memory",
                "content_subcategory_name_zh": "英雄追忆",
            }]}), encoding="utf-8")

            build("ss13", raw_root, asset_manifest, root / "assets", output,
                  catalog_path=catalog_path, search_index_path=search_path,
                  entity_index_path=entity_path)

            page = json.loads(
                output.joinpath("search-index.json").read_text(encoding="utf-8")
            )["pages"][0]
            self.assertEqual(clean_summary, page["plain_text"])
            self.assertIn("普通复苏词缀", page["plain_text"])
            self.assertIn("复苏词缀（月相）", page["plain_text"])
            self.assertIn("全属性", page["plain_text"])
            self.assertEqual("memory", page["content_category_id"])
            self.assertEqual("hero_memory", page["content_subcategory_id"])
            self.assertNotIn("页面原始正文", page["plain_text"])
            self.assertNotIn("旧缓存", page["plain_text"])

    def test_vorax_entity_search_uses_canonical_route_without_fragment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_root = root / "raw"
            page_dir = raw_root / "inventory/raw_html"
            page_dir.mkdir(parents=True)
            pages = (
                ("Vorax_Limb:_Head", "渴瘾肢体：脑部"),
                ("Vorax_Limb:_Legs", "渴瘾肢体：腿部"),
            )
            for slug, title in pages:
                page_dir.joinpath(f"{slug.replace(':', '%3A')}.html").write_text(
                    f'<button data-bs-toggle="tab" data-bs-target="#{title}">{title}</button>'
                    f'<div id="{title}" class="tab-pane"><h1>{title}</h1></div>',
                    encoding="utf-8",
                )
            asset_manifest = root / "asset-manifest.json"
            asset_manifest.write_text('{"assets": []}', encoding="utf-8")
            output = root / "site"
            catalog_path = root / "catalog.json"
            catalog_path.write_text(json.dumps({"pages": [{
                "system_id": "inventory", "system_name_zh": "仓库",
                "id": slug, "slug": slug, "title": title,
                "source_url": f"https://tlidb.com/cn/{slug}",
            } for slug, title in pages]}), encoding="utf-8")
            search_path = root / "search-index.json"
            search_path.write_text('{"pages": []}', encoding="utf-8")
            entity_path = root / "entities.json"
            entity_path.write_text(json.dumps({"entities": [{
                "entity_id": f"tlidb:cn:{slug}", "canonical_route": f"/cn/{slug}/",
                "entity_title_zh": title, "entity_visibility": "visible",
                "entity_type": "equipment",
                "clean_summary": f"{title} 打造词条 战意 传奇品质",
                "content_category_id": "equipment", "content_category_name_zh": "装备",
                "content_subcategory_id": "equipment_vorax",
                "content_subcategory_name_zh": "渴瘾装备",
            } for slug, title in pages]}), encoding="utf-8")

            build("ss13", raw_root, asset_manifest, root / "assets", output,
                  catalog_path=catalog_path, search_index_path=search_path,
                  entity_index_path=entity_path)

            index = json.loads(output.joinpath("search-index.json").read_text(encoding="utf-8"))
            by_id = {page["id"]: page for page in index["pages"]}
            for slug, title in pages:
                page = by_id[slug]
                self.assertNotIn("landing_anchor", page)
                self.assertEqual(f"cn/{slug}/", page["route"])
                self.assertEqual("equipment", page["content_category_id"])
                self.assertEqual("equipment_vorax", page["content_subcategory_id"])
                self.assertIn("战意", page["plain_text"])
                self.assertIn(title, page["plain_text"])
            search_js = output.joinpath("_local/search/app.js").read_text(encoding="utf-8")
            mirror_js = output.joinpath("_local/mirror.js").read_text(encoding="utf-8")
            self.assertNotIn("landing_anchor", search_js)
            self.assertIn("?local_search=", search_js)
            self.assertNotIn("location.hash", mirror_js)
            self.assertNotIn("bootstrap.Tab", mirror_js)

    def test_search_result_url_has_no_fragment_logic(self):
        search_js = local_assets()["_local/search/app.js"]
        self.assertNotIn("landing_anchor", search_js)
        self.assertIn("const resultHref=(x,raw)=>encodeURI('../../'+x.route)+'?local_search='+encodeURIComponent(raw);", search_js)

    def test_encoded_source_route_uses_http_server_compatible_path(self):
        self.assertEqual(route_for_source("https://tlidb.com/cn/Activation_Medium%3A_Boss"),
                         "cn/Activation_Medium:_Boss/index.html")

    def test_inventory_relative_links_use_page_url_as_file_base(self):
        base = "https://tlidb.com/cn/Inventory"
        self.assertEqual(canonical_page_key("STR_Helmet", base), "https://tlidb.com/cn/STR_Helmet")
        self.assertEqual(canonical_page_key("Vorax_Limb:_Head", base),
                         "https://tlidb.com/cn/Vorax_Limb:_Head")
        self.assertEqual(canonical_page_key("B", "https://tlidb.com/cn/A"), "https://tlidb.com/cn/B")
        self.assertEqual(canonical_page_key("https://tlidb.com/cn/B", base), "https://tlidb.com/cn/B")
        self.assertEqual(canonical_page_key("/cn/B", base), "https://tlidb.com/cn/B")
        self.assertEqual(canonical_page_key("B#x", base), "https://tlidb.com/cn/B")
        self.assertEqual(canonical_page_key("B?a=1", base), "https://tlidb.com/cn/B")
        self.assertIsNone(canonical_page_key("https://example.com/B", base))

        route_map = {
            "https://tlidb.com/cn/STR_Helmet": "cn/STR_Helmet/index.html",
            "https://tlidb.com/cn/Vorax_Limb:_Head": "cn/Vorax_Limb:_Head/index.html",
        }
        raw = '<a href="STR_Helmet">Helmet</a><a href="Vorax_Limb:_Head">Vorax</a><a href="https://example.com/B">External</a>'
        rewriter = HTMLRewriter(base, route_map, {}, "/local/", CSSRewriter({}, "/local/"))
        rewriter.feed(raw); rewriter.close()
        rendered = "".join(rewriter.output)
        self.assertIn('href="/local/cn/STR_Helmet/"', rendered)
        self.assertIn('href="/local/cn/Vorax_Limb:_Head/"', rendered)
        self.assertNotIn("/cn/Inventory/STR_Helmet", rendered)
        self.assertIn('href="https://example.com/B"', rendered)
        self.assertEqual(raw, '<a href="STR_Helmet">Helmet</a><a href="Vorax_Limb:_Head">Vorax</a><a href="https://example.com/B">External</a>')
        self.assertEqual(rewriter.stats["relative_url_resolutions"], 2)
        self.assertEqual(rewriter.stats["wrong_directory_join_prevented"], 2)

    def test_catalog_miss_canonicalizes_relative_href_without_local_directory_fallback(self):
        cases = (
            ("https://tlidb.com/cn/Inventory", "Vorax_Limb:_Head",
             "https://tlidb.com/cn/Vorax_Limb:_Head", "/cn/Inventory/Vorax_Limb:_Head"),
            ("https://tlidb.com/cn/Nether_Kings_Broken_Divinity",
             "Nether_Kings_Broken_Divinity:_Contamination",
             "https://tlidb.com/cn/Nether_Kings_Broken_Divinity:_Contamination",
             "/cn/Nether_Kings_Broken_Divinity/Nether_Kings_Broken_Divinity:_Contamination"),
            ("https://tlidb.com/cn/Ethereal_Prism", "Ethereal_Prism:_Haze",
             "https://tlidb.com/cn/Ethereal_Prism:_Haze",
             "/cn/Ethereal_Prism/Ethereal_Prism:_Haze"),
        )
        for base, href, expected, forbidden in cases:
            raw = f'<a href="{href}">Target</a>'
            rewriter = HTMLRewriter(base, {}, {}, "/local/", CSSRewriter({}, "/local/"))
            rewriter.feed(raw); rewriter.close()
            rendered = "".join(rewriter.output)
            self.assertIn(f'href="{expected}"', rendered)
            self.assertNotIn(forbidden, rendered)
            self.assertEqual(raw, f'<a href="{href}">Target</a>')
            self.assertEqual(rewriter.stats["relative_catalog_miss_canonicalized"], 1)

    def test_catalog_miss_preserves_root_relative_and_absolute_links(self):
        raw = '<a href="/cn/Root">Root</a><a href="https://tlidb.com/cn/Absolute">Absolute</a>'
        rewriter = HTMLRewriter("https://tlidb.com/cn/Inventory", {}, {}, "/local/", CSSRewriter({}, "/local/"))
        rewriter.feed(raw); rewriter.close()
        self.assertEqual("".join(rewriter.output), raw)

    def test_builds_full_document_rewrites_dependencies_and_preserves_raw(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); raw_root = root / "raw"; asset_root = root / "asset-files"
            page_dir = raw_root / "hero/raw_html"; other_dir = raw_root / "help/raw_html"; duplicate_dir = raw_root / "hyperlink/raw_html"
            page_dir.mkdir(parents=True); other_dir.mkdir(parents=True); duplicate_dir.mkdir(parents=True)
            raw_page = """<!DOCTYPE html><html id="root"><head>
<link rel="stylesheet" href="https://cdn.tlidb.com/css/site.css"><script src="https://cdn.tlidb.com/js/app.js"></script>
<script src="https://s.nitropay.com/ad.js"></script><style>.hero{background:url('https://cdn.tlidb.com/image/bg.png')}</style>
</head><body class="original" data-page="hero" style="background:url(https://cdn.tlidb.com/image/bg.png)">
<nav data-bs-toggle="dropdown"></nav><div data-bs-toggle="tooltip" data-bs-title="提示"></div>
<div data-bs-toggle="collapse"></div><div data-bs-toggle="tab"></div><table class="datatable"></table>
<img src="https://cdn.tlidb.com/image/a.png" srcset="https://cdn.tlidb.com/image/a.png 1x, https://cdn.tlidb.com/image/bg.png 2x">
<img src="https://cdn.tlidb.com/missing.png"><a id="relative" href="/cn/Other?q=1#part">Other</a>
<a id="absolute" href="https://tlidb.com/cn/Other?x=2#section">Absolute</a><a href="https://example.com/keep">External</a>
<form role="search" action="search"><input name="q"></form><script>fetch('/api/example')</script>
</body></html>"""
            page_path = page_dir / "Page.html"; page_path.write_text(raw_page, encoding="utf-8")
            other_dir.joinpath("Other.html").write_text("<!doctype html><html><body><h1>其它页面</h1></body></html>", encoding="utf-8")
            duplicate_dir.joinpath("PageCopy.html").write_text("<!doctype html><html><body>conflicting copy</body></html>", encoding="utf-8")
            raw_hash = hashlib.sha256(page_path.read_bytes()).hexdigest()

            asset_specs = [
                ("css", "https://cdn.tlidb.com/css/site.css", "stylesheet", "css/aa/site.css", "@import 'https://cdn.tlidb.com/css/theme.css';.x{background:url('../image/bg.png')}"),
                ("theme", "https://cdn.tlidb.com/css/theme.css", "stylesheet", "css/bb/theme.css", "body{}"),
                ("js", "https://cdn.tlidb.com/js/app.js", "javascript", "js/cc/app.js", "console.log('local')"),
                ("a", "https://cdn.tlidb.com/image/a.png", "image", "image/dd/a.png", "a"),
                ("bg", "https://cdn.tlidb.com/image/bg.png", "image", "image/ee/bg.png", "bg"),
            ]
            assets = []
            for asset_id, url, kind, relative, content in asset_specs:
                path = asset_root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content, encoding="utf-8")
                assets.append({"asset_id": asset_id, "source_url": url, "asset_type": kind, "local_relative_path": relative})
            manifest_path = root / "asset-manifest.json"
            manifest_path.write_text(json.dumps({"assets": assets}), encoding="utf-8")
            output = root / "local_wiki/ss13/site"; output.parent.mkdir(parents=True)
            catalog = {"pages": [
                {"system_id":"hero","system_name_zh":"主动技能","id":"Page","slug":"Page","title":"页面","source_url":"https://tlidb.com/cn/Page"},
                {"system_id":"help","id":"Other","slug":"Other","title":"其它","source_url":"https://tlidb.com/cn/Other"},
                {"system_id":"hyperlink","id":"PageCopy","slug":"PageCopy","title":"副本","source_url":"https://tlidb.com/cn/Page"},
            ]}
            search = {"pages": [
                {"system_id":"hero","id":"Page","title":"战意页面",
                 "plain_text":"A_Fervor_%28Noble%29 这里包含战意测试内容 Info id:7716 Show Description Tier name 2"},
                {"system_id":"help","id":"Other","title":"其它","plain_text":"其它内容"},
            ]}
            catalog_path = output.parent / "catalog.json"; search_path = output.parent / "search-index.json"
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8"); search_path.write_text(json.dumps(search), encoding="utf-8")

            report = build("ss13", raw_root, manifest_path, asset_root, output, force=True,
                           catalog_path=catalog_path, search_index_path=search_path,
                           game_category_mapping_path=Path(__file__).resolve().parents[2] / "config/game_category_mapping.json",
                           game_content_tree_path=Path(__file__).resolve().parents[2] / "config/game_content_tree.json")
            rendered = output.joinpath("cn/Page/index.html").read_text(encoding="utf-8")
            self.assertTrue(rendered.lower().startswith("<!doctype html>"))
            self.assertIn('<html id="root">', rendered)
            self.assertIn('class="original"', rendered)
            self.assertIn('data-page="hero"', rendered)
            self.assertIn('/local_wiki/ss13/site/assets/image/dd/a.png', rendered)
            self.assertIn('/local_wiki/ss13/site/assets/image/ee/bg.png 2x', rendered)
            self.assertIn('/local_wiki/ss13/site/assets/css/aa/site.css', rendered)
            self.assertIn('/local_wiki/ss13/site/assets/js/cc/app.js', rendered)
            self.assertIn('/local_wiki/ss13/site/cn/Other/?q=1#part', rendered)
            self.assertIn('/local_wiki/ss13/site/cn/Other/?x=2#section', rendered)
            self.assertIn('https://example.com/keep', rendered)
            self.assertNotIn('s.nitropay.com', rendered)
            self.assertIn('action="/local_wiki/ss13/site/_local/search/"', rendered)
            self.assertIn('name="q"', rendered)
            self.assertEqual(hashlib.sha256(page_path.read_bytes()).hexdigest(), raw_hash)
            css = output.joinpath("assets/css/aa/site.css").read_text(encoding="utf-8")
            self.assertIn("../bb/theme.css", css)
            self.assertIn("../../image/ee/bg.png", css)
            self.assertNotIn("cdn.tlidb.com", css)
            index = json.loads(output.joinpath("search-index.json").read_text(encoding="utf-8"))
            result = next(item for item in index["pages"] if item["title"] == "战意页面")
            self.assertEqual(result["route"], "cn/Page/")
            self.assertEqual(result["system_id"], "hero")
            self.assertEqual(result["system_name_zh"], "主动技能")
            self.assertEqual(result["game_category"], "hero")
            self.assertEqual(result["game_category_name_zh"], "英雄")
            self.assertEqual(result["game_category_visibility"], "primary")
            self.assertIn("Info id:7716", result["plain_text"])
            self.assertIn("战意测试内容", result["plain_text"])
            self.assertEqual(result["title_display"], "战意页面")
            self.assertIn("战意测试内容", result["summary_display"])
            self.assertNotIn("Info id", result["summary_display"])
            self.assertNotIn("Show Description", result["summary_display"])
            self.assertNotIn("Tier name", result["summary_display"])
            self.assertNotIn("%28", result["summary_display"])
            self.assertEqual(index["schema_version"], 8)
            self.assertTrue({"system_id", "system_name_zh", "title", "plain_text",
                             "title_display", "summary_display", "entity_id", "entity_title",
                             "entity_category", "entity_category_name_zh", "entity_confidence",
                             "entity_title_zh", "entity_visibility", "clean_summary",
                             "content_category_id", "content_category_name_zh",
                             "content_subcategory_id", "content_subcategory_name_zh"}.issubset(result))
            self.assertIsNone(result["entity_id"])
            self.assertEqual(result["content_category_id"], "hero")
            self.assertEqual(result["content_category_name_zh"], "英雄")
            self.assertEqual(result["content_subcategory_id"], "hero_trait")
            self.assertEqual(result["content_subcategory_name_zh"], "英雄特性")
            fallback = next(item for item in index["pages"] if item["system_id"] == "help")
            self.assertEqual(fallback["system_name_zh"], "help")
            search_js = output.joinpath("_local/search/app.js").read_text(encoding="utf-8")
            search_html = output.joinpath("_local/search/index.html").read_text(encoding="utf-8")
            self.assertIn("local_search", search_js)
            self.assertIn("system_name_zh||v.x.system_id", search_js)
            self.assertIn("group.name||id", search_js)
            self.assertIn("title_display||x.title", search_js)
            self.assertIn("summary_display||x.plain_text", search_js)
            self.assertIn("x.title.toLocaleLowerCase()", search_js)
            self.assertIn("x.plain_text.toLocaleLowerCase()", search_js)
            self.assertIn('<nav id="content-tree"', search_html)
            self.assertIn("fetch('game-content-tree.json')", search_js)
            self.assertIn("contentTree.search_categories", search_js)
            self.assertIn("x.content_category_id===selectedCategory", search_js)
            self.assertIn("x.content_subcategory_id===selectedSubcategory", search_js)
            self.assertIn("hiddenSystems.has(x.system_id)", search_js)
            self.assertNotIn("matchesCategory", search_js)
            self.assertIn("content_subcategory_name_zh||x.content_category_name_zh||x.system_name_zh", search_js)
            self.assertIn("collapseEntityHits", search_js)
            self.assertIn("entity_title||x.title_display||x.title", search_js)
            self.assertIn("entity_category_name_zh||x.entity_category", search_js)
            self.assertIn("来源：", search_js)
            self.assertIn("hi(displayTitle,k)", search_js)
            copied_tree = json.loads(output.joinpath("_local/search/game-content-tree.json").read_text(encoding="utf-8"))
            self.assertEqual(copied_tree["schema_version"], 1)
            self.assertEqual(report["raw_pages"], 3)
            self.assertEqual(report["routes_generated"], 2)
            self.assertEqual(len(report["duplicate_route_conflicts"]), 1)
            self.assertGreater(report["html_asset_rewrites"], 0)
            self.assertGreater(report["css_asset_rewrites"], 0)
            self.assertGreater(report["inline_css_rewrites"], 0)
            self.assertGreater(report["internal_page_links_rewritten"], 0)
            self.assertEqual(report["search_forms_rewritten"], 1)
            self.assertGreater(report["tracking_elements_removed"], 0)
            self.assertGreater(report["runtime_http_reference_count"], 0)
            self.assertGreater(report["remaining_remote_asset_references"], 0)
            self.assertTrue(any("could not be mapped" in warning for warning in report["warnings"]))

    def test_confirmed_inventory_manifest_builds_canonical_route_and_skips_known_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_root = root / "raw"
            for system_id, slug in (("inventory", "STR_Helmet"), ("hero", "Anger")):
                path = raw_root / system_id / "raw_html" / f"{slug}.html"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"<html><head><title>{slug}</title></head><body>{slug}</body></html>", encoding="utf-8")
            anger_path = raw_root / "hero/raw_html/Anger.html"
            anger_path.write_text('<html><head><title>Anger</title></head><body><a href="https://tlidb.com/cn/Nether_Kings_Broken_Divinity:_Judgment">Recovered</a></body></html>', encoding="utf-8")
            recovered_path = raw_root / "recovered_internal_pages/raw_html/Nether_Kings_Broken_Divinity%3A_Judgment.html"
            recovered_path.parent.mkdir(parents=True)
            recovered_path.write_text("<html><head><title>Judgment</title></head><body>Recovered</body></html>", encoding="utf-8")
            self.assertTrue(recovered_path.is_file())

            inventory_manifest = root / "inventory_manifest.json"
            inventory_manifest.write_text(json.dumps({"entries": [
                {"id": "STR_Helmet", "slug": "STR_Helmet", "name_zh": "STR Helmet",
                 "url": "https://tlidb.com/cn/STR_Helmet",
                 "validation": {"status": "available", "http_status": 200}},
                {"id": "Vorax_Limb:_Head", "slug": "Vorax_Limb:_Head",
                 "url": "https://tlidb.com/cn/Vorax_Limb:_Head",
                 "validation": {"status": "not_found", "http_status": 404,
                                "reason": "detail_page_missing"}},
            ]}), encoding="utf-8")
            hero_manifest = root / "hero_manifest.json"
            hero_manifest.write_text(json.dumps({"entries": [
                {"id": "Anger", "slug": "Anger", "url": "https://tlidb.com/cn/Anger"},
            ]}), encoding="utf-8")
            help_manifest = root / "help_manifest.json"
            help_manifest.write_text(json.dumps({"entries": [
                {"id": "Hero_Relic", "slug": "Hero_Relic", "url": "https://tlidb.com/cn/Hero_Relic"},
            ]}), encoding="utf-8")
            system_manifest = root / "system_manifest.json"
            system_manifest.write_text(json.dumps({"systems": [
                {"system_id": "hero", "discovery_status": "confirmed", "manifest_path": str(hero_manifest)},
                {"system_id": "inventory", "discovery_status": "confirmed", "manifest_path": str(inventory_manifest)},
                {"system_id": "help", "discovery_status": "confirmed", "manifest_path": str(help_manifest)},
                {"system_id": "candidate", "discovery_status": "candidate", "manifest_path": "ignored.json"},
            ]}), encoding="utf-8")
            supplemental_manifest = root / "recovered_manifest.json"
            supplemental_manifest.write_text(json.dumps({
                "system_id": "recovered_internal_pages", "entries": [
                    {"id": "Nether_Kings_Broken_Divinity:_Judgment",
                     "slug": "Nether_Kings_Broken_Divinity:_Judgment",
                     "url": "https://tlidb.com/cn/Nether_Kings_Broken_Divinity:_Judgment",
                     "validation": {"status": "available", "http_status": 200}},
                    {"id": "STR_Helmet", "slug": "STR_Helmet",
                     "url": "https://tlidb.com/cn/STR_Helmet",
                     "validation": {"status": "available", "http_status": 200}},
                ]}), encoding="utf-8")

            asset_manifest = root / "assets.json"
            asset_manifest.write_text('{"assets": []}', encoding="utf-8")
            output = root / "local_wiki/ss13/site"
            output.parent.mkdir(parents=True)
            catalog = output.parent / "catalog.json"
            search = output.parent / "search-index.json"
            catalog.write_text('{"pages": []}', encoding="utf-8")
            search.write_text('{"pages": []}', encoding="utf-8")

            report = build(
                "ss13", raw_root, asset_manifest, root / "asset-files", output,
                force=True, catalog_path=catalog, search_index_path=search,
                system_manifest_path=system_manifest, supplemental_manifest_path=supplemental_manifest,
                game_category_mapping_path=Path(__file__).resolve().parents[2] / "config/game_category_mapping.json",
            )
            self.assertTrue((output / "cn/STR_Helmet/index.html").is_file())
            self.assertFalse((output / "cn/Inventory/STR_Helmet/index.html").exists())
            self.assertFalse((output / "cn/Vorax_Limb:_Head/index.html").exists())
            self.assertTrue((output / "cn/Anger/index.html").is_file())
            recovered_route = supplemental_route_for_source(
                "https://tlidb.com/cn/Nether_Kings_Broken_Divinity:_Judgment"
            )
            self.assertEqual(recovered_route,
                             "cn/Nether_Kings_Broken_Divinity%3A_Judgment/index.html")
            recovered_output = output_path_for_route(output, recovered_route)
            self.assertEqual(recovered_output,
                             output / "cn/Nether_Kings_Broken_Divinity:_Judgment/index.html")
            self.assertTrue(recovered_output.is_file())
            self.assertFalse((output / recovered_route).exists())
            rendered_anger = (output / "cn/Anger/index.html").read_text(encoding="utf-8")
            self.assertIn('/local_wiki/ss13/site/cn/Nether_Kings_Broken_Divinity%3A_Judgment/', rendered_anger)
            self.assertNotIn('https://tlidb.com/cn/Nether_Kings_Broken_Divinity', rendered_anger)
            self.assertFalse((output / "cn/Nether_Kings_Broken_Divinity/Nether_Kings_Broken_Divinity:_Judgment/index.html").exists())
            generated_catalog = json.loads((output / "catalog.json").read_text(encoding="utf-8"))
            recovered_catalog = next(page for page in generated_catalog["pages"]
                                     if page["id"] == "Nether_Kings_Broken_Divinity:_Judgment")
            self.assertEqual(recovered_catalog["source_type"], "recovered_internal")
            generated_search = json.loads((output / "search-index.json").read_text(encoding="utf-8"))
            recovered_search = next(page for page in generated_search["pages"]
                                    if page["id"] == "Nether_Kings_Broken_Divinity:_Judgment")
            self.assertIsNone(recovered_search["game_category"])
            inventory_search = next(page for page in generated_search["pages"]
                                    if page["id"] == "STR_Helmet")
            self.assertEqual(inventory_search["game_category"], "equipment")
            official_catalog = next(page for page in generated_catalog["pages"] if page["id"] == "STR_Helmet")
            self.assertEqual(official_catalog["source_type"], "official_system")
            self.assertEqual(report["system_count"], 3)
            self.assertTrue(report["inventory_included"])
            self.assertEqual(report["known_missing_pages"], 1)
            self.assertEqual(report["supplemental_pages_included"], 1)
            self.assertEqual(report["recovered_pages_included"], 1)
            self.assertEqual(report["known_missing_detail_pages"], [
                {"system_id": "inventory", "id": "Vorax_Limb:_Head"},
            ])
            self.assertEqual(report["raw_pages_missing_count"], 1)
            self.assertEqual(report["known_missing_raw_pages"], [{
                "system_id": "help", "id": "Hero_Relic",
                "reason": "manifest_entry_without_raw_snapshot",
            }])
            self.assertEqual(report["pages_failed"], 0)

    def test_existing_raw_page_read_error_remains_a_real_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); raw_root = root / "raw"
            raw_path = raw_root / "hero/raw_html/Broken.html"
            raw_path.parent.mkdir(parents=True)
            raw_path.write_bytes(b"\xff\xfe\x00")
            manifest = root / "hero.json"
            manifest.write_text(json.dumps({"entries": [
                {"id": "Broken", "slug": "Broken", "url": "https://tlidb.com/cn/Broken"},
            ]}), encoding="utf-8")
            systems = root / "systems.json"
            systems.write_text(json.dumps({"systems": [
                {"system_id": "hero", "discovery_status": "confirmed", "manifest_path": str(manifest)},
            ]}), encoding="utf-8")
            assets = root / "assets.json"; assets.write_text('{"assets": []}', encoding="utf-8")
            output = root / "site"; output.parent.mkdir(parents=True, exist_ok=True)
            catalog = root / "catalog.json"; catalog.write_text('{"pages": []}', encoding="utf-8")
            search = root / "search.json"; search.write_text('{"pages": []}', encoding="utf-8")
            report = build("ss13", raw_root, assets, root / "asset-files", output,
                           catalog_path=catalog, search_index_path=search,
                           system_manifest_path=systems)
            self.assertEqual(report["raw_pages_missing_count"], 0)
            self.assertEqual(report["pages_failed"], 1)
            self.assertTrue(any("Failed hero/Broken" in error for error in report["errors"]))

    def test_empty_raw_snapshot_is_skipped_without_generating_a_page(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); raw_root = root / "raw"
            empty = raw_root / "hero/raw_html/Empty.html"
            normal = raw_root / "hero/raw_html/Normal.html"
            empty.parent.mkdir(parents=True)
            empty.write_bytes(b"")
            normal.write_text(
                "<!doctype html><html><body><h1>正常页面</h1></body></html>",
                encoding="utf-8",
            )
            manifest = root / "hero.json"
            manifest.write_text(json.dumps({"entries": [
                {"id": "Empty", "slug": "Empty", "url": "https://tlidb.com/cn/Empty"},
                {"id": "Normal", "slug": "Normal", "url": "https://tlidb.com/cn/Normal"},
            ]}), encoding="utf-8")
            systems = root / "systems.json"
            systems.write_text(json.dumps({"systems": [{
                "system_id": "hero", "discovery_status": "confirmed",
                "manifest_path": str(manifest),
            }]}), encoding="utf-8")
            assets = root / "assets.json"
            assets.write_text('{"assets": []}', encoding="utf-8")
            output = root / "site"
            catalog = root / "catalog.json"; catalog.write_text('{"pages": []}', encoding="utf-8")
            search = root / "search.json"; search.write_text('{"pages": []}', encoding="utf-8")

            report = build(
                "ss13", raw_root, assets, root / "asset-files", output,
                force=True, catalog_path=catalog, search_index_path=search,
                system_manifest_path=systems,
            )

            self.assertFalse((output / "cn/Empty/index.html").exists())
            self.assertTrue((output / "cn/Normal/index.html").is_file())
            self.assertEqual(1, report["routes_generated"])
            self.assertEqual(0, report["pages_failed"])
            self.assertEqual(1, report["empty_snapshot_skipped_count"])
            self.assertEqual({
                "system_id": "hero",
                "id": "Empty",
                "route": "/cn/Empty/",
                "raw_size": 0,
                "reason": "skipped_empty_snapshot",
            }, report["empty_snapshot_skipped_examples"][0])

    def test_system_display_name_uses_manifest_sources_then_native_i18n_then_id(self):
        translations = {
            "item_type_list|name|50606": "崇高辅助技能",
            "function|name|133": "侵蚀",
            "AuctionHouse_rough_search|description|1": "传奇装备",
        }
        self.assertEqual(system_display_name(
            {"system_id": "legendary_gear", "name_zh": "自定义中文"}, translations
        ), "自定义中文")
        self.assertEqual(system_display_name(
            {"system_id": "legendary_gear", "name_zh": "Legendary Gear"},
            translations, {"name_zh": "其它清单中文"}
        ), "其它清单中文")
        self.assertEqual(system_display_name(
            {"system_id": "legendary_gear", "name_zh": "Legendary Gear"}, translations
        ), "传奇装备")
        self.assertEqual(system_display_name(
            {"system_id": "noble_support_skill", "name_zh": "Noble Support Skill"}, translations
        ), "崇高辅助技能")
        self.assertEqual(system_display_name(
            {"system_id": "corrosion", "name_zh": "Corrosion"}, translations
        ), "侵蚀")
        self.assertEqual(system_display_name(
            {"system_id": "hyperlink", "name_zh": "Hyperlink"}, {}
        ), "超链接")
        self.assertEqual(system_display_name(
            {"system_id": "recovered_internal_pages"}, {}
        ), "补充页面")
        self.assertEqual(system_display_name(
            {"system_id": "unknown_system", "name_zh": "Unknown"}, {}
        ), "unknown_system")

    def test_game_category_mapping_covers_confirmed_and_leaves_unmapped_null(self):
        mapping = load_game_category_mapping(
            Path(__file__).resolve().parents[2] / "config/game_category_mapping.json"
        )
        self.assertEqual(mapping["hero"]["game_category"], "hero")
        self.assertEqual(mapping["hero"]["game_category_name_zh"], "英雄")
        self.assertEqual(mapping["craft"]["game_category"], "equipment")
        self.assertEqual(mapping["craft"]["game_category_name_zh"], "装备")
        self.assertEqual(mapping["active_skill"]["game_category"], "skill")
        fixtures = [
            {"system_id": "inventory", "game_category": mapping["inventory"]["game_category"]},
            {"system_id": "active_skill", "game_category": mapping["active_skill"]["game_category"]},
            {"system_id": "hero", "game_category": mapping["hero"]["game_category"]},
            {"system_id": "hyperlink", "game_category": None},
        ]
        self.assertEqual([x["system_id"] for x in fixtures if x["game_category"] == "equipment"], ["inventory"])
        self.assertEqual([x["system_id"] for x in fixtures if x["game_category"] == "skill"], ["active_skill"])
        self.assertEqual([x["system_id"] for x in fixtures if x["game_category"] == "hero"], ["hero"])
        self.assertEqual(len(fixtures), 4)
        self.assertEqual([x["system_id"] for x in fixtures if not x["game_category"]], ["hyperlink"])
        for system_id in ("hyperlink", "recovered_internal_pages", "unknown_system"):
            category = mapping.get(system_id, {})
            self.assertIsNone(category.get("game_category"))

    def test_game_content_tree_maps_primary_and_secondary_categories(self):
        mapping = load_game_content_tree(
            Path(__file__).resolve().parents[2] / "config/game_content_tree.json"
        )
        expected = {
            "hero": ("hero", "英雄", "hero_trait", "英雄特性"),
            "boon": ("hero", "英雄", "hero_memory", "追忆"),
            "craft": ("equipment", "装备", "equipment_craft", "打造装备"),
            "legendary_gear": ("equipment", "装备", "equipment_legendary", "传奇装备"),
            "active_skill": ("skill", "技能", "skill_active", "主动技能"),
                "talent": ("talent_board", "天赋系统", "talent_hero", "英雄天赋"),
            "pactspirit": ("pact_spirit", "契灵系统", "pact_spirit_entity", "契灵"),
            "destiny": ("pact_spirit", "契灵系统", "pact_spirit_destiny", "命运"),
        }
        for system_id, values in expected.items():
            item = content_tree_fields_for_system(system_id, mapping)
            self.assertEqual(values, (
                item["content_category_id"], item["content_category_name_zh"],
                item["content_subcategory_id"], item["content_subcategory_name_zh"],
            ))

        hidden = content_tree_fields_for_system("hyperlink", mapping)
        self.assertTrue(all(value is None for value in hidden.values()))

    def test_content_tree_classification_priority(self):
        root = Path(__file__).resolve().parents[2]
        tree = load_game_content_tree(root / "config/game_content_tree.json")
        entities = load_entity_index(root / "data/generated/entity-index.json")

        cases = [
            (
                {"system_id": "inventory", "route": "/cn/Divinity_Slate/"},
                ("talent_board", "talent_divinity_slate", "route_override"),
            ),
            (
                {"system_id": "inventory", "route": "/cn/Active_Skill/"},
                ("skill", "skill_active", "route_override"),
            ),
            (
                {"system_id": "corrosion", "route": "/cn/Legendary_Gear/"},
                ("equipment", "equipment_legendary", "route_override"),
            ),
            (
                {"system_id": "craft", "route": "/cn/Trinity/"},
                ("equipment", "equipment_legendary", "entity_override"),
            ),
            (
                {"system_id": "craft", "route": "/cn/Ordinary_Craft_Page/"},
                (None, None, "craft_rejected"),
            ),
        ]
        for page, expected in cases:
            fields, source = resolve_content_tree_classification(page, entities, tree)
            self.assertEqual(expected, (
                fields["content_category_id"], fields["content_subcategory_id"], source,
            ))

    def test_inventory_equipment_classification_requires_confirmed_entity(self):
        tree = load_game_content_tree(
            Path(__file__).resolve().parents[2] / "config/game_content_tree.json"
        )
        entities = {
            "/cn/STR_Helmet/": {
                "entity_type": "equipment", "content_category_id": "equipment",
                "content_category_name_zh": "装备",
                "content_subcategory_id": "equipment_craft",
                "content_subcategory_name_zh": "打造装备",
            },
            "/cn/Vorax_Limb:_Head/": {
                "entity_type": "equipment", "content_category_id": "equipment",
                "content_category_name_zh": "装备",
                "content_subcategory_id": "equipment_vorax",
                "content_subcategory_name_zh": "渴瘾装备",
            },
            "/cn/Sandlord_Season/": {
                "entity_type": None, "content_category_id": "equipment",
                "content_category_name_zh": "装备",
                "content_subcategory_id": "equipment_type",
                "content_subcategory_name_zh": "装备类型",
            },
            "/cn/Flawless_Heart_-_Buff/": {
                "entity_type": None, "content_category_id": "equipment",
                "content_category_name_zh": "装备",
                "content_subcategory_id": "equipment_type",
                "content_subcategory_name_zh": "装备类型",
            },
        }
        for route, subcategory in (
            ("/cn/STR_Helmet/", "equipment_craft"),
            ("/cn/Vorax_Limb:_Head/", "equipment_vorax"),
        ):
            fields, source = resolve_content_tree_classification(
                {"system_id": "inventory", "route": route}, entities, tree
            )
            self.assertEqual("equipment", fields["content_category_id"])
            self.assertEqual(subcategory, fields["content_subcategory_id"])
            self.assertEqual("entity_override", source)

        for route in ("/cn/Sandlord_Season/", "/cn/Flawless_Heart_-_Buff/"):
            fields, source = resolve_content_tree_classification(
                {"system_id": "inventory", "route": route}, entities, tree
            )
            self.assertTrue(all(value is None for value in fields.values()))
            self.assertEqual("inventory_unclassified", source)

    def test_inventory_route_mapping_can_preserve_non_equipment_category(self):
        tree = load_game_content_tree(
            Path(__file__).resolve().parents[2] / "config/game_content_tree.json"
        )
        entities = {
            "/cn/Ethereal_Prism/": {
                "entity_type": None, "content_category_id": "equipment",
                "content_category_name_zh": "装备",
                "content_subcategory_id": "equipment_type",
                "content_subcategory_name_zh": "装备类型",
            }
        }
        fields, source = resolve_content_tree_classification(
            {"system_id": "inventory", "route": "/cn/Ethereal_Prism/"}, entities, tree
        )
        self.assertEqual("talent_board", fields["content_category_id"])
        self.assertEqual("talent_ethereal_prism", fields["content_subcategory_id"])
        self.assertEqual("route_override", source)


if __name__ == "__main__":
    unittest.main()
