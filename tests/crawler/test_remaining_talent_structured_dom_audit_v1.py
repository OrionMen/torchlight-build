from __future__ import annotations

import json
import unittest
from pathlib import Path

from crawler.audit_remaining_talent_structured_dom_v1 import build_audit


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "data/reports/local-wiki/remaining-talent-structured-dom-audit-v1.json"


class RemainingTalentStructuredDomAuditV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = build_audit(ROOT)

    def test_entity_scope_matches_repository(self) -> None:
        scope = self.report["entity_scope"]
        self.assertEqual(32, scope["entity_count"])
        self.assertEqual({"talent_hero": 30, "talent_new_god": 1, "talent_nether_king_entity": 1}, scope["subcategory_counts"])
        self.assertEqual(0, scope["hidden_entities"])
        self.assertTrue(all(page["entity_type"] == "talent" for page in scope["entities"]))

    def test_source_completeness(self) -> None:
        source = self.report["source_completeness"]
        self.assertEqual(32, source["raw_present"])
        self.assertEqual(32, source["raw_nonempty"])
        self.assertEqual(0, source["zero_byte"])
        self.assertEqual(0, source["missing"])
        self.assertEqual(32, source["http_200"])
        self.assertEqual(32, source["hash_matches"])
        self.assertEqual(0, source["recovered_sources"])

    def test_template_coverage_is_complete(self) -> None:
        coverage = self.report["template_coverage"]
        self.assertEqual(32, coverage["covered"])
        self.assertEqual(100.0, coverage["percent"])
        self.assertEqual({"talent_active_pane", "talent_root_container", "talent_active_pane_with_nested_modifiers"}, {group["group_id"] for group in self.report["template_groups"]})

    def test_candidate_counts_are_repeatable(self) -> None:
        counts = self.report["record_counts"]
        self.assertEqual(1141, counts["total"])
        self.assertEqual(1013, counts["by_subcategory"]["talent_hero"])
        self.assertEqual(36, counts["by_subcategory"]["talent_new_god"])
        self.assertEqual(92, counts["by_subcategory"]["talent_nether_king_entity"])
        self.assertEqual(30, self.report["record_distribution"]["min"])
        self.assertEqual(92, self.report["record_distribution"]["max"])

    def test_native_identity_and_duplicates(self) -> None:
        ids = self.report["data_talent_id_analysis"]
        self.assertEqual(1141, ids["candidate_records"])
        self.assertEqual(1141, ids["unique_ids"])
        self.assertEqual(100.0, ids["coverage_percent"])
        self.assertEqual(0, ids["within_entity_duplicate_ids"])
        self.assertEqual(0, ids["cross_entity_duplicate_ids"])
        self.assertEqual({"high": 1141, "medium": 0, "low": 0, "unresolved": 0}, self.report["identity_confidence"])
        duplicates = self.report["duplicate_analysis"]
        self.assertEqual(0, duplicates["nodes_with_multiple_modifiers"])
        self.assertEqual(9, duplicates["nodes_with_one_nested_modifier"])

    def test_level_branch_history_and_whitelist(self) -> None:
        state = self.report["level_branch_board_analysis"]
        self.assertFalse(state["level_selector"])
        self.assertFalse(state["branch_selector"])
        self.assertEqual("metadata", state["point_requirement"])
        historical = self.report["historical_legacy_exclusion"]
        self.assertEqual(0, historical["historical_candidate_records"])
        self.assertIn("inactive tab-pane", historical["excluded_structural_scopes"])
        whitelist = self.report["search_text_whitelist"]
        self.assertIn("current node effect", whitelist["include"])
        self.assertIn("whole-page plain_text", whitelist["exclude"])

    def test_divinity_slate_has_explicit_legacy_support_conclusion(self) -> None:
        divinity = self.report["divinity_slate_analysis"]
        self.assertEqual("path_of_progression", divinity["manifest_system"])
        self.assertTrue(divinity["raw_present"])
        self.assertEqual(0, divinity["data_talent_id_count"])
        self.assertIn("legacy/support", divinity["conclusion"])
        self.assertEqual(0, self.report["case_studies"]["Divinity_Slate"]["candidate_records"])

    def test_locator_cases_and_framework_contract(self) -> None:
        locator = self.report["locator_support"]
        self.assertEqual(1141, locator["record_level"])
        self.assertEqual(100.0, locator["record_level_percent"])
        self.assertFalse(locator["whole_page_unscoped_lookup"])
        for key in ("hero_simplest", "hero_most_complex", "hero_ordinary", "new_god", "nether_king"):
            self.assertIn(key, self.report["case_studies"])
            self.assertEqual("record", self.report["case_studies"][key]["locator_level"])
        self.assertTrue(self.report["framework_compatible"])
        self.assertTrue(self.report["parser_recommendation"]["unified_parser"])

    def test_report_json_is_valid(self) -> None:
        self.assertEqual([], self.report["errors"])
        if REPORT.is_file():
            self.assertIsInstance(json.loads(REPORT.read_text(encoding="utf-8")), dict)


if __name__ == "__main__":
    unittest.main()
