import unittest

from crawler.build_full_wiki_mirror import local_assets


class SearchContentTreeUITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assets = local_assets()
        cls.html = assets["_local/search/index.html"]
        cls.script = assets["_local/search/app.js"]

    def test_tree_is_loaded_and_rendered_dynamically(self):
        self.assertIn('<nav id="content-tree"', self.html)
        self.assertIn("fetch('game-content-tree.json')", self.script)
        self.assertIn("contentTree.search_categories", self.script)
        self.assertIn(
            "category.children.filter(child=>child.search_visibility!=='hidden').forEach",
            self.script,
        )
        self.assertNotIn("打造装备", self.script)
        self.assertNotIn("传奇装备", self.script)

    def test_primary_equipment_and_secondary_legendary_filters_use_v5_fields(self):
        self.assertIn("x.content_category_id===selectedCategory", self.script)
        self.assertIn("x.content_subcategory_id===selectedSubcategory", self.script)
        self.assertIn("selectFilter(category.id,child.id,button)", self.script)

    def test_parent_filter_uses_only_visible_full_paths(self):
        self.assertIn("const visibleSubcategories=categoryId=>new Set", self.script)
        self.assertIn(
            "if(selectedCategory)return x.content_category_id===selectedCategory&&visibleSubcategories(selectedCategory).has(x.content_subcategory_id)",
            self.script,
        )

        visible_children = {"hero_trait"}
        pages = [
            {"id": "Anger", "category": "hero", "subcategory": "hero_trait"},
            {"id": "Stars_of_Long_Night", "category": "hero", "subcategory": "hero_memory"},
            {"id": "Hero_Memories", "category": "memory", "subcategory": "hero_memory"},
        ]
        matched = [
            page["id"] for page in pages
            if page["category"] == "hero" and page["subcategory"] in visible_children
        ]
        self.assertEqual(["Anger"], matched)

    def test_subcategory_filter_also_matches_parent_category(self):
        self.assertIn(
            "if(selectedSubcategory)return x.content_category_id===selectedCategory&&x.content_subcategory_id===selectedSubcategory",
            self.script,
        )
        pages = [
            {
                "id": "Hero_Memories",
                "content_category_id": "memory",
                "content_subcategory_id": "hero_memory",
            },
            {
                "id": "Project_Black_Fire",
                "content_category_id": "hero",
                "content_subcategory_id": "hero_memory",
            },
            {
                "id": "Stars_of_Long_Night",
                "content_category_id": "hero",
                "content_subcategory_id": "hero_memory",
            },
        ]

        def matches(page, category, subcategory):
            return (
                page["content_category_id"] == category
                and page["content_subcategory_id"] == subcategory
            )

        memory = [
            page["id"] for page in pages
            if matches(page, "memory", "hero_memory")
        ]
        boon = [
            page["id"] for page in pages
            if matches(page, "hero", "hero_memory")
        ]
        self.assertEqual(["Hero_Memories"], memory)
        self.assertEqual(["Project_Black_Fire", "Stars_of_Long_Night"], boon)

    def test_legacy_boon_child_is_hidden_but_memory_child_is_visible(self):
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        tree = json.loads(
            (root / "config/game_content_tree.json").read_text(encoding="utf-8")
        )
        categories = {item["id"]: item for item in tree["search_categories"]}
        legacy = next(
            child for child in categories["hero"]["children"]
            if child["id"] == "hero_memory"
        )
        memory = next(
            child for child in categories["memory"]["children"]
            if child["id"] == "hero_memory"
        )
        self.assertEqual(["boon"], legacy["systems"])
        self.assertEqual("hidden", legacy["search_visibility"])
        self.assertEqual("英雄追忆", memory["name_zh"])
        self.assertNotEqual("hidden", memory.get("search_visibility"))

    def test_skill_hero_and_pact_filters_are_config_driven(self):
        self.assertIn("category.name_zh", self.script)
        self.assertIn("child.name_zh", self.script)
        self.assertIn("category.search_visibility==='primary'", self.script)

    def test_hidden_systems_are_excluded_by_config(self):
        self.assertIn("contentTree.hidden_systems.map", self.script)
        self.assertIn("hiddenSystems.has(x.system_id)", self.script)
        self.assertIn("x.entity_visibility==='hidden'", self.script)

    def test_uncategorized_non_hidden_pages_remain_visible(self):
        self.assertIn(".has(x.content_subcategory_id);return true", self.script)

    def test_existing_search_matching_is_preserved(self):
        self.assertIn("const t=x.title.toLocaleLowerCase(),p=x.plain_text.toLocaleLowerCase()", self.script)
        self.assertIn("hi(displayTitle,k)", self.script)
        self.assertNotIn("matchesCategory", self.script)

    def test_results_group_by_content_subcategory_first(self):
        self.assertIn(
            "id:x.content_subcategory_id||x.content_category_id||x.system_id",
            self.script,
        )
        self.assertIn(
            "name:x.content_subcategory_name_zh||x.content_category_name_zh||x.system_name_zh||x.system_id",
            self.script,
        )

    def test_known_systems_receive_expected_group_names_from_tree(self):
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        tree = json.loads((root / "config/game_content_tree.json").read_text(encoding="utf-8"))
        groups = {
            system_id: child["name_zh"]
            for category in tree["search_categories"]
            for child in category["children"]
            for system_id in child["systems"]
        }
        self.assertEqual("主动技能", groups["active_skill"])
        self.assertEqual("传奇装备", groups["legendary_gear"])
        self.assertEqual("追忆", groups["boon"])
        self.assertEqual("命运", groups["destiny"])

    def test_unclassified_group_falls_back_to_system_name(self):
        self.assertIn("x.content_category_name_zh||x.system_name_zh||x.system_id", self.script)


if __name__ == "__main__":
    unittest.main()
