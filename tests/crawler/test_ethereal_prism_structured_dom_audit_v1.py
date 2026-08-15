from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crawler.audit_ethereal_prism_structured_dom_v1 import (
    build_report,
    inspect_section_rows,
)


REPO = Path(__file__).resolve().parents[2]


class EtherealPrismStructuredDomAuditV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = build_report(REPO)

    def test_source_and_single_entity_model_are_complete(self) -> None:
        source = self.report["source_completeness"]
        entity = self.report["entity_model"]
        self.assertTrue(source["manifest_entry_present"])
        self.assertTrue(source["raw_nonempty"])
        self.assertFalse(source["zero_byte"])
        self.assertEqual(200, source["http_status"])
        self.assertEqual(1, entity["entity_count"])
        self.assertEqual("talent_system", entity["entity_type"])
        self.assertEqual("talent_board", entity["category"])
        self.assertEqual("talent_ethereal_prism", entity["subcategory"])

    def test_only_two_affix_sections_are_candidate_sources(self) -> None:
        self.assertEqual(2, len(self.report["sections"]))
        self.assertEqual({"基础词缀", "随机词缀"}, {item["section_name"] for item in self.report["sections"]})
        self.assertTrue(all(item["structure_status"] == "matched" for item in self.report["sections"]))
        excluded = self.report["excluded_sources"]
        self.assertEqual(24, excluded["related_item_count"])
        self.assertTrue(all(not item["structured_affix_source"] for item in excluded["related_items"]))
        self.assertFalse(excluded["calibrate"]["structured_affix_source"])

    def test_record_counts_and_candidate_types_match_current_raw(self) -> None:
        self.assertEqual(33, self.report["record_counts"]["ethereal_prism_base_affix"])
        self.assertEqual(358, self.report["record_counts"]["ethereal_prism_random_affix"])
        self.assertEqual(391, self.report["candidate_records"])
        self.assertEqual({
            "ethereal_prism_base_affix", "ethereal_prism_random_affix",
        }, {item["record_type"] for item in self.report["candidate_record_types"]})

    def test_outer_modifier_identity_is_complete_and_unique(self) -> None:
        self.assertEqual(391, self.report["stable_key_records"])
        self.assertEqual(1.0, self.report["stable_key_coverage"])
        duplicate = self.report["duplicate_key_analysis"]
        self.assertEqual(0, duplicate["base_internal_outer_key_duplicates"])
        self.assertEqual(0, duplicate["random_internal_outer_key_duplicates"])
        self.assertEqual(0, duplicate["cross_section_outer_key_duplicates"])
        self.assertEqual(0, duplicate["outer_key_collision_count"])
        self.assertGreater(duplicate["nested_key_duplicate_count"], 0)

    def test_same_text_different_modifier_remains_independent(self) -> None:
        duplicate = self.report["duplicate_key_analysis"]
        self.assertEqual(0, duplicate["base_same_text"]["group_count"])
        self.assertEqual(97, duplicate["random_same_text"]["group_count"])
        self.assertEqual(209, duplicate["random_same_text"]["record_count"])
        case = self.report["case_studies"]["same_text_different_modifier"]
        self.assertGreater(len(case["matching_outer_keys"]), 1)
        self.assertEqual(len(case["matching_outer_keys"]), len(set(case["matching_outer_keys"])))

    def test_datatable_and_record_landing_are_framework_compatible(self) -> None:
        datatable = self.report["datatable_behavior"]
        self.assertFalse(datatable["paging"])
        self.assertTrue(datatable["client_search"])
        self.assertTrue(datatable["datatable_ready_required"])
        self.assertFalse(datatable["filter_reset_required"])
        self.assertEqual(391, self.report["locator_support"]["record_level"])
        self.assertEqual(0, self.report["locator_support"]["section_level"])
        self.assertTrue(self.report["framework_compatible"])
        self.assertFalse(self.report["framework_compatibility"]["generic_extension_required"])

    def test_row_inspector_uses_first_not_nested_modifier(self) -> None:
        rows = inspect_section_rows('''
          <button data-bs-target="#基础词缀">基础</button>
          <div id="基础词缀" class="tab-pane active show"><table><tbody>
            <tr><td><span data-modifier-id="outer">前缀<span data-modifier-id="inner">内层</span></span></td></tr>
          </tbody></table></div>
        ''', "基础词缀")
        self.assertEqual(1, len(rows))
        self.assertEqual("outer", rows[0]["outer_stable_key"])
        self.assertEqual(["inner"], rows[0]["nested_modifier_ids"])

    def test_noise_boundary_and_case_studies(self) -> None:
        boundary = self.report["search_text_boundary"]
        self.assertIn("affix effect text", boundary["include"])
        self.assertIn("出现位置 Item names", boundary["exclude"])
        self.assertIn("tooltip metadata", boundary["exclude"])
        self.assertIsNotNone(self.report["case_studies"]["base_affix"])
        self.assertIsNotNone(self.report["case_studies"]["random_affix"])
        self.assertIsNotNone(self.report["case_studies"]["multi_line_effect"])
        self.assertIsNone(self.report["case_studies"]["cross_section_stable_key"])
        self.assertEqual([], self.report["errors"])

    def test_report_is_json_serializable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            output.write_text(json.dumps(self.report, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(1, json.loads(output.read_text(encoding="utf-8"))["schema_version"])


if __name__ == "__main__":
    unittest.main()
