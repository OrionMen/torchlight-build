import json
import unittest
from pathlib import Path

from crawler.audit_entity_dedup import canonical_route, load_category_map, source_role


REPO = Path(__file__).resolve().parents[2]
REPORT = REPO / "data/reports/local-wiki/entity-dedup-audit.json"


class EntityDedupAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads(REPORT.read_text(encoding="utf-8"))
        cls.candidates = cls.report["entity_candidates"]

    def test_same_route_multiple_sources_are_candidates(self):
        self.assertTrue(self.candidates)
        for candidate in self.candidates:
            self.assertGreater(len(candidate["sources"]), 1)
            self.assertEqual(
                {candidate["canonical_route"]},
                {source["canonical_route"] for source in candidate["sources"]},
            )

    def test_different_routes_are_not_merged(self):
        routes = [candidate["canonical_route"] for candidate in self.candidates]
        self.assertEqual(len(routes), len(set(routes)))
        self.assertNotEqual(canonical_route("/cn/Trinity"), canonical_route("/cn/Frozen_Flame"))

    def test_hyperlink_is_secondary(self):
        self.assertEqual("secondary", source_role("hyperlink"))
        hyperlink_sources = [
            source
            for candidate in self.candidates
            for source in candidate["sources"]
            if source["system_id"] == "hyperlink"
        ]
        self.assertTrue(hyperlink_sources)
        self.assertTrue(all(source["role"] == "secondary" for source in hyperlink_sources))

    def test_category_is_inherited(self):
        mapping = load_category_map(REPO / "config/game_category_mapping.json")
        self.assertEqual("equipment", mapping["craft"]["id"])
        candidate = next(item for item in self.candidates if item["canonical_route"] == "/cn/Trinity/")
        self.assertEqual("equipment", candidate["category"])

    def test_confidence_output(self):
        self.assertTrue(all(item["confidence"] in {"high", "medium", "low"} for item in self.candidates))
        self.assertEqual(
            len(self.candidates),
            sum(self.report["statistics"]["confidence"].values()),
        )


if __name__ == "__main__":
    unittest.main()
