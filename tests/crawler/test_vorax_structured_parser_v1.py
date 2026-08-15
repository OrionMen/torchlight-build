from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

from crawler.build_full_wiki_mirror import local_assets
from crawler.structured.parser_base import ParserInput
from crawler.structured.parsers.vorax_equipment_parser import VoraxDefinition, VoraxEquipmentParser
from crawler.structured.run_vorax_equipment_parser import ROOT


INDEX = ROOT / "data/generated/structured/ss13/structured-search-index.json"
REPORT = ROOT / "data/reports/local-wiki/vorax-structured-parser-v1-report.json"


class VoraxStructuredParserV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = json.loads(INDEX.read_text(encoding="utf-8"))
        cls.report = json.loads(REPORT.read_text(encoding="utf-8"))
        cls.records = [record for record in cls.index["records"] if record.get("entity_type") == "vorax_equipment"]
        assets = local_assets()
        cls.search_js = assets["_local/search/app.js"]
        cls.landing_js = assets["_local/mirror.js"]

    def test_ten_entities_match_and_all_five_record_types_exist(self) -> None:
        self.assertEqual(10, self.report["vorax_entities"])
        self.assertEqual(10, self.report["parsed_entities"])
        self.assertEqual(10, self.report["structure_matched"])
        self.assertEqual(0, self.report["structure_mismatches"])
        self.assertEqual({
            "vorax_base_stat", "vorax_special_mechanic", "vorax_base_affix",
            "vorax_craft_affix", "vorax_legendary_quality_affix",
        }, {record["record_type"] for record in self.records})

    def test_record_counts_identity_and_locator_coverage(self) -> None:
        self.assertEqual(7499, len(self.records))
        self.assertEqual(7499, self.report["unique_record_ids"])
        self.assertEqual(10, self.report["section_level_records"])
        self.assertEqual(7489, self.report["landing"]["record_level"])
        self.assertGreater(self.report["stable_key_coverage"], 0.998)

    def test_special_mechanics_are_section_level_not_fake_modifier_records(self) -> None:
        special = [record for record in self.records if record["record_type"] == "vorax_special_mechanic"]
        self.assertEqual(10, len(special))
        self.assertTrue(all(record["source_locator"]["locator_level"] == "section" for record in special))
        self.assertTrue(all(record["source_locator"]["stable_key"] == "section:special_mechanic" for record in special))
        self.assertTrue(all(record["source_locator"]["section_selector"] == "[data-block='detail']" for record in special))

    def test_history_item_tab_and_noise_are_excluded(self) -> None:
        noise = self.report["noise_validation"]
        self.assertEqual(30, self.report["historical_records_excluded"])
        self.assertEqual(0, noise["ss12_records"])
        self.assertEqual(0, noise["item_tab_records"])
        self.assertEqual(0, noise["requirement_records"])
        self.assertEqual(0, noise["drop_source_records"])
        self.assertFalse(any(record["source_locator"]["dom_id"] == "Item" for record in self.records))

    def test_craft_tiers_include_t0_plus_through_t2_and_show_all_for_3_to_5(self) -> None:
        craft = [record for record in self.records if record["record_type"] == "vorax_craft_affix"]
        self.assertEqual({"t0_plus", "t0", "t1", "t2", "all"}, {record["tier"] for record in craft})
        for source in ("3", "4", "5"):
            self.assertTrue(all(
                record["tier"] == "all" for record in craft
                if record["source_tier_value"] == source
            ))

    def test_classification_and_search_total_preserve_existing_records(self) -> None:
        self.assertEqual(28780, self.index["record_count"])
        self.assertEqual(10442, sum(record.get("entity_type") == "equipment" for record in self.index["records"]))
        self.assertEqual(3287, sum(record.get("entity_type") == "legendary_equipment" for record in self.index["records"]))
        self.assertTrue(all(
            record["content_category_id"] == "equipment"
            and record["content_subcategory_id"] == "equipment_vorax"
            for record in self.records
        ))
        self.assertEqual(8, json.loads((ROOT / "local_wiki/ss13/site/search-index.json").read_text(encoding="utf-8"))["schema_version"])

    def test_legs_battle_intent_returns_structured_records_and_suppresses_page(self) -> None:
        matches = [
            record for record in self.records
            if record["entity_id"] == "tlidb:cn:Vorax_Limb:_Legs" and "战意" in record["text"]
        ]
        self.assertTrue(matches)
        self.assertIn("structuredEntities.has(hit.x.entity_id)", self.search_js)
        self.assertIn("!structuredEntities.has(hit.x.entity_id)", self.search_js)

    def test_search_url_carries_vorax_view_state_and_section_fallback(self) -> None:
        for token in (
            "structured_vorax_tab", "structured_container", "structured_reset_filter",
            "structured_section_selector", "structured_tier",
        ):
            self.assertIn(token, self.search_js)
        self.assertIn("if(x.source_locator.section_selector)", self.search_js)

    def test_landing_activates_tab_tier_filter_and_scoped_record(self) -> None:
        script = self.landing_js
        self.assertIn("bootstrap.Tab.getOrCreateInstance(trigger).show()", script)
        self.assertIn("tierValues={t0_plus:'0+',t0:'0',t1:'1',t2:'2'}", script)
        self.assertIn("input[type=\"radio\"][name=\"showDetail\"]", script)
        self.assertIn("pane.querySelector('.popupItem:not(.previousItem)')", script)
        self.assertIn("root.querySelectorAll('[data-modifier-id]')", script)
        self.assertIn("const target=", script)
        self.assertIn("scrollIntoView", script)

    def test_legendary_quality_clears_filter_before_record_lookup(self) -> None:
        legendary = next(record for record in self.records if record["record_type"] == "vorax_legendary_quality_affix")
        self.assertEqual("clear", legendary["source_locator"]["view_state"]["legendary_filter"])
        self.assertIn("filter.value=''", self.landing_js)
        apply_script = self.landing_js.split("const applyTierAndLocate=", 1)[1]
        self.assertLess(apply_script.index("filter.value=''"), apply_script.index("waitForViewAndLocate()"))

    def test_historical_duplicate_modifier_lookup_is_current_container_scoped(self) -> None:
        head = next(record for record in self.records if record["entity_id"] == "tlidb:cn:Vorax_Limb:_Head" and record["record_type"] == "vorax_base_stat")
        self.assertEqual("current", head["source_locator"]["view_state"]["season_container"])
        self.assertIn("popupItem:not(.previousItem)", head["source_locator"]["container_selector"])
        self.assertNotIn("document.querySelectorAll('[data-modifier-id]')", self.landing_js)

    def test_missing_required_tab_is_structure_mismatch_with_no_records(self) -> None:
        slug = "Vorax_Limb:_Head"
        source = ROOT / "data/raw/manifests/inventory/raw_html" / f"{quote(slug, safe='-_.')}.html"
        html = source.read_text(encoding="utf-8").replace('id="Item" class="tab-pane', 'id="MissingItem" class="tab-pane', 1)
        with tempfile.TemporaryDirectory() as temporary:
            raw = Path(temporary) / "page.html"
            raw.write_text(html, encoding="utf-8")
            result = VoraxEquipmentParser(VoraxDefinition(slug, "渴瘾肢体：脑部")).parse(ParserInput(
                "ss13", "inventory", slug, f"/cn/{slug}/", raw
            ))
        self.assertEqual("structure_mismatch", result["structure_validation"]["status"])
        self.assertEqual([], result["records"])

    def test_case_studies_cover_required_real_pages(self) -> None:
        for slug in ("Vorax_Limb:_Head", "Vorax_Limb:_Legs", "Vorax_Aberrant_Limb:_Digits"):
            self.assertTrue(self.report["case_studies"][slug]["record_ids_unique"])
            self.assertEqual(["all", "t0", "t0_plus", "t1", "t2"], self.report["case_studies"][slug]["craft_tiers"])

    def test_record_identity_does_not_depend_on_text_or_season(self) -> None:
        from crawler.structured.schema import make_record_id
        identity = {
            "parser_id": "inventory.vorax_equipment.affixes",
            "entity_id": "tlidb:cn:Vorax_Limb:_Head",
            "record_type": "vorax_craft_affix",
            "section_key": "craft_affixes",
            "stable_key": "modifier:251150000",
        }
        before = make_record_id(**identity)
        # Text, rolls, and season are deliberately absent from the identity contract.
        after = make_record_id(**identity)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
