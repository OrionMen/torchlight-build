import json
import re
import unittest
from pathlib import Path

from crawler.build_full_wiki_mirror import entity_fields_for_route, load_entity_index
from crawler.generate_entity_index_v3 import ORDINARY_EQUIPMENT_IDS


ROOT = Path(__file__).resolve().parents[2]
INDEX_PATH = ROOT / "data/generated/entity-index-v3.json"


class EntityPresentationV3Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        cls.by_id = {entity["entity_id"]: entity for entity in cls.index["entities"]}

    def test_chinese_titles_from_page_or_manifest(self):
        self.assertEqual("手枪", self.by_id["tlidb:cn:Pistol"]["entity_title_zh"])
        self.assertEqual("戒指", self.by_id["tlidb:cn:Ring"]["entity_title_zh"])
        self.assertEqual("神格石板", self.by_id["tlidb:cn:Divinity_Slate"]["entity_title_zh"])

    def test_directory_entity_is_hidden(self):
        self.assertEqual("hidden", self.by_id["tlidb:cn:Active_Skill"]["entity_visibility"])

    def test_regular_skill_is_visible(self):
        entity = next(
            item
            for item in self.index["entities"]
            if item.get("content_category_id") == "skill"
            and item["canonical_route"] != "/cn/Active_Skill/"
            and item["confidence"] == "primary"
        )
        self.assertEqual("visible", entity["entity_visibility"])

    def test_clean_summary_has_no_internal_debug_tokens(self):
        for entity_id in ("tlidb:cn:Pistol", "tlidb:cn:Active_Skill"):
            summary = self.by_id[entity_id]["clean_summary"]
            self.assertNotRegex(summary, re.compile(r"Info\s+id|Show Description|Tier name|\bDetails\b|\bSimple\b|\bAlts\b", re.I))

    def test_english_fallback_is_preserved_without_chinese_evidence(self):
        entity = self.by_id["tlidb:cn:Overrealm_Season"]
        self.assertEqual("Overrealm_Season", entity["entity_title_zh"])

    def test_schema_and_required_fields(self):
        self.assertEqual(3, self.index["schema_version"])
        required = {"entity_title_zh", "entity_visibility", "clean_summary"}
        self.assertTrue(all(required <= set(entity) for entity in self.index["entities"]))

    def test_search_index_fields_prefer_v3_presentation(self):
        entities = load_entity_index(INDEX_PATH)
        fields = entity_fields_for_route("/cn/Pistol/", entities)
        self.assertEqual("手枪", fields["entity_title"])
        self.assertEqual("手枪", fields["entity_title_zh"])
        self.assertEqual("visible", fields["entity_visibility"])
        self.assertTrue(fields["clean_summary"])

    def test_all_reviewed_inventory_equipment_entities(self):
        equipment = [
            entity for entity in self.index["entities"]
            if entity.get("content_subcategory_id") == "equipment_craft"
        ]
        self.assertEqual(38, len(equipment))
        self.assertEqual(
            ORDINARY_EQUIPMENT_IDS,
            {entity["canonical_route"].removeprefix("/cn/").removesuffix("/") for entity in equipment},
        )
        for entity in equipment:
            self.assertEqual("visible", entity["entity_visibility"])
            self.assertEqual("equipment", entity["content_category_id"])
            self.assertEqual("装备", entity["content_category_name_zh"])
            self.assertEqual("equipment_craft", entity["content_subcategory_id"])
            self.assertEqual("打造装备", entity["content_subcategory_name_zh"])
            self.assertEqual([
                {"source_type": "inventory", "role": "base_equipment"},
                {"source_type": "craft", "role": "craft_affixes"},
            ], entity["sources"])

    def test_equipment_summary_excludes_craft_tables(self):
        for slug in ("STR_Helmet", "Belt", "Crossbow", "Ring"):
            entity = self.by_id[f"tlidb:cn:{slug}"]
            self.assertTrue(entity["entity_title_zh"])
            self.assertIn(entity["entity_title_zh"], entity["clean_summary"])
            self.assertIn("基础词缀", entity["clean_summary"])
            self.assertIn("打造词缀", entity["clean_summary"])
            self.assertNotRegex(entity["clean_summary"], re.compile(r"\bTier\b|\bWeight\b|\bLibrary\b", re.I))

    def test_spirit_ring_is_added_as_equipment(self):
        entity = self.by_id["tlidb:cn:Spirit_Ring"]
        self.assertEqual("灵戒", entity["entity_title_zh"])
        self.assertEqual("equipment", entity["entity_type"])
        self.assertEqual("打造装备", entity["content_subcategory_name_zh"])
        self.assertIn("基础词缀", entity["clean_summary"])
        self.assertIn("打造词缀", entity["clean_summary"])

    def test_strength_helmet_merges_base_and_craft_modifier_text(self):
        entity = self.by_id["tlidb:cn:STR_Helmet"]
        self.assertIn("+(54–74) 最大生命", entity["clean_summary"])
        self.assertIn("+(330–372) 最大生命", entity["clean_summary"])
        self.assertNotIn("Inventory", entity["clean_summary"])
        self.assertNotIn("Craft", entity["clean_summary"])
        self.assertNotIn("仓库", entity["clean_summary"])

    def test_inventory_and_craft_category_pages_are_hidden(self):
        self.assertEqual("hidden", self.by_id["tlidb:cn:Inventory"]["entity_visibility"])
        self.assertEqual("hidden", self.by_id["tlidb:cn:Craft"]["entity_visibility"])

    def test_craft_is_not_source_of_ordinary_equipment_entities(self):
        for slug in ORDINARY_EQUIPMENT_IDS:
            sources = self.by_id[f"tlidb:cn:{slug}"]["sources"]
            self.assertEqual("craft_affixes", next(
                source["role"] for source in sources if source["source_type"] == "craft"
            ))


if __name__ == "__main__":
    unittest.main()
