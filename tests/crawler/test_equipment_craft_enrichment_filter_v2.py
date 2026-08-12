import json
import unittest
from pathlib import Path

from crawler.build_full_wiki_mirror import (
    load_entity_index,
    load_game_content_tree,
    resolve_content_tree_classification,
)
from crawler.generate_entity_index_v3 import equipment_craft_enrichment_filter_v2_report


ROOT = Path(__file__).resolve().parents[2]


class EquipmentCraftEnrichmentFilterV2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = json.loads(
            (ROOT / "data/generated/entity-index-v3.json").read_text(encoding="utf-8")
        )
        cls.by_id = {entity["entity_id"]: entity for entity in cls.index["entities"]}
        cls.report = equipment_craft_enrichment_filter_v2_report(ROOT, cls.index)

    def test_all_38_equipment_entities_remain(self):
        self.assertEqual(38, self.report["total_equipment_entities"])
        self.assertEqual(38, len(self.report["accepted_craft_sources"]))

    def test_strength_helmet_and_belt_have_filtered_craft_sources(self):
        for slug in ("STR_Helmet", "Belt", "Crossbow"):
            entity = self.by_id[f"tlidb:cn:{slug}"]
            self.assertEqual("craft_affixes", next(
                source["role"] for source in entity["sources"]
                if source["source_type"] == "craft"
            ))
            self.assertIn("打造词缀", entity["clean_summary"])

    def test_memory_craft_pages_are_rejected(self):
        rejected = {item["id"] for item in self.report["rejected_craft_sources"]}
        self.assertTrue({
            "Memory_of_Origin", "Memory_of_Progress", "Memory_of_Discipline"
        } <= rejected)

    def test_equipment_summaries_have_no_memory_text(self):
        forbidden = ("本源的追忆", "奋进的追忆", "守己的追忆")
        equipment = [
            entity for entity in self.index["entities"]
            if entity.get("entity_type") == "equipment"
        ]
        self.assertTrue(all(
            not any(value in entity["clean_summary"] for value in forbidden)
            for entity in equipment
        ))
        self.assertEqual(0, self.report["summary"]["equipment_summaries_with_rejected_memory_text"])

    def test_equipment_category_is_unchanged(self):
        for slug in ("STR_Helmet", "Belt", "Spirit_Ring", "Crossbow"):
            entity = self.by_id[f"tlidb:cn:{slug}"]
            self.assertEqual("equipment", entity["content_category_id"])
            self.assertEqual("equipment_craft", entity["content_subcategory_id"])

    def test_unmatched_craft_page_has_no_equipment_classification(self):
        entities = load_entity_index(ROOT / "data/generated/entity-index-v3.json")
        tree = load_game_content_tree(ROOT / "config/game_content_tree.json")
        fields, source = resolve_content_tree_classification(
            {"system_id": "craft", "route": "/cn/Memory_of_Origin/"},
            entities,
            tree,
        )
        self.assertEqual("craft_rejected", source)
        self.assertIsNone(fields["content_category_id"])
        self.assertIsNone(fields["content_subcategory_id"])


if __name__ == "__main__":
    unittest.main()
