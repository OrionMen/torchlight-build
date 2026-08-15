from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crawler.audit_hero_trait_structured_dom_v1 import ROOT, build_audit, write_report


class HeroTraitStructuredDOMAuditV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = build_audit(ROOT)

    def test_all_27_entities_and_raw_sources_are_complete(self) -> None:
        source = self.report["source_completeness"]
        self.assertEqual((27, 27, 27, 27), (
            source["manifest_pages"], source["entities"],
            source["raw_present"], source["raw_nonempty"],
        ))
        self.assertEqual([], source["zero_byte"])
        self.assertEqual([], source["missing"])
        self.assertEqual(27, source["http_200_meta"])
        self.assertEqual(27, source["raw_hash_matches_meta"])
        self.assertEqual(0, source["duplicate_route_count"])

    def test_entity_and_record_boundaries_are_not_whole_pages_or_text_lines(self) -> None:
        model = self.report["entity_model"]
        self.assertEqual(["hero", "hero_trait"], model["entity_classification"])
        self.assertIn("data-src=affix", model["record_boundary"])
        counts = self.report["record_counts"]
        self.assertEqual(181, counts["trait_nodes"])
        self.assertEqual(331, counts["hero_trait_effect"])
        self.assertEqual(1299, counts["line_fragments_not_records"])
        self.assertGreater(counts["line_fragments_not_records"], counts["hero_trait_effect"])

    def test_template_groups_cover_every_entity_and_record(self) -> None:
        groups = self.report["template_groups"]
        self.assertEqual(8, len(groups))
        self.assertEqual(27, sum(group["count"] for group in groups))
        self.assertEqual(331, sum(group["candidate_records"] for group in groups))
        self.assertTrue(all('[data-src="affix"]' in group["required_selectors"] for group in groups))

    def test_candidate_counts_are_repeatable_and_distribution_is_explicit(self) -> None:
        candidate = self.report["candidate_record_types"]
        self.assertEqual(["hero_trait_effect"], [item["record_type"] for item in candidate])
        self.assertEqual(331, candidate[0]["count"])
        counts = self.report["record_counts"]
        self.assertEqual(331, sum(counts["by_entity"].values()))
        distribution = self.report["record_distribution"]
        self.assertEqual(10, distribution["minimum"])
        self.assertEqual(28, distribution["maximum"])
        self.assertEqual(11, distribution["median"])

    def test_stable_identity_is_complete_but_honestly_medium_confidence(self) -> None:
        stable = self.report["stable_key_coverage"]
        self.assertEqual(331, stable["candidate_records"])
        self.assertEqual(0, stable["native_data_id_records"])
        self.assertEqual(0.0, stable["native_stable_key_coverage"])
        self.assertEqual(331, stable["medium_confidence_composite_records"])
        self.assertEqual(1.0, stable["medium_confidence_composite_coverage"])
        self.assertEqual(1, stable["duplicate_before_occurrence_disambiguation"])
        self.assertEqual(0, stable["duplicate_after_occurrence_disambiguation"])
        self.assertIn("not a native gameplay ID", stable["warning"])

    def test_duplicate_and_branch_level_analysis_are_structural(self) -> None:
        duplicate = self.report["duplicate_analysis"]
        self.assertEqual(1, duplicate["duplicate_stable_key_groups_before_disambiguation"])
        self.assertEqual(0, duplicate["duplicate_stable_key_groups_after_disambiguation"])
        self.assertEqual(0, duplicate["current_history_duplicate_keys"])
        branch = self.report["branch_level_variant_analysis"]
        self.assertEqual((187, 144, 37), (
            branch["explicit_level_records"], branch["unspecified_level_records"],
            branch["nodes_with_multiple_levels"],
        ))
        self.assertFalse(branch["branch_selector_present"])
        self.assertFalse(branch["level_selector_present"])

    def test_legacy_boon_memory_history_and_skill_shop_are_excluded(self) -> None:
        exclusion = self.report["historical_exclusion"]
        self.assertEqual(0, exclusion["pages_with_historical_structure"])
        self.assertEqual(0, exclusion["historical_records"])
        self.assertEqual(0, exclusion["boon_candidate_records"])
        self.assertEqual(0, exclusion["hero_memory_candidate_records"])
        self.assertEqual(0, exclusion["skill_shop_candidate_records"])
        self.assertIn("#技能商店", exclusion["excluded_sibling_scope"])
        self.assertIn("show.active", exclusion["structural_scope"])

    def test_search_whitelist_never_wraps_whole_page_text(self) -> None:
        whitelist = self.report["search_text_whitelist"]
        self.assertIn("one current affix block effect", whitelist["include"])
        self.assertIn("whole-page Hero plain_text", whitelist["record_rule"])
        noise = " ".join(self.report["noise_exclusions"])
        for item in ("skill shop", "tooltip", "boon", "hero_memory", "JS/CSS"):
            self.assertIn(item, noise)

    def test_locator_totals_and_case_studies_are_complete(self) -> None:
        locator = self.report["locator_support"]
        self.assertEqual((331, 0, 0), (
            locator["record_level"], locator["section_level"], locator["page_level"],
        ))
        self.assertEqual({"high": 0, "medium": 331, "low": 0}, locator["confidence"])
        cases = self.report["case_studies"]
        self.assertEqual({
            "minimum", "maximum", "ordinary", "branch_level",
            "duplicate_stable_key_risk", "legacy_boon_memory_confusion",
        }, set(cases))
        self.assertEqual("tlidb:cn:Creative_Genius", cases["maximum"]["entity_id"])
        self.assertEqual("tlidb:cn:Incarnation_of_the_Gods", cases["duplicate_stable_key_risk"]["entity_id"])

    def test_framework_and_parser_recommendation_are_explicit(self) -> None:
        self.assertTrue(self.report["framework_compatible"])
        compatibility = self.report["framework_compatibility"]
        self.assertTrue(compatibility["compatible"])
        self.assertEqual([], compatibility["required_framework_changes"])
        recommendation = self.report["parser_recommendation"]
        self.assertIn("one parameterized", recommendation["strategy"])
        self.assertEqual("hero.trait.effects", recommendation["parser_id"])
        self.assertEqual(["hero_trait_effect"], recommendation["record_types"])

    def test_report_is_valid_json_and_has_no_errors(self) -> None:
        self.assertEqual([], self.report["errors"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            write_report(self.report, path)
            loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(1, loaded["schema_version"])
        self.assertEqual(331, loaded["record_counts"]["hero_trait_effect"])


if __name__ == "__main__":
    unittest.main()
