from __future__ import annotations

import json
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

from crawler.build_full_wiki_mirror import local_assets
from crawler.structured.parser_base import ParserInput
from crawler.structured.parsers.talent_node_parser import TalentNodeParser
from crawler.structured.schema import make_record_id


ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "data/generated/structured/ss13/structured-search-index.json"
REPORT = ROOT / "data/reports/local-wiki/remaining-talent-structured-parser-v1-report.json"
RAW_ROOT = ROOT / "data/raw/manifests/talent/raw_html"


class RemainingTalentStructuredParserV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = json.loads(INDEX.read_text(encoding="utf-8"))
        cls.records = [record for record in cls.index["records"] if record["record_type"] == "talent_node"]
        cls.report = json.loads(REPORT.read_text(encoding="utf-8"))
        assets = local_assets()
        cls.search_script = assets["_local/search/app.js"]
        cls.landing_script = assets["_local/mirror.js"]

    def test_entity_and_record_coverage(self) -> None:
        self.assertEqual(32, self.report["talent_entities"])
        self.assertEqual(32, self.report["structure_matched"])
        self.assertEqual(0, self.report["structure_mismatches"])
        self.assertEqual({"talent_hero": 30, "talent_new_god": 1, "talent_nether_king_entity": 1}, self.report["subcategory_counts"])
        self.assertEqual(1141, len(self.records))
        self.assertEqual({"talent_hero": 1013, "talent_new_god": 36, "talent_nether_king_entity": 92}, self.report["record_counts_by_subcategory"])
        self.assertEqual(28780, self.index["record_count"])

    def test_native_identity_is_unique_high_confidence_and_stable(self) -> None:
        self.assertEqual(1141, len({record["record_id"] for record in self.records}))
        self.assertEqual({"high": 1141}, self.report["identity_confidence"])
        coverage = self.report["data_talent_id_coverage"]
        self.assertEqual(1141, coverage["with_id"])
        self.assertEqual(1141, coverage["unique"])
        first = self.records[0]
        expected = make_record_id(
            parser_id=TalentNodeParser.parser_id, entity_id=first["entity_id"],
            record_type="talent_node", section_key="talent_nodes",
            stable_key=first["source_locator"]["stable_key"],
        )
        self.assertEqual(first["record_id"], expected)
        self.assertNotIn(first["text"], first["source_locator"]["stable_key"])

    def test_historical_support_and_legacy_scopes_are_excluded(self) -> None:
        self.assertEqual(0, self.report["historical_records_emitted"])
        self.assertEqual(0, self.report["support_cache_records_emitted"])
        noise = self.report["noise_validation"]
        self.assertEqual(0, noise["inactive_pane_records"])
        self.assertEqual(0, noise["cache_records"])
        self.assertEqual(0, noise["profession_tree_records"])
        self.assertEqual(0, noise["item_records"])
        self.assertEqual(0, noise["divinity_slate_records"])

    def test_nested_modifiers_remain_inside_nether_king_nodes(self) -> None:
        nested = self.report["nested_modifier_nodes"]
        self.assertEqual(9, nested["nodes"])
        self.assertEqual(9, nested["modifier_ids"])
        self.assertEqual(0, nested["extra_records_emitted"])
        nether = [record for record in self.records if record["entity_id"] == "tlidb:cn:Nether_King"]
        self.assertEqual(92, len(nether))
        self.assertTrue(all(record["source_locator"]["stable_key"].startswith("talent:") for record in nether))
        self.assertTrue(self.report["landing"]["nested_modifier_protection"])

    def test_same_text_different_talent_ids_remain_distinct(self) -> None:
        groups = defaultdict(list)
        for record in self.records:
            groups[record["text"]].append(record)
        duplicate = next(items for items in groups.values() if len({item["talent_id"] for item in items}) > 1)
        self.assertGreater(len(duplicate), 1)
        self.assertEqual(len(duplicate), len({item["record_id"] for item in duplicate}))
        self.assertGreater(self.report["same_text_different_talent_ids"], 0)

    def test_classification_inherits_current_entity(self) -> None:
        expected = {
            "tlidb:cn:God_of_War": "talent_hero",
            "tlidb:cn:New_God": "talent_new_god",
            "tlidb:cn:Nether_King": "talent_nether_king_entity",
        }
        for entity_id, subcategory in expected.items():
            selected = [record for record in self.records if record["entity_id"] == entity_id]
            self.assertTrue(selected)
            self.assertTrue(all(record["content_category_id"] == "talent_board" for record in selected))
            self.assertTrue(all(record["content_subcategory_id"] == subcategory for record in selected))
        self.assertEqual(0, self.report["classification_errors"])

    def test_existing_structured_records_and_v1_schema_are_preserved(self) -> None:
        merge = self.report["structured_search"]
        self.assertEqual(25754, merge["previous_total"])
        self.assertEqual(1141, merge["added"])
        self.assertEqual(26895, merge["new_total"])
        self.assertEqual(25754, merge["existing_record_ids_preserved"])
        v1 = json.loads((ROOT / "local_wiki/ss13/site/search-index.json").read_text(encoding="utf-8"))
        self.assertEqual(8, v1["schema_version"])

    def test_page_suppression_and_structured_result_contract(self) -> None:
        self.assertIn("structuredEntities.has(hit.x.entity_id)", self.search_script)
        self.assertIn("!structuredRoutes.has(normalizeRoute(hit.x.route))", self.search_script)
        self.assertTrue(self.report["page_suppression"]["v1_fallback_without_structured_match"])
        self.assertIn("structured-record-type", self.search_script)

    def test_landing_is_scoped_by_container_and_native_talent_id(self) -> None:
        for token in ("structured_talent_container", "structured_talent_root", "structured_talent_id"):
            self.assertIn(token, self.search_script)
            self.assertIn(token, self.landing_script)
        self.assertIn("root.querySelectorAll('[data-talent-id]')", self.landing_script)
        self.assertIn("node.getAttribute('data-talent-id')===talentId", self.landing_script)
        self.assertIn("marker.closest('.d-flex.border-top.rounded')", self.landing_script)
        self.assertNotIn("document.querySelectorAll('[data-talent-id]')", self.landing_script)
        self.assertIn("trigger.addEventListener('shown.bs.tab'", self.landing_script)
        self.assertIn("filter.value=''", self.landing_script)
        self.assertIn("scrollIntoView", self.landing_script)
        self.assertIn("row.style.backgroundColor='#fef08a'", self.landing_script)
        self.assertIn("landing=target||root", self.landing_script)

    def test_case_studies_and_machinist_discrepancy(self) -> None:
        expected = {"God_of_War": 30, "God_of_Might": 32, "Machinist": 32, "New_God": 36, "Nether_King": 92}
        for slug, count in expected.items():
            self.assertEqual(count, self.report["case_studies"][slug]["records"])
        discrepancy = self.report["machinist_summary_discrepancy"]
        self.assertEqual(32, discrepancy["dom_records"])
        self.assertEqual(31, discrepancy["entity_summary_records"])

    def test_structure_mismatch_does_not_emit_partial_records(self) -> None:
        html = (RAW_ROOT / "God_of_War.html").read_text(encoding="utf-8")
        broken = html.replace('data-talent-id="', 'data-missing-talent-id="', 1)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "broken.html"
            path.write_text(broken, encoding="utf-8")
            result = TalentNodeParser().parse(ParserInput(
                "ss13", "talent", "God_of_War", "/cn/God_of_War/", path,
            ))
        self.assertEqual("structure_mismatch", result["structure_validation"]["status"])
        self.assertEqual([], result["records"])


if __name__ == "__main__":
    unittest.main()
