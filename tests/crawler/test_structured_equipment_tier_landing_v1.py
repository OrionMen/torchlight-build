from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crawler.build_full_wiki_mirror import local_assets
from crawler.structured.parser_base import ParserInput
from crawler.structured.parsers.equipment_parser import EquipmentDefinition, EquipmentParser
from crawler.structured.report_equipment_tier_landing import build_report
from crawler.structured.structure_probe import probe_section_table


ROOT = Path(__file__).resolve().parents[2]
INDEX_PATH = ROOT / "data/generated/structured/ss13/structured-search-index.json"


class StructuredEquipmentTierLandingV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        cls.records = cls.index["records"]
        cls.search_js = local_assets()["_local/search/app.js"]
        cls.landing_js = local_assets()["_local/mirror.js"]

    def test_four_real_craft_tiers_have_stable_metadata(self) -> None:
        expected = {"t0_plus": "0+", "t0": "0", "t1": "1", "t2": "2"}
        craft = [record for record in self.records if record["record_type"] == "equipment_craft_affix"]
        for tier, source_value in expected.items():
            with self.subTest(tier=tier):
                record = next(item for item in craft if item.get("tier") == tier)
                self.assertEqual(source_value, record["source_tier_value"])
                self.assertEqual(source_value, record["source_locator"]["tier_value"])
                self.assertTrue(record["source_locator"]["stable_key"].startswith("modifier:"))

    def test_search_url_and_landing_use_the_same_tier_parameter(self) -> None:
        self.assertIn("structured_tier=x.tier", self.search_js)
        self.assertIn("params.get('structured_tier')", self.landing_js)
        self.assertIn("tierValues={t0_plus:'0+',t0:'0',t1:'1',t2:'2'}", self.landing_js)

    def test_tab_then_tier_then_record_order_is_explicit(self) -> None:
        shown = self.landing_js.index("shown.bs.tab")
        apply_tier = self.landing_js.index("const applyTierAndLocate")
        dispatch = self.landing_js.index("dispatchEvent(new Event('change'")
        locate_after_filter = self.landing_js.index("requestAnimationFrame(()=>requestAnimationFrame(locate))")
        self.assertLess(apply_tier, shown)
        self.assertLess(dispatch, locate_after_filter)

    def test_missing_or_unknown_tier_uses_show_all(self) -> None:
        self.assertIn("tierValues[tier]||'all'", self.landing_js)
        self.assertIn("controls.find(node=>node.value==='all')", self.landing_js)

    def test_base_affix_has_no_craft_tier(self) -> None:
        base = next(record for record in self.records if record["record_type"] == "equipment_base_affix")
        self.assertNotIn("tier", base)
        self.assertNotIn("source_tier_value", base)

    def test_invalid_modifier_falls_back_without_error(self) -> None:
        self.assertIn("landing=target||", self.landing_js)
        self.assertIn("if(landing&&landing.scrollIntoView)requestAnimationFrame", self.landing_js)

    def test_tier_dom_contract_change_is_structure_mismatch(self) -> None:
        html = """
        <button data-bs-target="#力量头部基础词缀"></button>
        <button data-bs-target="#力量头部打造"></button>
        <div id="力量头部基础词缀" class="tab-pane fade"><table><tr><th>Tier</th><th>Modifier</th><th>Level</th><th>Weight</th></tr><tr><td>2</td><td><span data-modifier-id="1">base</span></td><td>1</td><td>1</td></tr></table></div>
        <div id="力量头部打造" class="tab-pane fade">
          <table><tr><th>Tier</th><th>Modifier</th><th>Lv</th><th>Weight</th><th>Library</th></tr><tr><td>1</td><td><span data-modifier-id="2">craft</span></td><td>1</td><td>1</td><td>x</td></tr></table>
          <table><tr><th>Tier</th><th>Modifier</th><th>Lv</th><th>Weight</th><th>Library</th></tr><tr><td>2</td><td><span data-modifier-id="3">craft2</span></td><td>1</td><td>1</td><td>x</td></tr></table>
        </div>
        """
        with tempfile.TemporaryDirectory() as temporary:
            raw = Path(temporary) / "STR_Helmet.html"
            raw.write_text(html, encoding="utf-8")
            definition = EquipmentDefinition("STR_Helmet", "力量头部")
            result = EquipmentParser(definition).parse(
                ParserInput("ss13", "inventory", definition.canonical_id, definition.route, raw)
            )
        self.assertEqual("structure_mismatch", result["structure_validation"]["status"])
        self.assertIn("tier_attribute", result["structure_validation"]["mismatches"]["craft_affixes"])

    def test_tier_value_change_does_not_change_structure_signature(self) -> None:
        def section(tier: str) -> str:
            return (
                '<button data-bs-target="#力量头部打造"></button>'
                '<div id="力量头部打造" class="tab-pane fade"><table>'
                '<tr><th>Tier</th><th>Modifier</th></tr>'
                f'<tr data-tier="{tier}"><td>{tier}</td><td>'
                '<span data-modifier-id="104700001">text</span></td></tr>'
                '</table></div>'
            )
        before = probe_section_table(section("1"), section_id="力量头部打造")
        after = probe_section_table(section("2"), section_id="力量头部打造")
        self.assertEqual(before["structure_signature"], after["structure_signature"])

    def test_report_has_all_tiers_and_no_errors(self) -> None:
        report = build_report(INDEX_PATH)
        self.assertTrue(report["tier_metadata_available"])
        self.assertTrue(report["show_all_fallback"]["available"])
        self.assertTrue(report["base_affix_regression"]["tier_parameter_absent"])
        self.assertEqual([], report["errors"])


if __name__ == "__main__":
    unittest.main()
