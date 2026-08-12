import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAPPING_PATH = ROOT / "config/game_category_mapping.json"
SYSTEM_MANIFEST_PATH = ROOT / "sources/system_manifest.json"


class GameCategoryMappingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
        cls.categories = {item["id"]: item for item in cls.mapping["categories"]}
        cls.system_to_category = {
            system_id: category
            for category in cls.mapping["categories"]
            for system_id in category["systems"]
        }
        cls.uncategorized = {
            item["system_id"]: item for item in cls.mapping["uncategorized"]
        }

    def test_confirmed_category_mappings(self):
        expected = {
            "hero": ("hero", "英雄"),
            "craft": ("equipment", "装备"),
            "active_skill": ("skill", "技能"),
            "talent": ("talent_board", "天赋石板"),
            "pactspirit": ("pact_spirit", "契灵"),
        }
        for system_id, (category_id, name_zh) in expected.items():
            category = self.system_to_category[system_id]
            self.assertEqual(category["id"], category_id)
            self.assertEqual(category["name_zh"], name_zh)

    def test_deferred_systems_are_not_primary_categories(self):
        for system_id in ("hyperlink", "recovered_internal_pages", "destiny"):
            self.assertNotIn(system_id, self.system_to_category)
            self.assertIn(system_id, self.uncategorized)
        self.assertNotIn("destiny", self.categories["memory"]["systems"])

    def test_schema_and_complete_system_coverage(self):
        self.assertEqual(self.mapping["schema_version"], 1)
        self.assertEqual(len(self.categories), len(self.mapping["categories"]))
        mapped = list(self.system_to_category)
        self.assertEqual(len(mapped), len(set(mapped)))
        self.assertFalse(set(mapped) & set(self.uncategorized))
        for category in self.mapping["categories"]:
            self.assertIsInstance(category["name_zh"], str)
            self.assertIn(category["search_visibility"], {"primary", "secondary", "hidden"})
            self.assertIn(category["confidence"], {"high", "medium", "low", "unassigned"})
            self.assertIsInstance(category["systems"], list)
        for item in self.mapping["uncategorized"]:
            self.assertTrue(item["system_id"])
            self.assertTrue(item["reason"])

        official = json.loads(SYSTEM_MANIFEST_PATH.read_text(encoding="utf-8"))
        expected_systems = {item["system_id"] for item in official["systems"]}
        expected_systems.add("recovered_internal_pages")
        self.assertEqual(set(mapped) | set(self.uncategorized), expected_systems)


if __name__ == "__main__":
    unittest.main()
