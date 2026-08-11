import json
import tempfile
import unittest
from pathlib import Path

from crawler.build_local_wiki import build


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def manifest(system_id, entries):
    return {"system_id": system_id, "entries": entries}


class LocalWikiBuildTest(unittest.TestCase):
    def test_builds_catalog_search_pages_links_and_continues_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / "sources"
            raw = root / "raw"
            output = root / "local_wiki/ss13"
            systems = {"systems": [
                {"system_id": "alpha", "discovery_status": "confirmed", "manifest_path": str(sources / "alpha.json")},
                {"system_id": "beta", "discovery_status": "confirmed", "manifest_path": str(sources / "beta.json")},
            ]}
            write_json(sources / "systems.json", systems)
            write_json(sources / "alpha.json", manifest("alpha", [
                {"id": "A", "slug": "A", "name_zh": "清单标题", "url": "https://tlidb.com/cn/A"},
                {"id": "Broken", "slug": "Broken", "name_zh": "坏页", "url": "https://tlidb.com/cn/Broken"},
            ]))
            write_json(sources / "beta.json", manifest("beta", [
                {"id": "B", "slug": "B", "name_zh": "乙", "url": "https://tlidb.com/cn/B"},
            ]))
            alpha = raw / "alpha/raw_html"; beta = raw / "beta/raw_html"
            alpha.mkdir(parents=True); beta.mkdir(parents=True)
            (alpha / "A.html").write_text("""<!doctype html><html><head><style>隐藏样式</style><script>隐藏脚本</script></head><body><h1>真实标题</h1><p>中文 战意 searchable</p><a href="/cn/B">本地</a><a href="/cn/Missing">缺失</a><a href="https://example.com/x">外部</a><span data-bs-toggle="tooltip" data-bs-title="提示原文">词</span></body></html>""", encoding="utf-8")
            (alpha / "Broken.html").write_bytes(b"\xff\xfe")
            (beta / "B.html").write_text("<html><body><h1>乙页面</h1><p>怒气</p></body></html>", encoding="utf-8")

            report = build("ss13", sources / "systems.json", raw, output, force=True)
            self.assertEqual((report["raw_pages_found"], report["pages_generated"], report["pages_failed"]), (3, 2, 1))
            self.assertEqual(report["rewritten_internal_links"], 1)
            self.assertEqual(report["unresolved_internal_links"], 1)
            self.assertTrue(any("Unresolved internal slug" in warning for warning in report["warnings"]))
            rendered = (output / "pages/alpha/A.html").read_text(encoding="utf-8")
            self.assertIn('href="../beta/B.html"', rendered)
            self.assertIn('href="https://example.com/x"', rendered)
            self.assertIn('data-bs-title="提示原文"', rendered)
            self.assertIn("../../../app/", rendered)
            catalog = json.loads((output / "catalog.json").read_text(encoding="utf-8"))
            index = json.loads((output / "search-index.json").read_text(encoding="utf-8"))
            self.assertEqual(catalog["page_count"], 2)
            self.assertEqual(catalog["pages"][0]["title"], "真实标题")
            self.assertEqual(index["page_count"], 2)
            self.assertIn("中文 战意 searchable", index["pages"][0]["plain_text"])
            self.assertNotIn("隐藏脚本", index["pages"][0]["plain_text"])
            self.assertNotIn("隐藏样式", index["pages"][0]["plain_text"])
            self.assertTrue((root / "local_wiki/app/index.html").is_file())


if __name__ == "__main__":
    unittest.main()
