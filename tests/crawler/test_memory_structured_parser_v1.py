from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crawler.build_full_wiki_mirror import local_assets
from crawler.structured.parser_base import ParserInput
from crawler.structured.parsers.memory_structured_parser import (
    HERO_MEMORY_SOURCE,
    MEMORY_REVIVAL_SOURCE,
    MemoryStructuredParser,
)
from crawler.structured.run_memory_structured_parser import ROOT, generate
from crawler.structured.schema import make_record_id


INDEX = ROOT / "data/generated/structured/ss13/structured-search-index.json"
REPORT = ROOT / "data/reports/local-wiki/memory-structured-parser-v1-report.json"


class MemoryStructuredParserV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = json.loads(INDEX.read_text(encoding="utf-8"))
        cls.report = json.loads(REPORT.read_text(encoding="utf-8"))
        cls.records = [record for record in cls.index["records"] if record.get("entity_type") == "memory_system"]
        assets = local_assets()
        cls.search_js = assets["_local/search/app.js"]
        cls.landing_js = assets["_local/mirror.js"]

    def test_one_entity_two_sources_five_sections_and_755_records(self) -> None:
        self.assertEqual(1, self.report["memory_entities"])
        self.assertEqual(2, self.report["source_pages"])
        self.assertEqual(2, self.report["structure_matched"])
        self.assertEqual(0, self.report["structure_mismatches"])
        self.assertEqual(755, len(self.records))
        self.assertEqual(755, self.report["record_counts"]["total"])
        self.assertEqual(5, len({record["record_type"] for record in self.records}))

    def test_identity_locator_and_classification(self) -> None:
        self.assertEqual(755, len({record["record_id"] for record in self.records}))
        self.assertEqual(1.0, self.report["stable_key_coverage"])
        self.assertEqual(755, self.report["record_level_locators"])
        self.assertTrue(all(record["entity_id"] == "tlidb:cn:Hero_Memories" for record in self.records))
        self.assertTrue(all(
            record["content_category_id"] == "memory"
            and record["content_subcategory_id"] == "hero_memory"
            for record in self.records
        ))

    def test_record_id_ignores_text_season_and_row(self) -> None:
        identity = dict(
            parser_id="memory.hero_memory.affixes",
            entity_id="tlidb:cn:Hero_Memories",
            record_type="memory_fixed_affix",
            section_key="fixed_affix",
            stable_key="modifier:402151201",
        )
        self.assertEqual(make_record_id(**identity), make_record_id(**identity))

    def test_section_whitelist_and_noise_exclusion(self) -> None:
        self.assertEqual(0, self.report["noise_validation"]["non_whitelisted_section_records"])
        self.assertEqual(0, self.report["noise_validation"]["metadata_column_records"])
        self.assertEqual(0, self.report["noise_validation"]["forbidden_text_records"])
        self.assertEqual({
            "基础属性", "固有词缀", "随机词缀", "复苏词缀", "复苏词缀（月相）",
        }, {record["section_name"] for record in self.records})

    def test_supplemental_records_keep_entity_but_land_on_revival(self) -> None:
        revival = [record for record in self.records if record["record_type"].startswith("memory_revival")]
        self.assertEqual(80, len(revival))
        self.assertTrue(all(record["route"] == "/cn/Memory_Revival/" for record in revival))
        self.assertTrue(all(record["source_page_id"] == "Memory_Revival" for record in revival))
        self.assertEqual(80, self.report["supplemental_source_landing"]["correct_route_count"])
        self.assertEqual(15, self.report["landing"]["base_attribute"])
        self.assertEqual(44, self.report["landing"]["revival_moon_affix"])

    def test_real_records_and_all_attribute_search(self) -> None:
        for record_type in (
            "memory_base_attribute", "memory_fixed_affix", "memory_random_affix",
            "memory_revival_affix", "memory_revival_moon_affix",
        ):
            self.assertTrue(any(record["record_type"] == record_type and record["text"] for record in self.records))
        self.assertGreater(self.report["case_studies"]["all_attribute_search"]["match_count"], 0)
        self.assertTrue(any("全属性" in record["text"] for record in self.records))

    def test_existing_structured_records_and_v1_schema_are_preserved(self) -> None:
        self.assertEqual(28780, self.index["record_count"])
        self.assertEqual(28025, sum(record.get("entity_type") != "memory_system" for record in self.index["records"]))
        self.assertEqual(8, json.loads((ROOT / "local_wiki/ss13/site/search-index.json").read_text(encoding="utf-8"))["schema_version"])

    def test_ui_suppression_and_memory_view_state_contract(self) -> None:
        self.assertIn("structuredEntities.has(hit.x.entity_id)", self.search_js)
        self.assertIn("!structuredEntities.has(hit.x.entity_id)", self.search_js)
        self.assertIn("structured_memory_section", self.search_js)
        self.assertIn("params.get('structured_memory_section')", self.landing_js)
        self.assertIn("root.querySelectorAll('[data-modifier-id]')", self.landing_js)
        self.assertNotIn("document.querySelectorAll('[data-modifier-id]')", self.landing_js)
        self.assertIn("shown.bs.tab", self.landing_js)
        self.assertIn("scrollIntoView", self.landing_js)
        self.assertIn("#fef08a", self.landing_js)

    def test_structure_mismatch_emits_no_records(self) -> None:
        source = ROOT / "data/raw/manifests/inventory/raw_html/Hero_Memories.html"
        html = source.read_text(encoding="utf-8").replace('id="基础属性" class="tab-pane', 'id="Missing" class="tab-pane', 1)
        with tempfile.TemporaryDirectory() as temporary:
            raw = Path(temporary) / "Hero_Memories.html"
            raw.write_text(html, encoding="utf-8")
            result = MemoryStructuredParser(HERO_MEMORY_SOURCE).parse(ParserInput(
                "ss13", "inventory", "Hero_Memories", "/cn/Hero_Memories/", raw
            ))
        self.assertEqual("structure_mismatch", result["structure_validation"]["status"])
        self.assertEqual([], result["records"])

    def test_generator_writes_only_its_self_contained_module_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "structured"
            output.mkdir()
            existing = [record for record in self.index["records"] if record.get("entity_type") != "memory_system"]
            (output / "structured-search-index.json").write_text(json.dumps({
                "schema_version": 1, "season_id": "ss13", "record_count": len(existing), "records": existing,
            }), encoding="utf-8")
            _, generated, report = generate(ROOT, output, Path(temporary) / "report.json")
            untouched = json.loads((output / "structured-search-index.json").read_text(encoding="utf-8"))
        self.assertEqual(755, generated["record_count"])
        self.assertEqual(len(existing), untouched["record_count"])
        self.assertEqual(755, report["record_counts"]["total"])


if __name__ == "__main__":
    unittest.main()
