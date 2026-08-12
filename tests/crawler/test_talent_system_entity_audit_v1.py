import unittest
from pathlib import Path

from crawler.audit_talent_system_entity_v1 import build_audit, inspect_talent_html


ROOT = Path(__file__).resolve().parents[2]


class TalentSystemEntityAuditV1Test(unittest.TestCase):
    def test_page_recognition_and_inactive_history_exclusion(self):
        evidence = inspect_talent_html(
            '''
            <div id="巨力之神" class="tab-pane fade show active">
              <h5>巨力之神 /2</h5>
              <span data-talent-id="a">+10 力量</span>
              <span data-talent-id="b">核心机制</span>
            </div>
            <div id="巨力之神_cache-3" class="tab-pane fade">
              <span data-talent-id="old">历史效果</span>
            </div>
            <div id="Item" class="tab-pane fade">关联物品</div>
            ''',
            "巨力之神",
        )
        self.assertTrue(evidence["title_detected"])
        self.assertEqual(2, evidence["current_talent_count"])
        self.assertEqual(1, evidence["historical_talent_count"])
        self.assertIn("巨力之神_cache-3", evidence["historical_tab_sections"])
        self.assertIn("Item", evidence["excluded_tab_sections"])

    def test_real_entity_counts_and_groups(self):
        report = build_audit(ROOT)
        summary = report["summary"]
        self.assertEqual(32, summary["manifest_count"])
        self.assertEqual(30, summary["hero_talent_entity_count"])
        self.assertEqual(1, summary["new_god_entity_count"])
        self.assertEqual(1, summary["nether_king_entity_count"])
        self.assertEqual(32, summary["entity_count"])
        self.assertEqual(32, summary["raw_available"])
        self.assertEqual("New_God", report["new_god"]["entities"][0]["id"])
        self.assertEqual("Nether_King", report["nether_king"]["entities"][0]["id"])

    def test_directory_is_excluded_and_search_regions_are_declared(self):
        report = build_audit(ROOT)
        excluded = report["hero_talent"]["excluded_pages"]
        self.assertEqual(["Talent"], [item["id"] for item in excluded])
        self.assertTrue(all(item["classification"] == "category_page" for item in excluded))
        recommendation = report["hero_talent"]["search_recommendation"]
        self.assertIn("天赋效果", recommendation["include"])
        self.assertIn("核心机制", recommendation["include"])
        self.assertIn("历史版本", recommendation["exclude"])
        self.assertIn("内部 ID", recommendation["exclude"])


if __name__ == "__main__":
    unittest.main()
