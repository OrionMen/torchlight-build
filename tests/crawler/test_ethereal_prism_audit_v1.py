import unittest
from pathlib import Path

from crawler.audit_ethereal_prism_v1 import build_audit, inspect_ethereal_prism_html


ROOT = Path(__file__).resolve().parents[2]


class EtherealPrismAuditV1Test(unittest.TestCase):
    def test_page_and_affix_sections_are_recognized(self):
        evidence = inspect_ethereal_prism_html(
            '''
            <div id="基础词缀" class="tab-pane active show"><table>
              <tr><td><span data-modifier-id="base-1">基础效果</span></td></tr>
            </table></div>
            <div id="随机词缀" class="tab-pane"><table>
              <tr><td><span data-modifier-id="random-1">随机效果</span></td></tr>
            </table></div>
            <div id="Item" class="tab-pane">
              <a href="Ethereal_Prism%3A_Haze">迷雾</a>
            </div>
            ''',
        )
        self.assertTrue(evidence["base_affix_section"]["detected"])
        self.assertTrue(evidence["base_affix_section"]["active_by_default"])
        self.assertEqual(1, evidence["base_affix_section"]["row_count"])
        self.assertEqual(1, evidence["random_affix_section"]["row_count"])
        self.assertEqual("Ethereal_Prism:_Haze", evidence["item_section"]["linked_items"][0]["id"])

    def test_real_page_is_one_system_candidate_with_two_affix_regions(self):
        report = build_audit(ROOT)
        self.assertTrue(report["entity_candidate"]["confirmed"])
        self.assertEqual("system_entity_candidate", report["entity_candidate"]["classification"])
        self.assertEqual(33, report["base_affix_section"]["row_count"])
        self.assertEqual(358, report["random_affix_section"]["row_count"])
        self.assertEqual(24, report["related_item_section"]["linked_item_count"])
        self.assertEqual(0, report["noise"]["material_pages_detected"])
        self.assertEqual(0, report["noise"]["historical_sections_detected"])

    def test_noise_and_related_pages_are_excluded_from_search_recommendation(self):
        report = build_audit(ROOT)
        recommendation = report["search_recommendation"]
        self.assertIn("基础词缀", recommendation["include"])
        self.assertIn("随机词缀", recommendation["include"])
        self.assertIn("内部 ID", recommendation["exclude"])
        self.assertIn("图片资源名", recommendation["exclude"])
        self.assertIn("Item 列表", recommendation["exclude"])
        linked = [
            page for page in report["excluded_pages"]
            if page["classification"] == "related_item_page"
        ]
        self.assertEqual(24, len(linked))
        self.assertTrue(all(page["raw_snapshot_available"] for page in linked))


if __name__ == "__main__":
    unittest.main()
