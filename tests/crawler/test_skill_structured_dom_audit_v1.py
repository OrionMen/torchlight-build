from __future__ import annotations

import json
import unittest
from pathlib import Path

from crawler.audit_skill_structured_dom_v1 import build_audit, inspect_skill_html


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "data/reports/local-wiki/skill-structured-dom-audit-v1.json"


class SkillStructuredDomAuditV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = build_audit(ROOT)

    def test_source_and_entity_scope_are_complete(self) -> None:
        source = self.report["source_completeness"]
        self.assertTrue(source["complete"])
        self.assertEqual(721, source["totals"]["manifest_pages"])
        self.assertEqual(721, source["totals"]["raw_nonempty"])
        self.assertEqual(0, source["totals"]["zero_byte_raw"])
        self.assertEqual(0, source["totals"]["missing_raw"])
        self.assertEqual(721, source["totals"]["hash_matches"])
        scope = self.report["entity_scope"]
        self.assertEqual(721, scope["entity_count"])
        self.assertEqual(721, scope["entity_present"])
        self.assertEqual(721, scope["visible"])
        self.assertEqual(7, scope["hidden_directory_entities_outside_scope"])

    def test_business_classification_matches_authorized_manifests(self) -> None:
        expected = {
            "active_skill": ("skill_active", 204),
            "support_skill": ("skill_support", 122),
            "passive_skill": ("skill_passive", 55),
            "activation_medium_skill": ("skill_activation_medium", 28),
            "magnificent_support_skill": ("skill_magnificent_support", 140),
            "noble_support_skill": ("skill_noble_support", 154),
            "modularization_skill": ("skill_modularization", 18),
        }
        for system, (subcategory, count) in expected.items():
            with self.subTest(system=system):
                item = self.report["business_classification"][system]
                self.assertEqual(subcategory, item["subcategory_id"])
                self.assertEqual(count, item["entities"])

    def test_template_groups_are_derived_from_real_dom(self) -> None:
        groups = {item["id"]: item["page_count"] for item in self.report["template_groups"]}
        self.assertEqual({
            "skill_modifier_growth": 321,
            "skill_standalone_card": 244,
            "skill_tabbed_cache_history": 83,
            "skill_tabbed_variants": 73,
        }, groups)
        leap = inspect_skill_html(
            (ROOT / "data/raw/manifests/active_skill/raw_html/Leap_Attack.html").read_text(encoding="utf-8")
        )
        self.assertEqual("skill_tabbed_variants", leap["template_group"])
        self.assertEqual(["跃击"], leap["active_panes"])
        self.assertIn("爱势汹汹", leap["inactive_panes"])
        self.assertEqual("SS13赛季", leap["current_version"])

    def test_candidate_records_and_stable_keys(self) -> None:
        counts = self.report["record_counts"]
        self.assertEqual(721, counts["skill_effect"])
        self.assertEqual(1164, counts["skill_growth_modifier"])
        self.assertEqual(1885, counts["estimated_total"])
        stable = self.report["stable_key_analysis"]
        self.assertEqual(0, stable["data_skill_id"])
        self.assertEqual(26, stable["data_id"])
        self.assertEqual(0, stable["data_id_accepted_for_identity"])
        self.assertEqual(1164, stable["data_modifier_id"])
        self.assertEqual(721, stable["info_id_coverage"])
        self.assertEqual({}, stable["duplicate_info_ids"])
        self.assertEqual({}, stable["duplicate_modifier_ids_across_entities"])
        self.assertEqual({"high": 1885, "medium": 0, "low": 0}, stable["identity_confidence"])

    def test_growth_modifiers_are_record_level_and_tiered(self) -> None:
        raw = (
            ROOT / "data/raw/manifests/activation_medium_skill/raw_html/Activation_Medium%3A_Preparation.html"
        ).read_text(encoding="utf-8")
        dom = inspect_skill_html(raw)
        self.assertEqual("skill_modifier_growth", dom["template_group"])
        self.assertEqual(11, len(dom["modifiers"]))
        self.assertEqual("modifier:771000010", dom["modifiers"][0]["stable_key"])
        self.assertEqual("0", dom["modifiers"][0]["tier"])
        self.assertEqual(["Tier", "name"], dom["modifiers"][0]["table_headers"])
        locator = self.report["locator_support"]
        self.assertEqual(1164, locator["record_level"])
        self.assertEqual(721, locator["section_level"])
        self.assertEqual(0, locator["page_level"])

    def test_level_rows_are_metadata_not_independent_records(self) -> None:
        level = self.report["level_model"]
        self.assertEqual(264, level["pages_with_level_tables"])
        self.assertEqual(10560, level["level_rows"])
        self.assertIn("not independent", level["model"])
        self.assertEqual({"20": 721}, level["observed_display_level"])

    def test_history_and_search_noise_have_explicit_boundaries(self) -> None:
        history = self.report["historical_exclusion"]
        self.assertEqual(695, history["pages_with_history"])
        self.assertEqual(767, history["historical_cards"])
        self.assertTrue(history["excluded_from_records"])
        noise = self.report["noise_exclusions"]["current_search_plain_text"]
        self.assertEqual(721, noise["info_id"]["count"])
        self.assertEqual(721, noise["show_description"]["count"])
        self.assertEqual(273, noise["skill_shop"]["count"])
        self.assertEqual(0, noise["historical_ss12"]["count"])
        whitelist = self.report["search_text_whitelist"]
        self.assertIn("current growth modifier text", whitelist["include"])
        self.assertIn("Info/internal IDs", whitelist["exclude"])

    def test_duplicate_text_does_not_override_stable_identity(self) -> None:
        duplicates = self.report["duplicate_analysis"]
        self.assertEqual(80, duplicates["same_modifier_text_different_stable_ids"])
        self.assertEqual(1, duplicates["same_skill_effect_text_different_skill_ids"])
        self.assertTrue(duplicates["modifier_examples"])
        self.assertGreater(len(duplicates["modifier_examples"][0]["stable_keys"]), 1)

    def test_cases_framework_and_parser_recommendation(self) -> None:
        cases = self.report["case_studies"]
        for name in (
            "simplest", "most_complex", "active_skill", "passive_skill", "support_skill",
            "multi_level", "multi_modifier", "current_and_history",
        ):
            self.assertIn(name, cases)
            self.assertTrue(cases[name]["stable_entity_key"].startswith("skill:"))
        self.assertEqual("record", cases["multi_modifier"]["landing_level"])
        self.assertGreater(cases["current_and_history"]["historical_card_count"], 0)
        framework = self.report["framework_compatibility"]
        self.assertTrue(framework["compatible"])
        self.assertFalse(framework["framework_change_required"])
        recommendation = self.report["parser_recommendation"]
        self.assertTrue(recommendation["parser_ready"])
        self.assertEqual("crawler/structured/skill_parser.py", recommendation["parser_file"])
        self.assertEqual("skill_structured_v1", recommendation["parser_id"])
        self.assertEqual(1885, recommendation["estimated_records"])

    def test_report_json_is_valid(self) -> None:
        self.assertEqual([], self.report["errors"])
        if REPORT.is_file():
            self.assertIsInstance(json.loads(REPORT.read_text(encoding="utf-8")), dict)


if __name__ == "__main__":
    unittest.main()
