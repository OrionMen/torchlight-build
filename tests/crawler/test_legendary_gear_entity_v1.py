import unittest
from pathlib import Path

from crawler.generate_entity_index_v3 import (
    build_entity_index_v3,
    legendary_gear_entity_v1_report,
)


ROOT = Path(__file__).resolve().parents[2]


class LegendaryGearEntityV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, _ = build_entity_index_v3(ROOT)
        cls.report = legendary_gear_entity_v1_report(ROOT, cls.index)
        cls.by_id = {entity["entity_id"]: entity for entity in cls.index["entities"]}

    def test_exactly_267_legendary_entities(self):
        self.assertEqual(267, self.report["total_entities"])
        self.assertEqual(7, self.report["excluded_non_equipment"])
        self.assertEqual(65, self.report["skipped_empty"])
        self.assertEqual(267, self.report["corrosion_enriched"])

    def test_thunder_prosthetics_includes_effects_and_corrosion_not_lore(self):
        entity = self.by_id["tlidb:cn:Thunder_Channeling_Prosthetics"]
        self.assertIn("触发一次 15 级闪电链", entity["clean_summary"])
        self.assertIn("触发一次 15 级电火花", entity["clean_summary"])
        self.assertIn("触发一次 20 级闪电链", entity["clean_summary"])
        self.assertNotIn("矮人族的祖先玛格努斯", entity["clean_summary"])

    def test_category_visibility_type_and_sources(self):
        entity = self.by_id["tlidb:cn:Crosser"]
        self.assertEqual("equipment", entity["entity_type"])
        self.assertEqual("装备", entity["content_category_name_zh"])
        self.assertEqual("传奇装备", entity["content_subcategory_name_zh"])
        self.assertEqual("visible", entity["entity_visibility"])
        self.assertEqual([
            {"source_type": "legendary_gear", "role": "main_effect"},
            {"source_type": "corrosion", "role": "corrosion"},
        ], entity["sources"])

    def test_non_equipment_and_empty_snapshots_are_absent(self):
        self.assertNotIn("tlidb:cn:Sparks_of_Moth_Fire", self.by_id)
        self.assertNotIn("tlidb:cn:Frozen_Flame", self.by_id)

    def test_required_examples_are_present(self):
        for slug in (
            "Crosser", "Frozen_Sight", "Glorious_Journey",
            "Omniscient_Prototype", "Awaiting",
        ):
            self.assertIn(f"tlidb:cn:{slug}", self.by_id)


if __name__ == "__main__":
    unittest.main()
