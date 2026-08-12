import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
V1_PATH = ROOT / "data/generated/entity-index.json"
V2_PATH = ROOT / "data/generated/entity-index-v2.json"
REPORT_PATH = ROOT / "data/reports/local-wiki/entity-index-v2-generation-report.json"


class EntityIndexV2GenerationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v1 = json.loads(V1_PATH.read_text(encoding="utf-8"))
        cls.v2 = json.loads(V2_PATH.read_text(encoding="utf-8"))
        cls.report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        cls.by_id = {entity["entity_id"]: entity for entity in cls.v2["entities"]}

    def test_old_entity_identity_sources_and_confidence_are_preserved(self):
        old = next(entity for entity in self.v1["entities"] if entity["entity_id"] == "tlidb:cn:Trinity")
        new = self.by_id[old["entity_id"]]
        self.assertEqual(old["canonical_route"], new["canonical_route"])
        self.assertEqual(old["sources"], new["sources"])
        self.assertEqual(old["confidence"], new["confidence"])

    def test_inventory_entity_is_added_with_stable_id_and_category(self):
        belt = self.by_id["tlidb:cn:Belt"]
        self.assertEqual("Belt", belt["title"])
        self.assertEqual("/cn/Belt/", belt["canonical_route"])
        self.assertEqual("equipment", belt["content_category_id"])
        self.assertEqual("equipment_type", belt["content_subcategory_id"])
        self.assertEqual([{"system_id": "inventory", "role": "primary"}], belt["sources"])
        self.assertEqual("primary", belt["confidence"])

    def test_skill_entity_is_added(self):
        skill_systems = {
            "active_skill", "support_skill", "passive_skill", "activation_medium_skill",
            "magnificent_support_skill", "noble_support_skill", "modularization_skill",
        }
        entity = next(
            item
            for item in self.v2["entities"]
            if item["confidence"] == "primary"
            and item["sources"][0]["system_id"] in skill_systems
        )
        self.assertEqual("skill", entity["content_category_id"])

    def test_hidden_system_does_not_create_primary_entity(self):
        hidden = {
            "hyperlink", "help", "tip", "codex", "drop_source", "compass",
            "season_compass", "netherrealm", "void_chart", "path_of_the_brave",
            "probe", "commodity", "corrosion", "recovered_internal_pages",
        }
        primary_systems = {
            entity["sources"][0]["system_id"]
            for entity in self.v2["entities"]
            if entity["confidence"] == "primary"
        }
        self.assertFalse(hidden & primary_systems)

    def test_schema_counts_and_unique_identity(self):
        self.assertEqual(2, self.v2["schema_version"])
        self.assertEqual(1635, len(self.v2["entities"]))
        self.assertEqual(494, self.report["old_entities"])
        self.assertEqual(1141, self.report["new_primary_entities"])
        self.assertEqual(0, self.report["duplicate_entity_ids"])
        self.assertEqual(0, self.report["duplicate_canonical_routes"])
        self.assertEqual(
            len(self.v2["entities"]),
            len({entity["entity_id"] for entity in self.v2["entities"]}),
        )

    def test_every_entity_has_v2_fields(self):
        required = {
            "entity_id", "title", "canonical_route", "content_category_id",
            "content_category_name_zh", "content_subcategory_id",
            "content_subcategory_name_zh", "sources", "confidence",
        }
        self.assertTrue(all(required <= set(entity) for entity in self.v2["entities"]))


if __name__ == "__main__":
    unittest.main()
