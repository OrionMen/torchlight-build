import json
import tempfile
import unittest
from pathlib import Path

from crawler.build_full_wiki_mirror import (
    CSSRewriter,
    HTMLRewriter,
    copy_i18n_files,
    rewrite_i18n_runtime_paths,
)
from crawler.discover_wiki_i18n import scan
from crawler.fetch_wiki_i18n import fetch_resources, local_relative_path


class WikiI18nTest(unittest.TestCase):
    def test_discovers_runtime_i18n_urls_from_real_template_and_page_language(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "page.html").write_text('<html lang="cn"><span data-i18n="Hero">Hero</span></html>', encoding="utf-8")
            (root / "header.js").write_text('$.getJSON(`/i18n/${lang}.json?_=1`); $.get(`/i18n/autocomplete_${lang}.json?_=1`);', encoding="utf-8")
            report = scan([root])
            urls = {item["resource_url"] for item in report["resources"]}
            self.assertEqual(urls, {"https://tlidb.com/i18n/cn.json?_=1",
                                    "https://tlidb.com/i18n/autocomplete_cn.json?_=1"})
            self.assertEqual(report["data_i18n_key_count"], 1)

    def test_ignores_unrelated_local_page_language_for_runtime_template(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "tlidb.html").write_text('<html lang="cn"><span data-i18n="Hero"></span></html>', encoding="utf-8")
            (root / "local.html").write_text('<html lang="zh-CN"><p>Local Search</p></html>', encoding="utf-8")
            (root / "header.js").write_text('$.getJSON(`/i18n/${lang}.json`)', encoding="utf-8")
            urls = {item["resource_url"] for item in scan([root])["resources"]}
            self.assertEqual(urls, {"https://tlidb.com/i18n/cn.json"})

    def test_discovers_relative_i18n_json_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "loader.js").write_text('fetch("i18n/cn.json")', encoding="utf-8")
            urls = {item["resource_url"] for item in scan([root])["resources"]}
            self.assertEqual(urls, {"https://tlidb.com/i18n/cn.json"})

    def test_fetch_cache_preserves_json_keys_and_chinese_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary); calls = []
            body = '{"Hero":"英雄","Stash":"仓库"}'.encode()
            def fetcher(url, timeout):
                calls.append(url); return {"body": body, "http_status": 200,
                    "final_url": url, "request_url": url, "content_type": "application/json"}
            resources = [{"resource_url": "https://tlidb.com/i18n/cn.json?_=1"}]
            first = fetch_resources(resources, output, retries=0, rate_limit=0, fetcher=fetcher)
            second = fetch_resources(resources, output, retries=0, rate_limit=0,
                                     fetcher=lambda *_: (_ for _ in ()).throw(AssertionError("cache")))
            saved = json.loads((output / "files/i18n/cn.json").read_text(encoding="utf-8"))
            self.assertEqual(saved, {"Hero": "英雄", "Stash": "仓库"})
            self.assertEqual((first["downloaded"], second["cache_hit"], len(calls)), (1, 1, 1))

    def test_local_mapping_runtime_rewrite_and_copy(self):
        self.assertEqual(local_relative_path("https://tlidb.com/i18n/cn.json?v=1"), Path("i18n/cn.json"))
        rewritten = rewrite_i18n_runtime_paths('$.getJSON(`/i18n/${lang}.json`)', "/local_wiki/ss13/site/")
        self.assertIn('`/local_wiki/ss13/site/i18n/${lang}.json`', rewritten)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / "raw/i18n/cn.json"
            source.parent.mkdir(parents=True); source.write_text('{"Hero":"英雄"}', encoding="utf-8")
            output = root / "site"
            self.assertEqual(copy_i18n_files(root / "raw", output), 1)
            self.assertEqual((output / "i18n/cn.json").read_text(encoding="utf-8"), '{"Hero":"英雄"}')

    def test_runtime_rewrite_covers_common_loaders_but_not_external_json(self):
        source = """fetch('/i18n/cn.json');
        xhr.open('GET', '/i18n/cn.json');
        $.get('/i18n/cn.json');
        $.getJSON(`/i18n/${lang}.json`);
        fetch('https://example.com/language.json');"""
        rewritten = rewrite_i18n_runtime_paths(source, "/local_wiki/ss13/site/")
        self.assertEqual(rewritten.count("/local_wiki/ss13/site/i18n/"), 4)
        self.assertIn("https://example.com/language.json", rewritten)

    def test_inline_script_i18n_request_is_rewritten(self):
        prefix = "/local_wiki/ss13/site/"
        rewriter = HTMLRewriter("https://tlidb.com/cn/Anger", {}, {}, prefix, CSSRewriter({}, prefix))
        rewriter.feed("<script>fetch('/i18n/cn.json')</script>")
        rendered = "".join(rewriter.output)
        self.assertIn("fetch('/local_wiki/ss13/site/i18n/cn.json')", rendered)

    def test_data_i18n_key_resolves_to_original_chinese_value(self):
        translations = json.loads('{"HeroRanking|name|1":"英雄"}')
        key = "HeroRanking|name|1"
        self.assertEqual(translations[key], "英雄")

    def test_navbar_uses_official_keys_with_english_fallback(self):
        navbar = [
            ("Hero", "HeroRanking|name|1", "英雄"),
            ("Stash", "function|name|115", "仓库"),
            ("Skill", "function|name|100", "技能"),
            ("Craft", "function|name|128", "打造"),
            ("Merits", "function|name|125", "成就"),
            ("Netherrealm", "system_help|name|8", "异界"),
            ("Shop", "function|name|110", "商城"),
        ]
        translations = {key: translated for _, key, translated in navbar}
        rendered = [translations.get(key) or fallback for fallback, key, _ in navbar]
        self.assertEqual(rendered, [translated for _, _, translated in navbar])
        self.assertEqual(translations.get("missing-key") or "English fallback", "English fallback")


if __name__ == "__main__": unittest.main()
