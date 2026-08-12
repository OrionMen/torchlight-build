import re
import unittest
from pathlib import Path

from crawler.audit_vorax_equipment_v1 import VORAX_ENTITY_IDS
from crawler.generate_entity_index_v3 import (
    build_entity_index_v3,
    vorax_equipment_entity_v1_report,
)


ROOT = Path(__file__).resolve().parents[2]


class VoraxEquipmentEntityV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, _ = build_entity_index_v3(ROOT)
        cls.report = vorax_equipment_entity_v1_report(ROOT, cls.index)
        cls.by_id = {entity["entity_id"]: entity for entity in cls.index["entities"]}

    def test_ten_entities_are_updated_without_duplicates(self):
        entities = [self.by_id[f"tlidb:cn:{slug}"] for slug in VORAX_ENTITY_IDS]
        self.assertEqual(10, len(entities))
        self.assertEqual(10, self.report["total_entities"])
        self.assertEqual(0, self.report["created"])
        self.assertEqual(10, self.report["updated"])

    def test_category_type_visibility_and_source(self):
        entity = self.by_id["tlidb:cn:Vorax_Limb:_Head"]
        self.assertEqual("渴瘾肢体：脑部", entity["entity_title_zh"])
        self.assertEqual("equipment", entity["entity_type"])
        self.assertEqual("装备", entity["content_category_name_zh"])
        self.assertEqual("渴瘾装备", entity["content_subcategory_name_zh"])
        self.assertEqual("visible", entity["entity_visibility"])
        self.assertEqual([{"source_type": "vorax", "role": "equipment_data"}], entity["sources"])

    def test_all_three_data_regions_are_in_clean_summary(self):
        for slug in (
            "Vorax_Limb:_Head", "Vorax_Limb:_Legs", "Vorax_Aberrant_Limb:_Digits"
        ):
            summary = self.by_id[f"tlidb:cn:{slug}"]["clean_summary"]
            self.assertIn("基础词缀", summary)
            self.assertIn("打造词条", summary)
            self.assertIn("传奇品质", summary)

    def test_vorax_entities_use_plain_canonical_routes(self):
        for slug in VORAX_ENTITY_IDS:
            entity = self.by_id[f"tlidb:cn:{slug}"]
            self.assertNotIn("landing_anchor", entity)
            self.assertEqual(f"/cn/{slug}/", entity["canonical_route"])

    def test_inventory_category_page_remains_hidden_and_is_not_vorax(self):
        inventory = self.by_id["tlidb:cn:Inventory"]
        self.assertEqual("hidden", inventory["entity_visibility"])
        self.assertNotEqual("equipment_vorax", inventory.get("content_subcategory_id"))
        for excluded in self.report["excluded_pages"]:
            if f"tlidb:cn:{excluded}" in self.by_id:
                self.assertNotEqual(
                    "equipment_vorax",
                    self.by_id[f"tlidb:cn:{excluded}"].get("content_subcategory_id"),
                )

    def test_clean_summary_has_no_table_metadata(self):
        forbidden = re.compile(r"\b(?:Tier|Weight|Library)\b|\bid\s*:", re.I)
        for slug in VORAX_ENTITY_IDS:
            summary = self.by_id[f"tlidb:cn:{slug}"]["clean_summary"]
            self.assertNotRegex(summary, forbidden)
            self.assertNotIn("Inventory", summary)
            self.assertNotIn("仓库", summary)


if __name__ == "__main__":
    unittest.main()
