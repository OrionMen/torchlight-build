import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TREE_PATH = ROOT / "config/game_content_tree.json"


class GameContentTreeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = json.loads(TREE_PATH.read_text(encoding="utf-8"))
        cls.categories = {item["id"]: item for item in cls.tree["search_categories"]}
        cls.system_paths = {
            system_id: (category["name_zh"], child["name_zh"])
            for category in cls.tree["search_categories"]
            for child in category["children"]
            for system_id in child["systems"]
        }
        cls.hidden = {item["system_id"]: item for item in cls.tree["hidden_systems"]}

    def test_player_facing_system_paths(self):
        expected = {
            "hero": ("英雄", "英雄特性"),
            "boon": ("英雄", "追忆"),
            "craft": ("装备", "打造装备"),
            "active_skill": ("技能", "主动技能"),
            "talent": ("天赋系统", "英雄天赋"),
            "pactspirit": ("契灵系统", "契灵"),
            "destiny": ("契灵系统", "命运"),
        }
        for system_id, path in expected.items():
            self.assertEqual(path, self.system_paths[system_id])

    def test_hyperlink_is_hidden_not_search_category(self):
        self.assertIn("hyperlink", self.hidden)
        self.assertNotIn("hyperlink", self.system_paths)

    def test_schema_and_primary_categories(self):
        self.assertEqual(1, self.tree["schema_version"])
        self.assertEqual(
            [
                "hero", "memory", "equipment", "equipment_related", "skill",
                "talent_board", "pact_spirit",
            ],
            [item["id"] for item in self.tree["search_categories"]],
        )
        self.assertTrue(all(item["search_visibility"] == "primary" for item in self.tree["search_categories"]))

    def test_equipment_tree_has_entity_categories_without_inventory_fallback(self):
        children = {
            child["id"]: child
            for child in self.categories["equipment"]["children"]
        }
        self.assertEqual(
            {"equipment_craft", "equipment_legendary", "equipment_vorax"},
            set(children),
        )
        self.assertEqual("渴瘾装备", children["equipment_vorax"]["name_zh"])
        self.assertNotIn("inventory", self.system_paths)
        self.assertNotIn("equipment_type", children)

    def test_equipment_related_system_category_is_separate(self):
        children = {
            child["id"]: child
            for child in self.categories["equipment_related"]["children"]
        }
        self.assertEqual(
            {
                "equipment_related_fragrance",
                "equipment_related_tower_sequence",
            },
            set(children),
        )
        self.assertEqual("调香秘仪", children["equipment_related_fragrance"]["name_zh"])
        self.assertEqual("高塔序列", children["equipment_related_tower_sequence"]["name_zh"])

    def test_unique_category_child_and_system_ids(self):
        category_ids = [item["id"] for item in self.tree["search_categories"]]
        child_paths = [
            (category["id"], child["id"])
            for category in self.tree["search_categories"]
            for child in category["children"]
        ]
        systems = [
            system_id
            for category in self.tree["search_categories"]
            for child in category["children"]
            for system_id in child["systems"]
        ]
        self.assertEqual(len(category_ids), len(set(category_ids)))
        self.assertEqual(len(child_paths), len(set(child_paths)))
        self.assertEqual(len(systems), len(set(systems)))
        self.assertFalse(set(systems) & set(self.hidden))

    def test_memory_entity_category_is_separate_from_legacy_boon_path(self):
        legacy = next(
            child for child in self.categories["hero"]["children"]
            if child["id"] == "hero_memory"
        )
        memory = self.categories["memory"]
        child = next(
            child for child in memory["children"]
            if child["id"] == "hero_memory"
        )
        self.assertEqual("追忆", memory["name_zh"])
        self.assertEqual("英雄追忆", child["name_zh"])
        self.assertEqual(["boon"], legacy["systems"])
        self.assertEqual("hidden", legacy["search_visibility"])
        self.assertEqual([], child["systems"])
        self.assertNotEqual("hidden", child.get("search_visibility"))
        self.assertTrue(child.get("notes"))

    def test_ethereal_prism_system_mapping_is_documented(self):
        child = next(
            child
            for child in self.categories["talent_board"]["children"]
            if child["id"] == "talent_ethereal_prism"
        )
        self.assertEqual(["Ethereal_Prism"], child["systems"])
        self.assertTrue(child.get("notes"))

    def test_talent_system_has_only_final_four_subcategories(self):
        category = self.categories["talent_board"]
        self.assertEqual("天赋系统", category["name_zh"])
        children = {child["id"]: child for child in category["children"]}
        self.assertEqual(
            {
                "talent_hero",
                "talent_new_god",
                "talent_nether_king_entity",
                "talent_ethereal_prism",
            },
            set(children),
        )
        self.assertEqual(
            ["英雄天赋", "新神", "冥王", "异度棱镜"],
            [child["name_zh"] for child in category["children"]],
        )
        self.assertEqual("新神", children["talent_new_god"]["name_zh"])
        self.assertEqual("冥王", children["talent_nether_king_entity"]["name_zh"])
        self.assertEqual([], children["talent_new_god"]["systems"])
        self.assertEqual([], children["talent_nether_king_entity"]["systems"])
        self.assertNotIn("神格石板", [child["name_zh"] for child in category["children"]])
        self.assertNotIn("冥王神格", [child["name_zh"] for child in category["children"]])

    def test_hidden_system_schema(self):
        expected = {
            "hyperlink", "help", "tip", "codex", "drop_source", "compass",
            "season_compass", "netherrealm", "void_chart", "path_of_the_brave",
            "probe", "commodity", "corrosion", "candidate_gear_empowerment",
            "candidate_outfit", "recovered_internal_pages",
        }
        self.assertEqual(expected, set(self.hidden))
        self.assertTrue(all(item.get("reason") for item in self.tree["hidden_systems"]))


if __name__ == "__main__":
    unittest.main()
