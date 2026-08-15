import json
import unittest
from pathlib import Path

from crawler.build_full_wiki_mirror import (
    load_entity_index,
    load_game_content_tree,
    resolve_content_tree_classification,
)


ROOT = Path(__file__).resolve().parents[2]
INDEX_PATH = ROOT / "data/generated/entity-index-v3.json"


class PactFateEntityClassificationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        cls.entities = load_entity_index(INDEX_PATH)
        cls.tree = load_game_content_tree(ROOT / "config/game_content_tree.json")

    def test_all_pact_entities_have_type_and_category(self):
        entities = [
            entity for entity in self.index["entities"]
            if any(
                source.get("system_id") == "pactspirit"
                for source in entity.get("sources", [])
            )
        ]
        self.assertEqual(175, len(entities))
        for entity in entities:
            self.assertEqual("pact_spirit", entity["entity_type"])
            self.assertEqual("pact_spirit", entity["content_category_id"])
            self.assertEqual("pact_spirit_entity", entity["content_subcategory_id"])

    def test_all_fate_entities_have_type_and_category(self):
        entities = [
            entity for entity in self.index["entities"]
            if entity.get("entity_type") == "fate"
        ]
        self.assertEqual(193, len(entities))
        for entity in entities:
            self.assertEqual("fate", entity["entity_type"])
            self.assertEqual("pact_spirit", entity["content_category_id"])
            self.assertEqual("pact_spirit_destiny", entity["content_subcategory_id"])

    def test_undetermined_fate_is_not_equipment(self):
        entity = self.entities["/cn/Undetermined_Fate/"]
        self.assertEqual("fate", entity["entity_type"])
        self.assertEqual("pact_spirit", entity["content_category_id"])
        self.assertEqual("pact_spirit_destiny", entity["content_subcategory_id"])

    def test_recovered_micro_fate_routes_use_destiny_classification(self):
        for slug in (
            "Micro_Fate:_Deterioration_Duration",
            "Micro_Fate:_Trauma_Damage_Mitigation",
        ):
            classification, source = resolve_content_tree_classification(
                {
                    "route": f"/cn/{slug}/",
                    "system_id": "recovered_internal_pages",
                },
                self.entities,
                self.tree,
            )
            self.assertEqual("entity_override", source)
            self.assertEqual("pact_spirit", classification["content_category_id"])
            self.assertEqual(
                "pact_spirit_destiny",
                classification["content_subcategory_id"],
            )


if __name__ == "__main__":
    unittest.main()
