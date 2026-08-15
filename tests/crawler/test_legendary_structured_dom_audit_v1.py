from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from crawler.audit_legendary_structured_dom_v1 import ROOT, build_audit, inspect_html


class LegendaryStructuredDOMAuditV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = build_audit(ROOT)

    def test_all_332_entities_are_audited_and_grouped(self) -> None:
        self.assertEqual(332, self.report["legendary_pages"])
        self.assertEqual(332, sum(group["page_count"] for group in self.report["template_groups"]))
        self.assertEqual([], self.report["errors"])

    def test_current_and_historical_cards_are_separated_by_dom_class(self) -> None:
        html = """
        <div class="card ui_item popupItem"><div class="item_ver">SS13赛季</div>
          <div class="tierParent"><span data-modifier-id="current">当前效果</span></div></div>
        <div class="card ui_item popupItem previousItem"><div class="item_ver">SS12赛季</div>
          <div class="tierParent"><span data-modifier-id="old">历史效果</span></div></div>
        """
        evidence = inspect_html(html)
        self.assertEqual(1, evidence["current_card_count"])
        self.assertEqual(1, evidence["historical_card_count"])
        self.assertEqual(1, evidence["legendary_affix_count"])
        self.assertEqual(1, evidence["historical_modifier_count"])

    def test_modifier_regions_and_stable_keys_are_detected(self) -> None:
        html = """
        <div class="card ui_item popupItem"><span data-modifier-id="base">+8 敏捷</span>
          <div class="tierParent"><span data-modifier-id="effect">传奇效果</span></div></div>
        <div class="card ui_item"><div data-i18n="hyperlink|name|30001">Corroded</div>
          <span data-modifier-id="corroded">侵蚀效果</span></div>
        """
        evidence = inspect_html(html)
        self.assertEqual(1, evidence["base_stat_count"])
        self.assertEqual(1, evidence["legendary_affix_count"])
        self.assertEqual(1, evidence["corrosion_effect_count"])
        self.assertEqual("effect", evidence["legendary_affix_examples"][0]["stable_key"])

    def test_noise_regions_are_classified_but_not_candidate_records(self) -> None:
        self.assertIn(".fst-italic lore", self.report["noise_exclusions"])
        self.assertIn("Drop Source card", self.report["noise_exclusions"])
        record_types = {item["record_type"] for item in self.report["candidate_record_types"]}
        self.assertEqual(
            {"legendary_base_stat", "legendary_affix", "legendary_corruption_effect"},
            record_types,
        )

    def test_firebird_case_has_current_history_and_corrosion(self) -> None:
        case = self.report["case_studies"]["necklace_of_firebird"]
        self.assertEqual("Necklace_of_Firebird", case["id"])
        self.assertGreater(case["current_card_count"], 0)
        self.assertGreater(case["historical_card_count"], 0)
        self.assertGreater(case["corrosion_effect_count"], 0)
        self.assertTrue(all("SS13" in label for label in case["current_versions"]))

    def test_single_effect_case_really_has_one_legendary_affix(self) -> None:
        case = self.report["case_studies"]["single_legendary_effect"]
        self.assertEqual(1, case["legendary_affix_count"])

    def test_every_page_supports_record_level_locator(self) -> None:
        support = self.report["locator_support"]
        self.assertEqual(332, support["record_level"])
        self.assertEqual(support["record_count"], support["stable_record_count"])

    def test_report_can_be_written_as_json_by_main_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.json"
            import json
            path.write_text(json.dumps(self.report, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(332, json.loads(path.read_text(encoding="utf-8"))["legendary_pages"])


if __name__ == "__main__":
    unittest.main()
