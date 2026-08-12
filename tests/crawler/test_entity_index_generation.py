import json
import unittest
from pathlib import Path

from crawler.generate_entity_index import entity_id_from_route


REPO = Path(__file__).resolve().parents[2]
INDEX_PATH = REPO / "data/generated/entity-index.json"
REPORT_PATH = REPO / "data/reports/local-wiki/entity-index-generation-report.json"


class EntityIndexGenerationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        cls.report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        cls.by_route = {entity["canonical_route"]: entity for entity in cls.index["entities"]}

    def test_schema_and_counts(self):
        self.assertEqual(1, self.index["schema_version"])
        self.assertEqual(494, len(self.index["entities"]))
        self.assertEqual(428, self.report["high_confidence_count"])
        self.assertEqual(66, self.report["medium_a_count"])
        self.assertEqual(4, self.report["skipped_medium_b_count"])

    def test_trinity_entity_and_multiple_sources(self):
        entity = self.by_route["/cn/Trinity/"]
        self.assertEqual("tlidb:cn:Trinity", entity["entity_id"])
        self.assertEqual("三相", entity["title"])
        self.assertEqual(
            {"legendary_gear", "craft", "hyperlink"},
            {source["system_id"] for source in entity["sources"]},
        )

    def test_hyperlink_role_and_category_inheritance(self):
        entity = self.by_route["/cn/Trinity/"]
        hyperlink = next(source for source in entity["sources"] if source["system_id"] == "hyperlink")
        self.assertEqual("secondary", hyperlink["role"])
        self.assertEqual("equipment", entity["category"])
        self.assertEqual("装备", entity["category_name_zh"])

    def test_medium_b_is_not_generated(self):
        skipped = {item["canonical_route"] for item in self.report["skipped_medium_b"]}
        self.assertTrue(skipped)
        self.assertTrue(skipped.isdisjoint(self.by_route))

    def test_entity_id_is_stable_and_semantic(self):
        self.assertEqual("tlidb:cn:Trinity", entity_id_from_route("/cn/Trinity/"))
        self.assertEqual(
            "tlidb:cn:Micro_Fate:_Trauma",
            entity_id_from_route("/cn/Micro_Fate%3A_Trauma/"),
        )

    def test_entity_schema(self):
        required = {
            "entity_id", "title", "canonical_route", "category",
            "category_name_zh", "sources", "confidence",
        }
        self.assertTrue(all(required <= set(entity) for entity in self.index["entities"]))
        self.assertEqual(
            len(self.index["entities"]),
            len({entity["entity_id"] for entity in self.index["entities"]}),
        )


if __name__ == "__main__":
    unittest.main()
