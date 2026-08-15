from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from collections import Counter, defaultdict
from pathlib import Path

from crawler.build_full_wiki_mirror import local_assets
from crawler.structured.parser_base import ParserInput
from crawler.structured.parsers.ethereal_prism_parser import ENTITY_ID, EtherealPrismParser
from crawler.structured.run_ethereal_prism_parser import ROOT, generate
from crawler.structured.schema import make_record_id, resolve_record_landing


SOURCE_INDEX = ROOT / "data/generated/structured/ss13/structured-search-index.json"


class EtherealPrismStructuredParserV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temporary.name) / "structured"
        cls.output.mkdir()
        shutil.copy2(SOURCE_INDEX, cls.output / "structured-search-index.json")
        cls.before = json.loads(SOURCE_INDEX.read_text(encoding="utf-8"))
        cls.result, cls.index, cls.report = generate(
            ROOT, cls.output, Path(cls.temporary.name) / "report.json"
        )
        cls.records = [item for item in cls.index["records"] if item.get("entity_id") == ENTITY_ID]
        assets = local_assets()
        cls.search_js = assets["_local/search/app.js"]
        cls.landing_js = assets["_local/mirror.js"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_record_counts_and_classification(self) -> None:
        counts = Counter(item["record_type"] for item in self.records)
        self.assertEqual(33, counts["ethereal_prism_base_affix"])
        self.assertEqual(358, counts["ethereal_prism_random_affix"])
        self.assertEqual(391, len(self.records))
        self.assertTrue(all(item["entity_type"] == "talent_system" for item in self.records))
        self.assertTrue(all(item["content_category_id"] == "talent_board" for item in self.records))
        self.assertTrue(all(item["content_subcategory_id"] == "talent_ethereal_prism" for item in self.records))

    def test_outer_modifier_is_stable_identity_and_nested_modifiers_are_metadata_only(self) -> None:
        self.assertEqual(391, len({item["record_id"] for item in self.records}))
        self.assertTrue(all(item["source_locator"]["outer_modifier_required"] for item in self.records))
        self.assertTrue(all(item["source_locator"]["stable_key"].startswith("modifier:") for item in self.records))
        nested = [item for item in self.records if item["nested_modifier_ids"]]
        self.assertGreater(len(nested), 0)
        record = nested[0]
        identity = dict(
            parser_id="talent.ethereal_prism.affixes",
            entity_id=ENTITY_ID,
            record_type=record["record_type"],
            section_key=record["source_locator"]["section_key"],
            stable_key=record["source_locator"]["stable_key"],
        )
        self.assertEqual(record["record_id"], make_record_id(**identity))
        self.assertNotIn(record["nested_modifier_ids"][0], record["record_id"])
        self.assertEqual(0, self.report["nested_modifier_records_emitted"])

    def test_same_text_with_different_outer_keys_stays_independent(self) -> None:
        groups: dict[str, list[dict]] = defaultdict(list)
        for item in self.records:
            if item["record_type"] == "ethereal_prism_random_affix":
                groups[item["text"]].append(item)
        duplicate = next(items for items in groups.values() if len(items) > 1)
        self.assertEqual(len(duplicate), len({item["record_id"] for item in duplicate}))
        self.assertEqual(len(duplicate), len({item["source_locator"]["stable_key"] for item in duplicate}))

    def test_locator_and_landing_contract(self) -> None:
        self.assertTrue(all(item["source_locator"]["locator_level"] == "record" for item in self.records))
        self.assertTrue(all(item["source_locator"]["view_state"]["datatable_ready"] for item in self.records))
        self.assertEqual({"base_affixes", "random_affixes"}, {
            item["source_locator"]["view_state"]["ethereal_prism_section"] for item in self.records
        })
        self.assertTrue(all(resolve_record_landing(item) for item in self.result["records"]))

    def test_search_text_excludes_occurrence_location_and_noise(self) -> None:
        random = [item for item in self.records if item["record_type"] == "ethereal_prism_random_affix"]
        with_location = [item for item in random if item.get("occurrence_location_text")]
        self.assertGreater(len(with_location), 0)
        self.assertTrue(all(item["occurrence_location_text"] not in item["search_text"] for item in with_location))
        forbidden = ("Calibrate_Ethereal_Prism", "DataTables_Table", "UI_", "<script", "<style")
        self.assertFalse(any(token in item["search_text"] for item in self.records for token in forbidden))

    def test_module_index_is_self_contained_and_global_index_is_untouched(self) -> None:
        global_after = json.loads((self.output / "structured-search-index.json").read_text(encoding="utf-8"))
        self.assertEqual(self.before, global_after)
        self.assertEqual(391, self.index["record_count"])
        search = json.loads((ROOT / "local_wiki/ss13/site/search-index.json").read_text(encoding="utf-8"))
        self.assertEqual(8, search["schema_version"])

    def test_search_ui_suppression_and_landing_parameters(self) -> None:
        self.assertIn("structuredEntities.has(hit.x.entity_id)", self.search_js)
        self.assertIn("!structuredEntities.has(hit.x.entity_id)", self.search_js)
        self.assertIn("structured_ethereal_prism_section", self.search_js)
        self.assertIn("structured_datatable_ready", self.search_js)
        self.assertIn("params.get('structured_ethereal_prism_section')", self.landing_js)

    def test_landing_waits_for_datatable_and_matches_outer_modifier_in_tbody(self) -> None:
        script = self.landing_js
        self.assertIn("etherealPrismSections={base_affixes:'基础词缀',random_affixes:'随机词缀'}", script)
        self.assertIn("pane.querySelector('table.DataTable tbody')", script)
        self.assertIn("jQuery.fn.DataTable.isDataTable(table)", script)
        self.assertIn("outerModifierTarget", script)
        self.assertIn("root.querySelectorAll('tr')", script)
        self.assertIn("row.querySelector('[data-modifier-id]')", script)
        self.assertIn("shown.bs.tab", script)
        self.assertIn("scrollIntoView", script)
        self.assertIn("const target=", script)
        self.assertIn("catch(_)", script)

    def test_structure_mismatch_emits_no_records(self) -> None:
        source = ROOT / "data/raw/manifests/inventory/raw_html/Ethereal_Prism.html"
        html = source.read_text(encoding="utf-8").replace(
            'id="基础词缀" class="tab-pane', 'id="Missing" class="tab-pane', 1
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "page.html"
            path.write_text(html, encoding="utf-8")
            result = EtherealPrismParser().parse(ParserInput(
                "ss13", "inventory", "Ethereal_Prism", "/cn/Ethereal_Prism/", path
            ))
        self.assertEqual("structure_mismatch", result["structure_validation"]["status"])
        self.assertEqual([], result["records"])

    def test_report_and_case_studies(self) -> None:
        self.assertEqual(391, self.report["record_counts"]["total"])
        self.assertEqual(391, self.report["unique_record_ids"])
        self.assertEqual(0, self.report["classification_errors"])
        self.assertEqual([], self.report["errors"])
        cases = self.report["case_studies"]
        self.assertTrue(all(cases[key]["record_id"] for key in (
            "base_plain", "base_nested", "random_plain", "random_nested"
        )))
        duplicate = cases["same_text_different_outer_modifier"]
        self.assertGreater(duplicate["record_count"], 1)
        self.assertEqual(duplicate["record_count"], len(set(duplicate["record_ids"])))


if __name__ == "__main__":
    unittest.main()
