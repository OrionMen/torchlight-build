import unittest

from crawler.build_full_wiki_mirror import local_assets


class SearchEntityDisplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assets = local_assets()
        cls.script = assets["_local/search/app.js"]
        cls.styles = assets["_local/search/styles.css"]

    def test_trinity_like_entity_results_are_collapsed_once(self):
        self.assertIn("const collapseEntityHits=(hits,allSources)", self.script)
        self.assertIn("if(!entities.has(id))", self.script)
        self.assertIn("entities.get(id)", self.script)

    def test_single_page_and_unmodeled_results_keep_page_fallback(self):
        self.assertIn("if(!id){display.push({...v,kind:'page'})", self.script)
        self.assertIn("x.title_display||x.title", self.script)

    def test_entity_category_uses_chinese_display_name(self):
        self.assertIn("x.entity_category_name_zh||x.entity_category||'未分类'", self.script)
        self.assertIn("class=\"entity-category\"", self.script)

    def test_sources_are_aggregated_across_same_entity(self):
        self.assertIn("collectEntitySources", self.script)
        self.assertIn("x.system_name_zh||x.system_id", self.script)
        self.assertIn("来源：", self.script)

    def test_search_matching_and_highlight_are_preserved(self):
        self.assertIn("const t=x.title.toLocaleLowerCase(),p=x.plain_text.toLocaleLowerCase()", self.script)
        self.assertIn("hi(displayTitle,k)", self.script)
        self.assertIn("<mark>", self.script)

    def test_entity_card_has_distinct_non_destructive_style(self):
        self.assertIn(".entity-card", self.styles)
        self.assertIn(".entity-sources", self.styles)


if __name__ == "__main__":
    unittest.main()
