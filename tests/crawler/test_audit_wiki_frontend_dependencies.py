import json
import tempfile
import unittest
from pathlib import Path

from crawler.audit_wiki_frontend_dependencies import audit


class FrontendDependencyAuditTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.raw_root = root / "raw"
        html_dir = self.raw_root / "hero" / "raw_html"
        html_dir.mkdir(parents=True)
        html_dir.joinpath("Page.html").write_text(
            """<!doctype html><html><head>
<link rel="stylesheet" href="https://cdn.tlidb.com/site.css">
<link rel="icon" href="https://cdn.tlidb.com/missing.png">
<script src="https://cdn.tlidb.com/app.js"></script>
<style>.inline{background:url('/img/inline.png')}</style>
</head><body style="background:url('/img/attribute.png')">
<nav></nav><aside class="sidebar"></aside>
<a href="/cn/Other">Other</a><a href="#part">Part</a>
<form action="/cn/search"></form>
<button title="Tip" data-bs-title="Embedded" data-bs-toggle="tooltip"></button>
<button data-bs-toggle="collapse"></button><button data-bs-toggle="modal"></button>
<button data-bs-toggle="tab"></button>
<script>fetch('/api/data'); fetch('https://s.nitropay.com/ad.json'); new XMLHttpRequest(); $.ajax({url:'/ajax/info'});</script>
<footer></footer></body></html>""",
            encoding="utf-8",
        )
        self.asset_root = root / "assets"
        css_rel = "stylesheet/aa/site.css"
        js_rel = "javascript/bb/app.js"
        (self.asset_root / css_rel).parent.mkdir(parents=True)
        (self.asset_root / js_rel).parent.mkdir(parents=True)
        (self.asset_root / css_rel).write_text(
            '@import "theme.css"; @font-face{src:url("font.woff2")} .x{background:url("bg.png")}',
            encoding="utf-8",
        )
        (self.asset_root / js_rel).write_text("fetch('/json/data'); new XMLHttpRequest();", encoding="utf-8")
        assets = [
            {"asset_id": "aa11", "asset_type": "stylesheet", "source_url": "https://cdn.tlidb.com/site.css", "local_relative_path": css_rel},
            {"asset_id": "bb22", "asset_type": "javascript", "source_url": "https://cdn.tlidb.com/app.js", "local_relative_path": js_rel},
            {"asset_id": "cc33", "asset_type": "image", "source_url": "https://cdn.tlidb.com/missing.png", "local_relative_path": "image/cc/missing.png"},
        ]
        self.manifest = root / "asset-manifest.json"
        self.manifest.write_text(json.dumps({"assets": assets}), encoding="utf-8")
        for asset_id in ("aa11", "bb22"):
            meta = self.asset_root / "meta" / asset_id[:2] / asset_id[2:4] / f"{asset_id}.meta.json"
            meta.parent.mkdir(parents=True, exist_ok=True)
            meta.write_text("{}", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_audits_static_runtime_interaction_and_navigation_dependencies(self):
        result = audit("ss13", self.raw_root, self.manifest, self.asset_root)

        self.assertEqual(result["pages"], 1)
        self.assertEqual(result["assets"]["expected"], 3)
        self.assertEqual(result["assets"]["present"], 2)
        self.assertEqual(result["assets"]["missing_files"], ["cc33"])
        self.assertEqual(result["html_dependencies"]["inline_script_blocks"], 1)
        self.assertEqual(result["html_dependencies"]["inline_style_blocks"], 1)
        self.assertEqual(result["html_dependencies"]["inline_style_attributes"], 1)
        patterns = result["javascript_audit"]["runtime_pattern_counts"]
        self.assertGreaterEqual(patterns["fetch"], 2)
        self.assertGreaterEqual(patterns["XMLHttpRequest"], 2)
        self.assertEqual(patterns["$.ajax"], 1)
        self.assertIn("https://tlidb.com/api/data", result["javascript_audit"]["runtime_http_endpoints"])
        self.assertNotIn("https://s.nitropay.com/ad.json", result["javascript_audit"]["runtime_http_endpoints"])
        self.assertIn("https://s.nitropay.com/ad.json", result["javascript_audit"]["tracking_runtime_urls"])
        self.assertGreaterEqual(result["javascript_audit"]["runtime_url_pattern_counts"]["/api/"], 1)
        self.assertGreaterEqual(len(result["css_audit"]["missing_secondary_assets"]), 5)
        interaction_counts = {item["feature"]: item["pages_affected"] for item in result["interactions"]}
        self.assertEqual(interaction_counts["tooltip"], 1)
        self.assertEqual(interaction_counts["collapse"], 1)
        self.assertEqual(interaction_counts["modal"], 1)
        self.assertEqual(interaction_counts["tabs"], 1)
        self.assertEqual(result["navigation"]["form_action_count"], 1)
        self.assertGreaterEqual(result["navigation"]["pure_rewrite_count"], 2)
        self.assertEqual(result["mirror_readiness"], "not_ready")


if __name__ == "__main__":
    unittest.main()
