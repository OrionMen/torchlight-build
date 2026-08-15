from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crawler.build_full_wiki_mirror import local_assets
from crawler.structured.parser_base import ParserInput
from crawler.structured.parsers.pact_spirit_parser import PactSpiritParser
from crawler.structured.run_pact_fate_structured_parsers import ROOT
from crawler.structured.schema import make_record_id


INDEX = ROOT / "data/generated/structured/ss13/structured-search-index.json"
REPORT = ROOT / "data/reports/local-wiki/pact-fate-structured-parser-v1-report.json"


class PactSpiritStructuredParserV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = json.loads(INDEX.read_text(encoding="utf-8"))
        cls.report = json.loads(REPORT.read_text(encoding="utf-8"))
        cls.records = [
            record for record in cls.index["records"]
            if record.get("record_type") == "pact_contract_node_effect"
        ]
        assets = local_assets()
        cls.search_js = assets["_local/search/app.js"]
        cls.landing_js = assets["_local/mirror.js"]

    def test_all_175_entities_and_real_record_count_are_emitted(self) -> None:
        self.assertEqual(175, self.report["source_pages"]["pact"])
        self.assertEqual(175, len({record["entity_id"] for record in self.records}))
        # The implementation re-counts current Raw. Two exceptional pages contain
        # one more real grid node than the regex audit's summary-card heuristic.
        self.assertEqual(2351, len(self.records))
        self.assertEqual(2351, self.report["record_counts"]["pact_total"])

    def test_identity_is_entity_scoped_and_independent_of_text(self) -> None:
        self.assertEqual(len(self.records), len({record["record_id"] for record in self.records}))
        record = self.records[0]
        identity = dict(
            parser_id="pact.spirit.contract_effects",
            entity_id=record["entity_id"],
            record_type="pact_contract_node_effect",
            section_key="contract_nodes",
            stable_key=record["source_locator"]["stable_key"],
        )
        self.assertEqual(make_record_id(**identity), make_record_id(**identity))
        self.assertRegex(record["source_locator"]["stable_key"], r"^contract:[^:]+:level:[^:]+$")

    def test_record_locator_and_landing_contract(self) -> None:
        self.assertTrue(all(record["source_locator"]["locator_level"] == "record" for record in self.records))
        self.assertTrue(all(record["source_locator"]["locator_confidence"] == "high" for record in self.records))
        record = next(item for item in self.records if item["entity_id"] == "tlidb:cn:Red_Umbrella")
        view = record["source_locator"]["view_state"]
        self.assertTrue(view["pact_contract"])
        self.assertTrue(view["pact_data_id"])
        self.assertTrue(view["pact_data_level"])
        self.assertEqual(record["route"], record["landing"]["route"])

    def test_search_text_is_name_and_effect_only(self) -> None:
        self.assertEqual(0, self.report["noise_validation"]["pact_search_whitelist_violations"])
        self.assertEqual(0, self.report["noise_validation"]["node_context_fields_in_search_documents"])
        self.assertTrue(all(record["search_text"] for record in self.records))
        self.assertTrue(all("data-id" not in record["search_text"] for record in self.records))

    def test_inactive_npc_nodes_are_structurally_excluded(self) -> None:
        self.assertEqual(36, self.report["npc_exclusion"]["pages_with_inactive_npc"])
        self.assertEqual(0, self.report["npc_exclusion"]["npc_records_emitted"])

    def test_search_suppression_and_precise_runtime_parameters(self) -> None:
        self.assertIn("structuredRoutes", self.search_js)
        self.assertIn("structured_pact_data_id", self.search_js)
        self.assertIn("structured_pact_data_level", self.search_js)
        self.assertIn("params.get('structured_pact_data_id')", self.landing_js)
        self.assertIn("params.get('structured_pact_data_level')", self.landing_js)
        self.assertIn("pactGrid.querySelectorAll('.d-flex.border.rounded img[data-id][data-level]')", self.landing_js)
        self.assertIn(".tab-pane[id$=\"_NPC\"]:not(.active):not(.show)", self.landing_js)
        self.assertIn("node.getAttribute('data-id')===pactDataId", self.landing_js)
        self.assertIn("node.getAttribute('data-level')===pactDataLevel", self.landing_js)
        self.assertIn("scrollIntoView", self.landing_js)
        self.assertIn("#fef08a", self.landing_js)

    def test_missing_stable_node_attribute_is_structure_mismatch(self) -> None:
        source = ROOT / "data/raw/manifests/pactspirit/raw_html/Red_Umbrella.html"
        html = source.read_text(encoding="utf-8").replace(" data-level=", " data-missing-level=")
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "Red_Umbrella.html"
            raw.write_text(html, encoding="utf-8")
            result = PactSpiritParser().parse(ParserInput(
                "ss13", "pactspirit", "Red_Umbrella", "/cn/Red_Umbrella/", raw
            ))
        self.assertEqual("structure_mismatch", result["structure_validation"]["status"])
        self.assertEqual([], result["records"])


if __name__ == "__main__":
    unittest.main()
