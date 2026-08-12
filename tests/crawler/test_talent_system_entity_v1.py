import re
import unittest
from pathlib import Path

from crawler.generate_entity_index_v3 import (
    build_entity_index_v3,
    talent_system_entity_v1_report,
)


ROOT = Path(__file__).resolve().parents[2]


class TalentSystemEntityV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, _ = build_entity_index_v3(ROOT)
        cls.report = talent_system_entity_v1_report(cls.index)
        cls.by_id = {entity["entity_id"]: entity for entity in cls.index["entities"]}

    def test_thirty_two_entities_and_categories(self):
        self.assertEqual(32, self.report["total_entities"])
        self.assertEqual(30, self.report["hero_talent_count"])
        self.assertEqual(1, self.report["new_god_count"])
        self.assertEqual(1, self.report["nether_king_count"])
        expected = {
            "God_of_Might": "英雄天赋",
            "New_God": "新神",
            "Nether_King": "冥王",
        }
        for slug, subcategory in expected.items():
            entity = self.by_id[f"tlidb:cn:{slug}"]
            self.assertEqual("talent", entity["entity_type"])
            self.assertEqual("天赋系统", entity["content_category_name_zh"])
            self.assertEqual(subcategory, entity["content_subcategory_name_zh"])
            self.assertEqual(f"/cn/{slug}/", entity["canonical_route"])

    def test_talent_overview_is_not_generated(self):
        self.assertNotIn("tlidb:cn:Talent", self.by_id)
        self.assertEqual(["/cn/Talent/"], self.report["excluded_pages"])

    def test_clean_summary_uses_current_talent_effects_without_cache_noise(self):
        entity = self.by_id["tlidb:cn:God_of_Might"]
        self.assertGreater(entity["talent_effect_count"], 0)
        self.assertIn("巨力之神", entity["clean_summary"])
        self.assertIn("攻击击中时", entity["clean_summary"])
        self.assertIn("攻击技能等级", entity["clean_summary"])
        self.assertNotIn("ProfessionTree", entity["clean_summary"])
        self.assertNotIn("_cache-", entity["clean_summary"])
        self.assertNotIn("Item /", entity["clean_summary"])
        self.assertFalse(re.search(r"data-talent-id|TalentIcon|\.webp", entity["clean_summary"]))


if __name__ == "__main__":
    unittest.main()
