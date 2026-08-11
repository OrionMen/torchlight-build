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
    output_path_for_route,
    route_for_source,
    supplemental_route_for_source,
)


class FullWikiMirrorBuilderTest(unittest.TestCase):
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
                {"system_id":"hero","id":"Page","slug":"Page","title":"页面","source_url":"https://tlidb.com/cn/Page"},
                {"system_id":"help","id":"Other","slug":"Other","title":"其它","source_url":"https://tlidb.com/cn/Other"},
                {"system_id":"hyperlink","id":"PageCopy","slug":"PageCopy","title":"副本","source_url":"https://tlidb.com/cn/Page"},
            ]}
            search = {"pages": [
                {"system_id":"hero","id":"Page","title":"战意页面","plain_text":"这里包含战意测试内容"},
                {"system_id":"help","id":"Other","title":"其它","plain_text":"其它内容"},
            ]}
            catalog_path = output.parent / "catalog.json"; search_path = output.parent / "search-index.json"
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8"); search_path.write_text(json.dumps(search), encoding="utf-8")

            report = build("ss13", raw_root, manifest_path, asset_root, output, force=True,
                           catalog_path=catalog_path, search_index_path=search_path)
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
            search_js = output.joinpath("_local/search/app.js").read_text(encoding="utf-8")
            self.assertIn("local_search", search_js)
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


if __name__ == "__main__":
    unittest.main()
