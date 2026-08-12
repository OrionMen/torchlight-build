import json
import unittest
from pathlib import Path

from crawler.build_full_wiki_mirror import (
    entity_fields_for_route,
    load_entity_index,
    load_game_content_tree,
    resolve_content_tree_classification,
    search_entity_v2_integration_report,
)


ROOT = Path(__file__).resolve().parents[2]


class SearchEntityV2IntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entities = load_entity_index(ROOT / "data/generated/entity-index-v2.json")
        cls.tree = load_game_content_tree(ROOT / "config/game_content_tree.json")

    def classification(self, route, system_id):
        fields = entity_fields_for_route(route, self.entities)
        content, source = resolve_content_tree_classification(
            {"route": route, "system_id": system_id}, self.entities, self.tree
        )
        return fields, content, source

    def test_entity_v2_loading_and_schema(self):
        raw = json.loads((ROOT / "data/generated/entity-index-v2.json").read_text(encoding="utf-8"))
        self.assertEqual(2, raw["schema_version"])
        self.assertEqual(1635, len(raw["entities"]))
        self.assertEqual(1635, len(self.entities))

    def test_belt_matches_equipment_type_entity(self):
        entity, content, source = self.classification("/cn/Belt/", "inventory")
        self.assertEqual("tlidb:cn:Belt", entity["entity_id"])
        self.assertEqual("primary", entity["entity_confidence"])
        self.assertEqual("equipment", content["content_category_id"])
        self.assertEqual("equipment_type", content["content_subcategory_id"])
        self.assertEqual("entity_override", source)

    def test_active_skill_uses_entity_category(self):
        entity, content, source = self.classification("/cn/Active_Skill/", "inventory")
        self.assertEqual("tlidb:cn:Active_Skill", entity["entity_id"])
        self.assertEqual("skill", content["content_category_id"])
        self.assertEqual("skill_active", content["content_subcategory_id"])
        self.assertEqual("entity_override", source)

    def test_divinity_slate_uses_entity_category(self):
        _, content, source = self.classification("/cn/Divinity_Slate/", "inventory")
        self.assertEqual("talent_board", content["content_category_id"])
        self.assertEqual("talent_divinity_slate", content["content_subcategory_id"])
        self.assertEqual("entity_override", source)

    def test_trinity_has_one_stable_entity(self):
        craft = entity_fields_for_route("/cn/Trinity/", self.entities)
        legendary = entity_fields_for_route("cn/Trinity/index.html", self.entities)
        self.assertEqual("tlidb:cn:Trinity", craft["entity_id"])
        self.assertEqual(craft["entity_id"], legendary["entity_id"])
        self.assertEqual("equipment", craft["entity_category"])

    def test_unknown_hidden_page_falls_back_without_entity(self):
        entity, content, source = self.classification("/cn/Unknown_Help_Only/", "help")
        self.assertTrue(all(value is None for value in entity.values()))
        self.assertIsNone(content["content_category_id"])
        self.assertEqual("null", source)

    def test_v2_report_schema_and_counts(self):
        search = json.loads((ROOT / "local_wiki/ss13/site/search-index.json").read_text(encoding="utf-8"))
        report = search_entity_v2_integration_report(search["pages"], self.entities)
        self.assertEqual(6, report["search_index_schema_version"])
        self.assertEqual(search["page_count"], report["total_entries"])
        self.assertEqual(
            report["total_entries"], report["entity_matched"] + report["unmatched"]
        )
        self.assertEqual(
            report["unique_entities"],
            report["primary_entities"] + report["high_entities"] + report["medium_entities"],
        )


if __name__ == "__main__":
    unittest.main()
