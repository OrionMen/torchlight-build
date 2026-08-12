import unittest
from pathlib import Path

from crawler.audit_legendary_gear_v1 import build_audit, inspect_legendary_html


ROOT = Path(__file__).resolve().parents[2]


class LegendaryGearAuditV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = build_audit(ROOT)
        cls.by_id = {item["id"]: item for item in cls.report["entities"]}

    def test_legendary_pages_are_identified_as_entities(self):
        self.assertEqual(339, self.report["total_pages"])
        self.assertEqual(274, self.report["raw_pages_available"])
        self.assertEqual(65, self.report["raw_pages_empty"])
        self.assertEqual(267, self.report["confirmed_entity_pages"])
        self.assertEqual(7, self.report["non_equipment_pages"])
        self.assertFalse(self.report["search_recommendation"]["one_page_one_entity"])
        self.assertTrue(self.report["search_recommendation"]["analyzed_legendary_pages_are_entities"])

    def test_thunder_prosthetics_lore_is_identified(self):
        item = self.by_id["Thunder_Channeling_Prosthetics"]
        self.assertEqual("引雷义肢", item["title"])
        self.assertGreater(item["lore_section_count"], 0)
        self.assertIn("矮人族的祖先玛格努斯", item["lore_examples"][0])

    def test_thunder_prosthetics_corrosion_is_identified(self):
        item = self.by_id["Thunder_Channeling_Prosthetics"]
        self.assertGreater(item["corrosion_section_count"], 0)
        self.assertGreater(item["corrosion_effect_count"], 0)

    def test_search_region_recommendations(self):
        include = self.report["search_recommendation"]["include"]
        exclude = self.report["search_recommendation"]["exclude"]
        self.assertIn("固定词条", include)
        self.assertIn("已侵蚀效果", include)
        self.assertIn("Lore", exclude)
        self.assertIn("掉落来源", exclude)

    def test_synthetic_regions_are_separated(self):
        html = '''<h1>测试传奇</h1><div class="card ui_item popupItem">
        <span data-modifier-id="1">主体效果</span><div class="fst-italic">背景故事</div></div>
        <div class="card ui_item"><div class="card-header" data-i18n="hyperlink|name|30001">Corroded</div>
        <span data-modifier-id="2">已侵蚀效果</span></div>
        <div class="card"><div data-i18n="TextTable_GameFunc|value|Func_Tips_DropSource">Drop</div></div>'''
        result = inspect_legendary_html(html)
        self.assertEqual(["主体效果"], result["main_effect_examples"])
        self.assertEqual(["已侵蚀效果"], result["corrosion_effect_examples"])
        self.assertEqual(["背景故事"], result["lore_examples"])
        self.assertEqual(1, result["drop_source_section_count"])


if __name__ == "__main__":
    unittest.main()
