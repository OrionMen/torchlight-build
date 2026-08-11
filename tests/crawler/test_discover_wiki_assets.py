import json
import tempfile
import unittest
from pathlib import Path

from crawler.discover_wiki_assets import discover


class WikiAssetDiscoveryTest(unittest.TestCase):
    def test_discovers_normalizes_deduplicates_and_excludes_tracking(self):
        with tempfile.TemporaryDirectory() as temporary:
            raw = Path(temporary) / "raw"; html_dir = raw / "hero/raw_html"; meta_dir = raw / "hero/meta"
            html_dir.mkdir(parents=True); meta_dir.mkdir(parents=True)
            (meta_dir / "Page.meta.json").write_text(json.dumps({"final_url":"https://tlidb.com/cn/Page"}),encoding="utf-8")
            (html_dir / "Page.html").write_text("""<html><head>
              <link rel="stylesheet" href="/assets/site.css?v=1#x"><link rel="icon" href="//cdn.tlidb.com/icon.png">
              <script src="https://google-analytics.com/track.js"></script>
              <style>@font-face{src:url('../font/a.woff2')} @import "theme.css";</style></head><body>
              <img src="img/a.webp?size=2#frag" srcset="img/a.webp?size=2 1x, //cdn.tlidb.com/a@2x.webp 2x">
              <script src="/assets/app.js"></script><source src="movie.webm" srcset="poster.jpg 1x">
              <video poster="cover.jpg"></video><object data="manual.pdf"></object></body></html>""",encoding="utf-8")
            manifest, report = discover("ss13", raw)
            urls = {item["source_url"] for item in manifest["assets"]}
            self.assertIn("https://tlidb.com/cn/img/a.webp?size=2", urls)
            self.assertIn("https://cdn.tlidb.com/icon.png", urls)
            self.assertIn("https://tlidb.com/assets/site.css?v=1", urls)
            self.assertNotIn("https://google-analytics.com/track.js", urls)
            self.assertEqual(report["pages_scanned"], 1)
            self.assertEqual(report["excluded_tracking_count"], 1)
            self.assertGreater(report["duplicate_reference_count"], 0)
            self.assertEqual(manifest["unique_asset_count"], len(urls))
            self.assertTrue(any(item["asset_type"]=="font" for item in manifest["assets"]))
            self.assertTrue(any(item["asset_type"]=="javascript" for item in manifest["assets"]))
            self.assertTrue(any(item["asset_type"]=="icon" for item in manifest["assets"]))
            files = Path(temporary) / "files"; css = files / "css/aa/bb/s.css"; css.parent.mkdir(parents=True)
            css.write_text("@font-face{src:url(font/local.woff2)}", encoding="utf-8")
            previous = {"assets":[{"asset_id":"a"*64,"source_url":"https://cdn.tlidb.com/css/site.css",
                                    "asset_type":"stylesheet","local_relative_path":"css/aa/bb/s.css"}]}
            recursive, _ = discover("ss13", raw, previous, files)
            self.assertTrue(any(item["source_url"]=="https://cdn.tlidb.com/css/font/local.woff2" for item in recursive["assets"]))

    def test_merges_downloaded_css_dependencies_until_converged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); raw = root / "raw"; html_dir = raw / "hero/raw_html"
            html_dir.mkdir(parents=True)
            html_dir.joinpath("Page.html").write_text(
                '<link rel="stylesheet" href="https://cdn.tlidb.com/assets/css/site/main.css">'
                '<img src="/existing.png">', encoding="utf-8")
            files = root / "files"
            first, first_report = discover("ss13", raw, files_root=files)
            first_by_url = {item["source_url"]: item for item in first["assets"]}
            self.assertEqual(first_report["css_not_downloaded"], 1)
            self.assertEqual(first_report["errors"], [])
            css_url = "https://cdn.tlidb.com/assets/css/site/main.css"
            css_asset = first_by_url[css_url]
            css_path = files / css_asset["local_relative_path"]
            css_path.parent.mkdir(parents=True)
            css_path.write_text("""
                @font-face { src: url('../fonts/test.woff2?v=123#font'); }
                .background { background-image: url('/images/bg.webp'); }
                .absolute { background: url('https://static.example.com/absolute.png'); }
                .protocol { mask: url(//cdn.tlidb.com/icons/icon.svg#shape); }
                @import url("theme/imported.css?x=1#top");
                .duplicate { background: url('/images/bg.webp'); }
                .tracking { background: url('https://google-analytics.com/pixel.png'); }
            """, encoding="utf-8")

            second, second_report = discover("ss13", raw, first, files)
            second_by_url = {item["source_url"]: item for item in second["assets"]}
            expected = {
                "https://cdn.tlidb.com/assets/css/fonts/test.woff2?v=123",
                "https://cdn.tlidb.com/images/bg.webp",
                "https://static.example.com/absolute.png",
                "https://cdn.tlidb.com/icons/icon.svg",
                "https://cdn.tlidb.com/assets/css/site/theme/imported.css?x=1",
            }
            self.assertTrue(expected.issubset(second_by_url))
            self.assertNotIn("https://google-analytics.com/pixel.png", second_by_url)
            self.assertEqual(second_report["css_scanned"], 1)
            self.assertEqual(second_report["css_secondary_reference_count"], 6)
            self.assertEqual(second_report["css_secondary_unique_asset_count"], 5)
            self.assertEqual(second_report["new_assets_from_css"], 5)
            self.assertFalse(second_report["discovery_converged"])
            self.assertGreaterEqual(second_report["excluded_tracking_count"], 1)
            self.assertEqual(second_by_url[css_url]["asset_id"], css_asset["asset_id"])
            self.assertEqual(second_by_url[css_url]["local_relative_path"], css_asset["local_relative_path"])
            font = second_by_url["https://cdn.tlidb.com/assets/css/fonts/test.woff2?v=123"]
            imported = second_by_url["https://cdn.tlidb.com/assets/css/site/theme/imported.css?x=1"]
            self.assertEqual(font["asset_type"], "font")
            self.assertEqual(imported["asset_type"], "stylesheet")
            self.assertTrue(any(ref.get("source_kind") == "stylesheet" and
                                ref.get("source_asset_id") == css_asset["asset_id"]
                                for ref in font["referenced_by"]))
            self.assertEqual(second_report["css_not_downloaded"], 0)
            self.assertEqual(second_report["errors"], [])

            imported_path = files / imported["local_relative_path"]
            imported_path.parent.mkdir(parents=True, exist_ok=True)
            imported_path.write_text("/* no further dependencies */", encoding="utf-8")
            third, third_report = discover("ss13", raw, second, files)
            third_by_url = {item["source_url"]: item for item in third["assets"]}
            self.assertEqual(third_report["css_scanned"], 2)
            self.assertEqual(third_report["new_assets_from_css"], 0)
            self.assertTrue(third_report["discovery_converged"])
            self.assertEqual(third_by_url[css_url]["asset_id"], css_asset["asset_id"])
            self.assertEqual(third_by_url[css_url]["local_relative_path"], css_asset["local_relative_path"])
            self.assertEqual(first_report["html_discovered_unique_assets"], 2)


if __name__ == "__main__": unittest.main()
