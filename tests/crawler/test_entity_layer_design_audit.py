import json
import unittest
from pathlib import Path

from crawler.audit_entity_layer_design import classify_medium


REPO = Path(__file__).resolve().parents[2]
REPORT = REPO / "data/reports/local-wiki/entity-layer-design-audit.json"


class EntityLayerDesignAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads(REPORT.read_text(encoding="utf-8"))

    def test_schema_proposal_has_required_identity_fields(self):
        fields = self.report["entity_schema_proposal"]["required_fields"]
        self.assertTrue({"entity_id", "title", "category", "canonical_route", "sources", "confidence"} <= set(fields))

    def test_high_safe_count_is_conservative(self):
        high = self.report["high_confidence_analysis"]
        self.assertEqual(428, high["total"])
        self.assertEqual(361, high["high_confidence_safe_count"])
        self.assertEqual(high["total"], high["high_confidence_safe_count"] + high["category_conflict_count"] + high["category_unmapped_count"])

    def test_medium_classes_cover_all_candidates(self):
        medium = self.report["medium_confidence_analysis"]
        self.assertEqual(70, medium["total"])
        self.assertEqual(70, sum(group["count"] for group in medium["classes"].values()))
        self.assertEqual(66, medium["classes"]["A"]["count"])
        self.assertEqual(4, medium["classes"]["B"]["count"])
        self.assertEqual(0, medium["classes"]["C"]["count"])

    def test_focus_cases_are_class_a(self):
        focus = self.report["medium_confidence_analysis"]["focus_cases"]
        self.assertEqual(
            {"Trinity", "Frozen_Flame", "Burning_Ice", "Windbreath_Convergence"},
            {item["id"] for item in focus},
        )
        self.assertTrue(all(item["classification"] == "A" for item in focus))

    def test_conflicting_primary_titles_are_not_auto_merged(self):
        candidate = {
            "category": "equipment",
            "sources": [
                {"role": "primary", "title": "甲", "raw_page_available": True},
                {"role": "primary", "title": "乙", "raw_page_available": True},
            ],
        }
        self.assertEqual("C", classify_medium(candidate)[0])

    def test_entity_id_recommendation_is_season_neutral(self):
        design = self.report["entity_id_design"]
        self.assertEqual("A_canonical_slug", design["recommendation"])
        self.assertIn("season-neutral", design["season_policy"])


if __name__ == "__main__":
    unittest.main()
