from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crawler.build_full_wiki_mirror import local_assets
from crawler.structured.parser_base import ParserInput
from crawler.structured.parsers.fate_parser import FateParser
from crawler.structured.run_pact_fate_structured_parsers import ROOT


ENTITY_INDEX = ROOT / "data/generated/entity-index-v3.json"
INDEX = ROOT / "data/generated/structured/ss13/structured-search-index.json"
REPORT = ROOT / "data/reports/local-wiki/pact-fate-structured-parser-v1-report.json"


class FateStructuredParserV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.entities = json.loads(ENTITY_INDEX.read_text(encoding="utf-8"))["entities"]
        cls.index = json.loads(INDEX.read_text(encoding="utf-8"))
        cls.report = json.loads(REPORT.read_text(encoding="utf-8"))
        cls.records = [
            record for record in cls.index["records"]
            if record.get("record_type") in {"fate_effect", "fate_entity_effect"}
        ]
        assets = local_assets()
        cls.search_js = assets["_local/search/app.js"]
        cls.landing_js = assets["_local/mirror.js"]

    def test_entity_linkage_is_193_including_recovered_and_undetermined(self) -> None:
        fate = [entity for entity in self.entities if entity.get("entity_type") == "fate"]
        self.assertEqual(193, len(fate))
        expected = {
            "tlidb:cn:Micro_Fate:_Deterioration_Duration",
            "tlidb:cn:Micro_Fate:_Trauma_Damage_Mitigation",
            "tlidb:cn:Undetermined_Fate",
        }
        actual = {entity["entity_id"] for entity in fate}
        self.assertTrue(expected <= actual)
        selected = [entity for entity in fate if entity["entity_id"] in expected]
        self.assertTrue(all(entity["content_category_id"] == "pact_spirit" for entity in selected))
        self.assertTrue(all(entity["content_subcategory_id"] == "pact_spirit_destiny" for entity in selected))

    def test_193_current_fate_records_and_history_exclusion(self) -> None:
        self.assertEqual(193, len(self.records))
        self.assertEqual(192, sum(record["record_type"] == "fate_effect" for record in self.records))
        self.assertEqual(1, sum(record["record_type"] == "fate_entity_effect" for record in self.records))
        self.assertEqual(0, self.report["historical_exclusion"]["historical_records_emitted"])
        self.assertEqual(190, self.report["historical_exclusion"]["pages_with_history"])

    def test_recovered_records_use_same_contract_and_classification(self) -> None:
        expected = {
            "tlidb:cn:Micro_Fate:_Deterioration_Duration",
            "tlidb:cn:Micro_Fate:_Trauma_Damage_Mitigation",
        }
        recovered = [record for record in self.records if record["entity_id"] in expected]
        self.assertEqual(2, len(recovered))
        self.assertTrue(all(record["source_system"] == "recovered_internal_pages" for record in recovered))
        self.assertTrue(all(record["content_category_id"] == "pact_spirit" for record in recovered))
        self.assertTrue(all(record["content_subcategory_id"] == "pact_spirit_destiny" for record in recovered))

    def test_undetermined_uses_honest_section_locator(self) -> None:
        record = next(item for item in self.records if item["entity_id"] == "tlidb:cn:Undetermined_Fate")
        self.assertEqual("fate_entity_effect", record["record_type"])
        self.assertEqual("section", record["source_locator"]["locator_level"])
        self.assertEqual("section:current_description2", record["source_locator"]["stable_key"])
        self.assertEqual('[data-block="description2"]', record["source_locator"]["section_selector"])
        self.assertEqual("current", record["landing"]["view_state"]["fate_state"])

    def test_landing_is_scoped_to_current_card_with_fallback(self) -> None:
        self.assertIn("structured_fate_state", self.search_js)
        self.assertIn("params.get('structured_fate_state')", self.landing_js)
        self.assertIn(".card.ui_item.popupItem:not(.previousItem)", self.landing_js)
        self.assertIn("root.querySelectorAll('[data-modifier-id]')", self.landing_js)
        self.assertIn("sectionSelector?root.querySelector(sectionSelector)", self.landing_js)
        self.assertIn("landing=target||root", self.landing_js)
        self.assertIn("scrollIntoView", self.landing_js)

    def test_missing_current_card_is_structure_mismatch(self) -> None:
        source = ROOT / "data/raw/manifests/destiny/raw_html/Micro_Fate%3A_Fire_Resistance.html"
        html = source.read_text(encoding="utf-8").replace("popupItem", "missingPopupItem", 1)
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "fate.html"
            raw.write_text(html, encoding="utf-8")
            result = FateParser().parse(ParserInput(
                "ss13", "destiny", "Micro_Fate:_Fire_Resistance",
                "/cn/Micro_Fate:_Fire_Resistance/", raw,
            ))
        self.assertEqual("structure_mismatch", result["structure_validation"]["status"])
        self.assertEqual([], result["records"])

    def test_merged_overlay_and_v1_search_schema(self) -> None:
        self.assertEqual(28780, self.index["record_count"])
        self.assertEqual(2544, self.report["search_merge"]["added"])
        self.assertEqual(22879, self.report["search_merge"]["previous_total"])
        v1 = json.loads((ROOT / "local_wiki/ss13/site/search-index.json").read_text(encoding="utf-8"))
        self.assertEqual(8, v1["schema_version"])
        self.assertIn("structuredRoutes.has(normalizeRoute(hit.x.route))", self.search_js)


if __name__ == "__main__":
    unittest.main()
