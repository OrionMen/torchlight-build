import unittest

from crawler.discover_manifest import discover_from_html, validate_entries


INDEX_URL = "https://tlidb.com/cn/Hero"
FIXTURE = """
<!doctype html>
<html><body>
  <nav><a href="/cn/Outside">导航外链接</a></nav>
  <section class="card">
    <h2>英雄 /3</h2>
    <div class="hero-list">
      <a href="/cn/Anger"><span>狂人 雷恩|怒火</span></a>
      <a href="Flame">圣枪 卡里诺|荣光游侠</a>
      <a href="https://tlidb.com/cn/Anger">重复英雄</a>
      <a href="/cn/Hero">当前目录</a>
      <a href="https://example.com/cn/Other">外部链接</a>
      <a href="/cn/icon.png">静态文件</a>
      <a href="#part">锚点</a>
      <a href="javascript:void(0)">脚本</a>
      <a href="mailto:test@example.com">邮件</a>
      <a href="/cn/Blank"></a>
    </div>
  </section>
</body></html>
"""


class ManifestDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.entries, self.report = discover_from_html(
            FIXTURE,
            INDEX_URL,
            "hero",
            expected_count=3,
            label="英雄",
        )

    def test_container_scope_and_relative_url_normalization(self):
        self.assertEqual([entry["slug"] for entry in self.entries], ["Anger", "Flame"])
        self.assertEqual(self.entries[1]["url"], "https://tlidb.com/cn/Flame")
        self.assertNotIn("Outside", [entry["slug"] for entry in self.entries])

    def test_duplicate_url_is_deduplicated_in_source_order(self):
        self.assertEqual(len(self.entries), 2)
        self.assertEqual(self.entries[0]["source_order"], 0)
        self.assertEqual(self.report["duplicate_urls"], ["https://tlidb.com/cn/Anger"])

    def test_visible_chinese_name_is_preserved(self):
        self.assertEqual(self.entries[0]["name_zh"], "狂人 雷恩|怒火")

    def test_exclusions_and_current_page(self):
        excluded = self.report["excluded"]
        self.assertEqual(excluded["self"], 1)
        self.assertEqual(excluded["external_domain"], 1)
        self.assertEqual(excluded["static_resource"], 1)
        self.assertEqual(excluded["anchor"], 1)
        self.assertEqual(self.report["links_without_text"], 1)

    def test_duplicate_id_validation_fails(self):
        errors = validate_entries(
            [
                {"id": "Same", "url": "https://tlidb.com/cn/One"},
                {"id": "Same", "url": "https://tlidb.com/cn/Two"},
            ]
        )
        self.assertTrue(any("duplicate entry ids" in error for error in errors))

    def test_missing_stable_container_fails(self):
        entries, report = discover_from_html(
            "<nav><a href='/cn/One'>一</a></nav>",
            INDEX_URL,
            "hero",
            expected_count=1,
            label="英雄",
        )
        self.assertEqual(entries, [])
        self.assertTrue(report["errors"])


if __name__ == "__main__":
    unittest.main()
