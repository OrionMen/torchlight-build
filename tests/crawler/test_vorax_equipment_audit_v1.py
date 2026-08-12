import unittest
from pathlib import Path

from crawler.audit_vorax_equipment_v1 import build_audit, inspect_vorax_html


ROOT = Path(__file__).resolve().parents[2]


class VoraxEquipmentAuditV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = build_audit(ROOT)
        cls.by_id = {item["id"]: item for item in cls.report["entities"]}

    def test_all_ten_vorax_entities_are_identified(self):
        self.assertEqual(10, len(self.report["entities"]))
        self.assertEqual(10, self.report["summary"]["confirmed_entities"])
        self.assertTrue(all(item["classification"] == "vorax_entity"
                            for item in self.report["entities"]))

    def test_inventory_is_a_hidden_category_page(self):
        category = self.report["category_pages"][0]
        self.assertEqual("category_page", category["classification"])
        self.assertEqual("装备类型", category["display_role"])
        self.assertEqual("hidden", category["search_visibility_recommendation"])
        self.assertEqual(10, category["vorax_link_count"])

    def test_all_three_data_layers_are_present(self):
        for entity in self.report["entities"]:
            self.assertGreater(entity["base_affix_modifier_count"], 0)
            self.assertGreater(entity["craft_affix_modifier_count"], 0)
            self.assertGreater(entity["legendary_quality_item_count"], 0)

    def test_focus_cases_have_chinese_entity_titles(self):
        self.assertEqual("渴瘾肢体：脑部", self.by_id["Vorax_Limb:_Head"]["title"])
        self.assertEqual("渴瘾肢体：腿部", self.by_id["Vorax_Limb:_Legs"]["title"])
        self.assertEqual("渴瘾异肢：指部", self.by_id["Vorax_Aberrant_Limb:_Digits"]["title"])

    def test_search_recommendation(self):
        recommendation = self.report["search_recommendation"]
        self.assertEqual(["装备名称", "基础词缀", "打造词条", "传奇品质"], recommendation["include"])
        self.assertIn("Tier/Weight", recommendation["exclude"])
        self.assertIn("数据表", recommendation["exclude"])

    def test_minimal_dom_section_detection(self):
        html = '''<div class="tab-pane" id="打造"><table><tr><td data-modifier-id="c">词条</td></tr></table></div>
        <div class="tab-pane" id="传奇品质"><a data-hover="x" href="Legend">传奇</a></div>
        <div class="tab-pane" id="基础词缀"><table><tr><td data-modifier-id="b">基础</td></tr></table></div>
        <div class="tab-pane" id="渴瘾肢体：脑部"><h1>渴瘾肢体：脑部</h1><div class="popupItem"></div></div>'''
        result = inspect_vorax_html(html)
        self.assertEqual(1, result["base_affix_modifier_count"])
        self.assertEqual(1, result["craft_affix_modifier_count"])
        self.assertEqual(1, result["legendary_quality_item_count"])
        self.assertEqual(1, result["current_entity_card_count"])


if __name__ == "__main__":
    unittest.main()
