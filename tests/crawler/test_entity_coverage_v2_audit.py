import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "data/reports/local-wiki/entity-coverage-v2-audit.json"
ENTITY_INDEX_PATH = ROOT / "data/generated/entity-index.json"


class EntityCoverageV2AuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        cls.candidates = cls.report["candidate_entities"]

    def test_inventory_focus_objects_are_candidates(self):
        inventory_routes = {
            item["canonical_route"]
            for item in self.candidates
            if item["system_id"] == "inventory"
        }
        for slug in ("Belt", "Crossbow", "DEX_Boots"):
            self.assertIn(f"/cn/{slug}/", inventory_routes)

    def test_skill_candidate_is_included(self):
        skill_systems = {
            "active_skill", "support_skill", "passive_skill", "activation_medium_skill",
            "magnificent_support_skill", "noble_support_skill", "modularization_skill",
        }
        self.assertTrue(any(item["system_id"] in skill_systems for item in self.candidates))
        self.assertGreater(self.report["by_category"].get("skill", 0), 0)

    def test_talent_board_candidates_include_secondary_primary_systems(self):
        systems = {item["system_id"] for item in self.candidates}
        self.assertIn("path_of_progression", systems)
        self.assertIn("nether_kings_divinity", systems)
        self.assertGreater(self.report["by_category"].get("talent_board", 0), 0)

    def test_hidden_systems_are_excluded(self):
        hidden = {
            "hyperlink", "help", "tip", "codex", "drop_source", "compass",
            "season_compass", "netherrealm", "void_chart", "path_of_the_brave",
            "probe", "commodity", "corrosion",
        }
        self.assertFalse(hidden & {item["system_id"] for item in self.candidates})

    def test_existing_entity_is_not_duplicated(self):
        existing = json.loads(ENTITY_INDEX_PATH.read_text(encoding="utf-8"))
        existing_routes = {item["canonical_route"] for item in existing["entities"]}
        candidate_routes = {item["canonical_route"] for item in self.candidates}
        self.assertFalse(existing_routes & candidate_routes)
        self.assertEqual(len(candidate_routes), len(self.candidates))

    def test_schema_and_counts(self):
        self.assertEqual(1, self.report["schema_version"])
        self.assertEqual(494, self.report["current_entity_count"])
        self.assertEqual(
            self.report["projected_entity_count"],
            self.report["current_entity_count"] + self.report["new_entity_candidates"],
        )
        self.assertEqual(
            self.report["new_entity_candidates"],
            sum(self.report["by_system"].values()),
        )


if __name__ == "__main__":
    unittest.main()
