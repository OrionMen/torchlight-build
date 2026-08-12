import re
import unittest
from pathlib import Path

from crawler.generate_entity_index_v3 import (
    _MemoryAffixParser,
    build_entity_index_v3,
    memory_system_entity_v1_report,
)


ROOT = Path(__file__).resolve().parents[2]


class MemorySystemEntityV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, _ = build_entity_index_v3(ROOT)
        cls.report = memory_system_entity_v1_report(cls.index)
        cls.by_route = {
            entity["canonical_route"]: entity for entity in cls.index["entities"]
        }
        cls.entity = cls.by_route["/cn/Hero_Memories/"]

    def test_single_memory_system_entity_is_created(self):
        self.assertTrue(self.report["entity_created"])
        self.assertEqual("tlidb:cn:Hero_Memories", self.entity["entity_id"])
        self.assertEqual("memory_system", self.entity["entity_type"])
        self.assertNotIn("/cn/Memory_Revival/", self.by_route)

    def test_memory_category_and_sources(self):
        self.assertEqual("追忆", self.entity["content_category_name_zh"])
        self.assertEqual("英雄追忆", self.entity["content_subcategory_name_zh"])
        self.assertEqual(
            [
                {"source_type": "hero_memory", "role": "base_memory_affixes"},
                {"source_type": "revival", "role": "revival_affixes"},
            ],
            self.entity["sources"],
        )

    def test_hero_memory_and_revival_content_are_merged(self):
        summary = self.entity["clean_summary"]
        for label in (
            "基础属性", "固有词缀", "随机词缀", "普通复苏词缀", "复苏词缀（月相）"
        ):
            self.assertIn(label, summary)
        self.assertEqual(15, self.entity["base_attribute_count"])
        self.assertEqual(228, self.entity["fixed_affix_count"])
        self.assertEqual(432, self.entity["random_affix_count"])
        self.assertEqual(36, self.entity["revival_affix_count"])
        self.assertEqual(44, self.entity["moon_affix_count"])

    def test_clean_summary_excludes_page_and_table_noise(self):
        summary = self.entity["clean_summary"]
        self.assertNotIn("Item /", summary)
        self.assertNotIn("追忆复苏材料", summary)
        self.assertNotIn("data-modifier-id", summary)
        self.assertNotIn("Tier", summary)
        self.assertNotIn("Weight", summary)
        self.assertNotIn("document.ready", summary)
        self.assertFalse(re.search(r"\.(?:webp|png)|/cache/", summary, re.I))

    def test_each_source_is_restricted_to_its_approved_dom_sections(self):
        hero = _MemoryAffixParser(("基础属性", "固有词缀", "随机词缀"))
        hero.feed((
            ROOT / "data/raw/manifests/inventory/raw_html/Hero_Memories.html"
        ).read_text(encoding="utf-8"))
        revival = _MemoryAffixParser(("复苏词缀", "复苏词缀（月相）"))
        revival.feed((
            ROOT / "data/raw/manifests/help/raw_html/Memory_Revival.html"
        ).read_text(encoding="utf-8"))
        self.assertEqual({"基础属性", "固有词缀", "随机词缀"}, set(hero.affixes))
        self.assertEqual({"复苏词缀", "复苏词缀（月相）"}, set(revival.affixes))
        self.assertEqual([15, 228, 432], [len(hero.affixes[key]) for key in hero.affixes])
        self.assertEqual([36, 44], [len(revival.affixes[key]) for key in revival.affixes])
        approved_text = " ".join(
            value
            for parser in (hero, revival)
            for values in parser.affixes.values()
            for value in values
        )
        self.assertNotIn("黑炎计划", approved_text)
        self.assertNotIn("九夜星光", approved_text)


if __name__ == "__main__":
    unittest.main()
