import json
import unittest
from pathlib import Path

from crawler.build_full_wiki_mirror import (
    ENTITY_FIELD_NAMES,
    entity_fields_for_route,
    load_entity_index,
    search_entity_integration_report,
)


REPO = Path(__file__).resolve().parents[2]


class SearchEntityIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entities = load_entity_index(REPO / "data/generated/entity-index.json")

    def test_trinity_multiple_sources_match_same_entity(self):
        legendary = entity_fields_for_route("cn/Trinity/", self.entities)
        craft = entity_fields_for_route("/cn/Trinity/index.html", self.entities)
        self.assertEqual("tlidb:cn:Trinity", legendary["entity_id"])
        self.assertEqual(legendary["entity_id"], craft["entity_id"])

    def test_craft_entity_category_is_equipment(self):
        fields = entity_fields_for_route("/cn/Trinity/", self.entities)
        self.assertEqual("equipment", fields["entity_category"])
        self.assertEqual("装备", fields["entity_category_name_zh"])

    def test_skill_entity_category_is_skill(self):
        fields = entity_fields_for_route("/cn/Aimed_Shot/", self.entities)
        self.assertEqual("skill", fields["entity_category"])

    def test_unmatched_route_has_null_entity_fields(self):
        fields = entity_fields_for_route("/cn/Definitely_Not_An_Entity/", self.entities)
        self.assertEqual(set(ENTITY_FIELD_NAMES), set(fields))
        self.assertTrue(all(value is None for value in fields.values()))

    def test_old_fields_are_preserved_when_entity_fields_are_added(self):
        page = {
            "title": "三相",
            "plain_text": "原搜索文本",
            "title_display": "三相",
            "summary_display": "原搜索摘要",
            "system_id": "craft",
            "system_name_zh": "词缀",
            "game_category": "equipment",
            "game_category_name_zh": "装备",
            "game_category_visibility": "primary",
        }
        original = dict(page)
        page.update(entity_fields_for_route("/cn/Trinity/", self.entities))
        self.assertTrue(all(page[key] == value for key, value in original.items()))

    def test_schema_version_and_report_counts(self):
        index = json.loads((REPO / "local_wiki/ss13/site/search-index.json").read_text(encoding="utf-8"))
        report = search_entity_integration_report(index["pages"], self.entities)
        self.assertEqual(4, report["search_index_schema_version"])
        self.assertEqual(index["page_count"], report["total_index_entries"])
        self.assertEqual(
            report["total_index_entries"],
            report["matched_entities"] + report["unmatched_entries"],
        )


if __name__ == "__main__":
    unittest.main()
