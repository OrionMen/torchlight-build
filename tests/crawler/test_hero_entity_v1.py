import re
import unittest
from pathlib import Path

from crawler.generate_entity_index_v3 import (
    build_entity_index_v3,
    hero_entity_v1_report,
)


ROOT = Path(__file__).resolve().parents[2]


class HeroEntityV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, _ = build_entity_index_v3(ROOT)
        cls.report = hero_entity_v1_report(cls.index)
        cls.by_id = {entity["entity_id"]: entity for entity in cls.index["entities"]}

    def test_twenty_seven_hero_entities_are_created(self):
        self.assertEqual(27, self.report["total_entities"])
        hero_entities = [
            entity for entity in self.index["entities"]
            if entity.get("entity_type") == "hero"
        ]
        self.assertEqual(27, len(hero_entities))

    def test_category_and_source_are_hero_trait(self):
        entity = self.by_id["tlidb:cn:Anger"]
        self.assertEqual("hero", entity["entity_type"])
        self.assertEqual("英雄", entity["content_category_name_zh"])
        self.assertEqual("英雄特性", entity["content_subcategory_name_zh"])
        self.assertEqual(
            [{"source_type": "hero", "role": "hero_trait"}],
            entity["sources"],
        )

    def test_hero_overview_is_not_generated(self):
        self.assertNotIn("tlidb:cn:Hero", self.by_id)
        self.assertEqual(["/cn/Hero/"], self.report["excluded_pages"])

    def test_clean_summary_contains_visible_hero_content(self):
        entity = self.by_id["tlidb:cn:Anger"]
        summary = entity["clean_summary"]
        self.assertTrue(summary)
        self.assertIn("狂人 雷恩", summary)
        self.assertIn("怒火", summary)
        self.assertIn("怒气", summary)
        self.assertGreater(entity["trait_effect_count"], 0)

    def test_clean_summary_excludes_ui_script_and_internal_noise(self):
        for slug in ("Anger", "Blasphemer", "Spacetime_Illusion"):
            summary = self.by_id[f"tlidb:cn:{slug}"]["clean_summary"]
            self.assertNotIn("技能商店", summary)
            self.assertNotIn("document.ready", summary)
            self.assertNotIn("filterClick", summary)
            self.assertNotIn("data-bs-", summary)
            self.assertFalse(re.search(r"(?:\.webp|\.png|data-hero|internal[_ -]?id)", summary, re.I))


if __name__ == "__main__":
    unittest.main()
