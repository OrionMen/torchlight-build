from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from crawler.build_full_wiki_mirror import local_assets
from crawler.structured.parser_base import ParserInput
from crawler.structured.parsers.equipment_related_parser import (
    FRAGRANCE,
    TOWER_SEQUENCE,
    EquipmentRelatedParser,
)
from crawler.structured.run_equipment_related_parser import ROOT, generate
from crawler.structured.schema import make_record_id


SOURCE_INDEX = ROOT / "data/generated/structured/ss13/structured-search-index.json"


class EquipmentRelatedStructuredParserV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temporary.name) / "structured"
        cls.output.mkdir()
        shutil.copy2(SOURCE_INDEX, cls.output / "structured-search-index.json")
        cls.before = json.loads(SOURCE_INDEX.read_text(encoding="utf-8"))
        cls.results, cls.index, cls.report = generate(
            ROOT, cls.output, Path(cls.temporary.name) / "report.json"
        )
        cls.records = [
            record for record in cls.index["records"]
            if record.get("entity_type") == "equipment_related_system"
        ]
        assets = local_assets()
        cls.search_js = assets["_local/search/app.js"]
        cls.landing_js = assets["_local/mirror.js"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_505_records_and_subtype_distributions(self) -> None:
        fragrance = [item for item in self.records if item["record_type"] == "fragrance_affix"]
        tower = [item for item in self.records if item["record_type"] == "tower_sequence_affix"]
        self.assertEqual(97, len(fragrance))
        self.assertEqual(408, len(tower))
        self.assertEqual(505, len(self.records))
        self.assertEqual({"medium": 36, "core": 55, "exotic": 6}, Counter(item["talent_type"] for item in fragrance))
        self.assertEqual({"intermediate": 220, "advanced": 188}, Counter(item["sequence_tier"] for item in tower))

    def test_identity_locator_and_structure_contract(self) -> None:
        self.assertEqual(505, len({item["record_id"] for item in self.records}))
        self.assertTrue(all(item["source_locator"]["locator_level"] == "record" for item in self.records))
        self.assertTrue(all(item["source_locator"]["stable_key"].startswith("modifier:") for item in self.records))
        self.assertTrue(all(result["structure_validation"]["status"] == "matched" for result in self.results))
        identity = dict(
            parser_id="equipment_related.system.affixes",
            entity_id="tlidb:cn:Blending_Rituals",
            record_type="fragrance_affix",
            section_key="fragrance",
            stable_key="modifier:3401000",
        )
        self.assertEqual(make_record_id(**identity), make_record_id(**identity))

    def test_fragrance_metadata_is_preserved_but_not_search_noise(self) -> None:
        record = next(item for item in self.records if item["record_type"] == "fragrance_affix")
        self.assertTrue(record["recipe_id"])
        self.assertTrue(record["recipe_materials"])
        self.assertIn(record["talent_type_name_zh"], record["search_text"])
        self.assertNotIn(record["recipe_id"], record["search_text"])
        self.assertTrue(all(material["name_zh"] not in record["search_text"] for material in record["recipe_materials"]))
        self.assertEqual(0, self.report["noise_validation"]["materials_in_search_text"])

    def test_tower_context_is_preserved_and_duplicate_text_is_not_deduplicated(self) -> None:
        tower = [item for item in self.records if item["record_type"] == "tower_sequence_affix"]
        self.assertEqual(22, len({item["equipment_type"] for item in tower}))
        duplicate = self.report["case_studies"]["tower"]["duplicate_text"]
        self.assertGreater(duplicate["records"], 1)
        self.assertEqual(duplicate["records"], duplicate["unique_record_ids"])
        self.assertGreater(len(duplicate["equipment_types"]), 1)

    def test_structured_search_queries_and_classification(self) -> None:
        self.assertGreater(self.report["case_studies"]["tower"]["fire_penetration_matches"], 0)
        self.assertGreater(self.report["case_studies"]["tower"]["all_attribute_matches"], 0)
        self.assertEqual(19, self.report["case_studies"]["tower"]["bow_matches"])
        self.assertEqual(0, self.report["classification_errors"])
        self.assertTrue(all(item["content_category_id"] == "equipment_related" for item in self.records))
        self.assertEqual({
            "equipment_related_fragrance", "equipment_related_tower_sequence",
        }, {item["content_subcategory_id"] for item in self.records})

    def test_module_index_is_self_contained_and_global_index_is_untouched(self) -> None:
        global_after = json.loads((self.output / "structured-search-index.json").read_text(encoding="utf-8"))
        self.assertEqual(self.before, global_after)
        self.assertEqual(505, self.index["record_count"])
        self.assertEqual(8, json.loads((ROOT / "local_wiki/ss13/site/search-index.json").read_text(encoding="utf-8"))["schema_version"])

    def test_search_ui_suppression_search_fields_and_landing_parameters(self) -> None:
        self.assertIn("x.search_text||x.text", self.search_js)
        self.assertIn("structuredEntities.has(hit.x.entity_id)", self.search_js)
        self.assertIn("!structuredEntities.has(hit.x.entity_id)", self.search_js)
        self.assertIn("structured_equipment_related_section", self.search_js)
        self.assertIn("structured_datatable_ready", self.search_js)
        self.assertIn("view.filter_reset", self.search_js)
        self.assertIn("params.get('structured_equipment_related_section')", self.landing_js)
        self.assertIn("params.get('structured_datatable_ready')", self.landing_js)

    def test_filter_reset_datatable_wait_scoped_lookup_and_fallback(self) -> None:
        script = self.landing_js
        self.assertIn("filter.value=''", script)
        self.assertIn("filter.dispatchEvent(new Event('input'", script)
        self.assertIn("jQuery.fn.DataTable.isDataTable(table)", script)
        self.assertIn("pane.querySelector('table.DataTable tbody')", script)
        self.assertIn("root.querySelectorAll('[data-modifier-id]')", script)
        self.assertIn("const target=", script)
        self.assertIn("attempt<20", script)
        self.assertIn("shown.bs.tab", script)
        self.assertIn("scrollIntoView", script)
        self.assertIn("try{", script)
        self.assertIn("catch(_)", script)

    def test_missing_required_structure_emits_no_records(self) -> None:
        source = ROOT / "data/raw/manifests/help/raw_html/Blending_Rituals.html"
        html = source.read_text(encoding="utf-8").replace('id="调香秘仪" class="tab-pane', 'id="Missing" class="tab-pane', 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "page.html"
            path.write_text(html, encoding="utf-8")
            result = EquipmentRelatedParser(FRAGRANCE).parse(ParserInput(
                "ss13", "help", FRAGRANCE.canonical_id, FRAGRANCE.route, path
            ))
        self.assertEqual("structure_mismatch", result["structure_validation"]["status"])
        self.assertEqual([], result["records"])

    def test_real_case_studies_cover_requested_shapes(self) -> None:
        fragrance = self.report["case_studies"]["fragrance"]
        tower = self.report["case_studies"]["tower"]
        self.assertTrue(all(fragrance[key]["record_id"] for key in ("medium", "core", "exotic", "multi_line")))
        self.assertTrue(all(tower[key]["record_id"] for key in ("intermediate", "advanced", "bow", "single_handed", "shield")))
        for record in self.records:
            self.assertIn("landing", record)


if __name__ == "__main__":
    unittest.main()
