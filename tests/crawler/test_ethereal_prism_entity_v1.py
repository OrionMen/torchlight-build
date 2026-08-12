import unittest
from pathlib import Path

from crawler.generate_entity_index_v3 import (
    build_entity_index_v3,
    ethereal_prism_entity_v1_report,
)


ROOT = Path(__file__).resolve().parents[2]


class EtherealPrismEntityV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, _ = build_entity_index_v3(ROOT)
        cls.report = ethereal_prism_entity_v1_report(ROOT, cls.index)
        cls.by_id = {
            entity["entity_id"]: entity for entity in cls.index["entities"]
        }

    def test_system_entity_is_created_with_talent_classification(self):
        entity = self.by_id["tlidb:cn:Ethereal_Prism"]
        self.assertTrue(self.report["entity_created"])
        self.assertEqual("talent_system", entity["entity_type"])
        self.assertEqual("天赋系统", entity["content_category_name_zh"])
        self.assertEqual("异度棱镜", entity["content_subcategory_name_zh"])
        self.assertEqual("/cn/Ethereal_Prism/", entity["canonical_route"])
        self.assertEqual(
            [{"source_type": "ethereal_prism", "role": "system_data"}],
            entity["sources"],
        )

    def test_both_affix_sections_enter_clean_summary(self):
        entity = self.by_id["tlidb:cn:Ethereal_Prism"]
        self.assertEqual(33, entity["base_affix_count"])
        self.assertEqual(358, entity["random_affix_count"])
        self.assertIn("基础词缀", entity["clean_summary"])
        self.assertIn("随机词缀", entity["clean_summary"])
        self.assertIn("影响范围扩大至 3 × 3 矩形", entity["clean_summary"])

    def test_item_pages_and_ui_noise_are_not_generated_or_indexed(self):
        entity = self.by_id["tlidb:cn:Ethereal_Prism"]
        prism_entities = [
            item for item in self.index["entities"]
            if item["entity_id"].startswith("tlidb:cn:Ethereal_Prism:")
        ]
        self.assertEqual([], prism_entities)
        self.assertEqual(24, self.report["excluded_item_pages"])
        self.assertNotIn("Item /24", entity["clean_summary"])
        self.assertNotIn("data-modifier-id", entity["clean_summary"])
        self.assertNotIn("Calibrate_Ethereal_Prism", entity["clean_summary"])


if __name__ == "__main__":
    unittest.main()
