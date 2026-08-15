from __future__ import annotations

import json
import unittest

from crawler.audit_vorax_structured_dom_v1 import ROOT, build_audit, inspect_html


class VoraxStructuredDOMAuditV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = build_audit(ROOT)

    def test_all_vorax_entities_have_complete_sources_and_one_template_group(self) -> None:
        self.assertEqual(10, self.report["vorax_entities"])
        self.assertTrue(self.report["source_completeness"]["complete"])
        self.assertEqual(10, self.report["source_completeness"]["raw_nonempty"])
        self.assertEqual(10, sum(group["page_count"] for group in self.report["template_groups"]))
        self.assertEqual([], self.report["errors"])

    def test_real_dom_has_expected_tabs_and_view_states(self) -> None:
        case = self.report["case_studies"]["multiple_view_states"]
        self.assertEqual("打造", case["default_active_tab"])
        self.assertEqual(["all", "0+", "0", "1", "2"], case["craft_tier_values"])
        self.assertEqual("1", case["craft_default_tier"])
        self.assertEqual(1, case["legendary_filter_count"])

    def test_current_and_history_are_scoped_before_modifier_lookup(self) -> None:
        html = """
        <button class="nav-link active" data-bs-target="#打造">打造</button>
        <div id="打造" class="tab-pane active"><table><tr data-tier="1"><td><span data-modifier-id="craft">效果</span></table></div>
        <div id="传奇品质" class="tab-pane"><span data-modifier-id="legend">效果</span></div>
        <div id="基础词缀" class="tab-pane"><table><tr><td><span data-modifier-id="base">效果</span></table></div>
        <div id="渴瘾肢体：脑部" class="tab-pane">
          <div class="card popupItem"><div class="item_ver">SS13赛季</div><span data-modifier-id="same">当前</span><div data-block="detail">机制<hr></div></div>
          <div class="card popupItem previousItem"><div class="item_ver">SS12赛季</div><span data-modifier-id="same">历史</span></div>
        </div><div id="Item" class="tab-pane"></div>
        """
        evidence = inspect_html(html)
        self.assertEqual(["same"], evidence["current_modifier_ids"])
        self.assertEqual(["same"], evidence["historical_modifier_ids"])
        self.assertEqual(5, evidence["candidate_records"])
        self.assertEqual(4, evidence["stable_key_records"])

    def test_candidate_record_counts_and_stable_coverage_are_reproducible(self) -> None:
        report = self.report
        total = sum(item["record_count"] for item in report["candidate_record_types"])
        self.assertEqual(total, report["candidate_records"])
        self.assertGreater(report["candidate_records"], 0)
        self.assertGreater(report["stable_key_coverage"], 0.99)
        self.assertEqual(
            report["stable_key_records"], report["locator_support"]["record_level"]
        )

    def test_duplicate_keys_require_context_but_not_per_page_special_cases(self) -> None:
        duplicate = self.report["duplicate_key_analysis"]
        self.assertGreater(duplicate["cross_entity_duplicate_keys"], 0)
        self.assertGreater(duplicate["current_history_duplicate_keys"], 0)
        self.assertEqual(0, duplicate["within_entity_section_duplicates"])
        self.assertIn("entity_id", duplicate["identity_context_required"])

    def test_historical_content_is_excluded_by_dom_class(self) -> None:
        history = self.report["historical_exclusion"]
        self.assertEqual(10, history["pages_with_history"])
        self.assertEqual(".popupItem.previousItem inside the entity-title tab", history["selector"])

    def test_framework_is_compatible_and_report_is_valid_json(self) -> None:
        self.assertTrue(self.report["framework_compatible"])
        decoded = json.loads(json.dumps(self.report, ensure_ascii=False))
        self.assertEqual(1, decoded["schema_version"])


if __name__ == "__main__":
    unittest.main()
