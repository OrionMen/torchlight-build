from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crawler.audit_pact_fate_structured_dom_v1 import ROOT, build_audit, write_report


class PactFateStructuredDOMAuditV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = build_audit(ROOT)

    def test_entity_and_effective_source_completeness(self) -> None:
        pact = self.report["source_completeness"]["pact"]
        fate = self.report["source_completeness"]["fate"]
        self.assertEqual((175, 175, 175), (
            pact["entities"], pact["raw_present"], pact["raw_nonempty"]
        ))
        self.assertEqual((0, 0, 175), (
            pact["raw_zero_byte"], pact["missing_raw"], pact["http_200_meta"]
        ))
        self.assertEqual((193, 193, 193, 193), (
            fate["manifest_pages"], fate["entities"], fate["raw_present"], fate["raw_nonempty"]
        ))
        self.assertEqual((0, 0, 193), (
            fate["raw_zero_byte"], fate["missing_raw"], fate["http_200_meta"]
        ))

    def test_recovered_fate_sources_are_explicitly_covered(self) -> None:
        expected = {
            "Micro_Fate:_Deterioration_Duration",
            "Micro_Fate:_Trauma_Damage_Mitigation",
        }
        fate = self.report["source_completeness"]["fate"]
        gap = self.report["source_completeness"]["fate_entity_linkage_gap"]
        self.assertEqual(expected, set(fate["recovered_source_pages"]))
        self.assertEqual(expected, set(gap["pages"]))
        self.assertEqual(2, gap["count"])
        cases = self.report["case_studies"]["fate"]
        self.assertIn("micro_deterioration_duration", cases)
        self.assertIn("micro_trauma_damage_mitigation", cases)

    def test_template_groups_cover_every_raw_page(self) -> None:
        groups = self.report["template_groups"]
        self.assertEqual(175, sum(group["page_count"] for group in groups["pact"]))
        self.assertEqual(193, sum(group["page_count"] for group in groups["fate"]))
        self.assertEqual(27, len(groups["pact"]))
        self.assertEqual(3, len(groups["fate"]))
        self.assertTrue(all(group["dom_contract"] for group in groups["pact"] + groups["fate"]))

    def test_candidate_record_counts_match_raw_contracts(self) -> None:
        counts = self.report["record_counts"]
        self.assertEqual(2349, counts["pact_contract_node_effect"])
        self.assertEqual(190, counts["fate_effect"])
        self.assertEqual(1, counts["fate_entity_effect_section_level"])
        self.assertEqual(191, counts["fate_total_entity_records"])
        self.assertEqual(2, counts["fate_recovered_candidate_records"])

    def test_stable_key_coverage_and_duplicate_scopes(self) -> None:
        coverage = self.report["stable_key_coverage"]
        self.assertEqual(1.0, coverage["pact"]["coverage"])
        self.assertEqual(2349, coverage["pact"]["stable_key_records"])
        self.assertEqual(0, coverage["pact"]["duplicate_within_entity"])
        self.assertGreater(coverage["pact"]["duplicate_across_entities"], 0)
        self.assertEqual(190, coverage["fate"]["stable_key_records"])
        self.assertAlmostEqual(190 / 191, coverage["fate"]["coverage"], places=6)
        self.assertEqual(0, coverage["fate"]["duplicate_within_entity"])
        self.assertEqual(0, coverage["fate"]["duplicate_across_entities"])
        self.assertIn("never deduplicate by effect text", self.report["duplicate_analysis"]["rule"])

    def test_historical_and_inactive_content_have_structural_exclusions(self) -> None:
        history = self.report["historical_exclusion"]
        self.assertEqual(0, history["pact"]["pages_with_history"])
        self.assertEqual(36, history["pact"]["inactive_npc_pages"])
        self.assertIn("_NPC", history["pact"]["inactive_npc_selector"])
        self.assertEqual(190, history["fate"]["pages_with_history"])
        self.assertEqual(188, history["fate"]["entity_pages_with_history"])
        self.assertEqual(189, history["fate"]["historical_records"])
        self.assertEqual(187, history["fate"]["entity_historical_records"])
        self.assertEqual(189, history["fate"]["duplicate_current_history_keys"])
        self.assertEqual(187, history["fate"]["entity_duplicate_current_history_keys"])
        self.assertEqual(
            ".card.ui_item.popupItem.previousItem",
            history["fate"]["recommended_exclusion_selector"],
        )

    def test_search_whitelist_and_noise_exclusions_are_conservative(self) -> None:
        whitelist = self.report["search_text_whitelist"]
        self.assertIn("contract node effect", whitelist["pact"])
        self.assertIn("current modifier effect", whitelist["fate"])
        noise = " ".join(self.report["noise_exclusions"])
        for value in ("lv/name", "Info id", "Show Description", "historical", "inactive NPC"):
            self.assertIn(value, noise)

    def test_locator_support_does_not_fake_undetermined_record_key(self) -> None:
        locator = self.report["locator_support"]
        self.assertEqual((2349, 0), (locator["pact"]["record_level"], locator["pact"]["section_level"]))
        self.assertEqual((190, 1), (locator["fate"]["record_level"], locator["fate"]["section_level"]))
        undetermined = self.report["case_studies"]["fate"]["undetermined_fate"]
        self.assertEqual("section", undetermined["landing_level"])
        self.assertEqual([], undetermined["stable_keys"])

    def test_required_case_studies_are_present(self) -> None:
        pact = self.report["case_studies"]["pact"]
        fate = self.report["case_studies"]["fate"]
        self.assertEqual(
            {"red_umbrella", "simplest", "most_complex", "variant_npc"}, set(pact)
        )
        self.assertEqual({
            "micro_fire_resistance", "micro_deterioration_duration",
            "micro_trauma_damage_mitigation", "undetermined_fate", "ordinary", "most_complex",
        }, set(fate))
        self.assertEqual("/cn/Red_Umbrella/", pact["red_umbrella"]["route"])
        self.assertEqual("/cn/Undetermined_Fate/", fate["undetermined_fate"]["route"])

    def test_framework_compatibility_and_parser_recommendation_are_explicit(self) -> None:
        framework = self.report["framework_compatibility"]
        self.assertTrue(framework["compatible"])
        self.assertEqual([], framework["required_framework_changes"])
        recommendation = self.report["parser_recommendation"]
        self.assertEqual("separate parsers", recommendation["strategy"])
        self.assertEqual("pact_spirit_parser.py", recommendation["pact"]["file"])
        self.assertEqual("fate_parser.py", recommendation["fate"]["file"])

    def test_report_is_json_serializable_and_has_no_audit_errors(self) -> None:
        self.assertEqual([], self.report["errors"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            write_report(self.report, path)
            loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(1, loaded["schema_version"])
        self.assertEqual(175, loaded["source_completeness"]["pact"]["entities"])


if __name__ == "__main__":
    unittest.main()
