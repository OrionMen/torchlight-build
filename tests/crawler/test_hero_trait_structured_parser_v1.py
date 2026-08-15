from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

from crawler.build_full_wiki_mirror import local_assets
from crawler.structured.parser_base import ParserInput
from crawler.structured.parsers.hero_trait_parser import HeroTraitParser
from crawler.structured.schema import make_record_id


ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = ROOT / "data/raw/manifests/hero/raw_html"
INDEX = ROOT / "data/generated/structured/ss13/structured-search-index.json"
REPORT = ROOT / "data/reports/local-wiki/hero-trait-structured-parser-v1-report.json"


class HeroTraitStructuredParserV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = json.loads(INDEX.read_text(encoding="utf-8"))
        cls.records = [
            record for record in cls.index["records"]
            if record["record_type"] == "hero_trait_effect"
        ]
        cls.report = json.loads(REPORT.read_text(encoding="utf-8"))
        assets = local_assets()
        cls.search_script = assets["_local/search/app.js"]
        cls.landing_script = assets["_local/mirror.js"]

    def test_all_entities_and_records_are_generated(self) -> None:
        self.assertEqual(27, self.report["hero_entities"])
        self.assertEqual(27, self.report["structure_matched"])
        self.assertEqual(0, self.report["structure_mismatches"])
        self.assertEqual(331, len(self.records))
        self.assertEqual(331, len({record["record_id"] for record in self.records}))
        self.assertEqual(28780, self.index["record_count"])
        self.assertEqual(25423, self.report["structured_search"]["previous_total"])

    def test_identity_is_explicitly_medium_and_stable(self) -> None:
        self.assertTrue(all(record["identity_confidence"] == "medium" for record in self.records))
        self.assertTrue(all(record["source_locator"]["locator_confidence"] == "medium" for record in self.records))
        first = self.records[0]
        identity = dict(
            parser_id=HeroTraitParser.parser_id, entity_id=first["entity_id"],
            record_type=first["record_type"], section_key="hero_trait_effects",
            stable_key=first["source_locator"]["stable_key"],
        )
        self.assertEqual(first["record_id"], make_record_id(**identity))
        self.assertEqual(first["record_id"], make_record_id(**identity))
        self.assertNotIn(first["text"], first["source_locator"]["stable_key"])

    def test_level_and_case_study_counts(self) -> None:
        self.assertEqual(187, self.report["records_with_level"])
        self.assertEqual(144, self.report["records_without_level"])
        self.assertEqual(331, self.report["medium_identity_records"])
        self.assertEqual(0, self.report["identity_unresolved"])
        expected = {
            "Anger": 10,
            "Creative_Genius": 28,
            "Zealot_of_War": 22,
            "Incarnation_of_the_Gods": 11,
        }
        for slug, count in expected.items():
            with self.subTest(slug=slug):
                self.assertEqual(count, self.report["case_studies"][slug]["records"])

    def test_duplicate_asset_is_disambiguated_by_scoped_occurrence(self) -> None:
        records = [
            record for record in self.records
            if record["entity_id"] == "tlidb:cn:Incarnation_of_the_Gods"
            and record["source_locator"]["view_state"]["hero_trait_asset_key"] == "UIYueNv033"
        ]
        self.assertEqual(2, len(records))
        self.assertEqual({1, 2}, {
            record["source_locator"]["view_state"]["hero_trait_asset_occurrence"]
            for record in records
        })
        self.assertEqual(2, len({record["source_locator"]["stable_key"] for record in records}))
        self.assertEqual(1, self.report["duplicate_asset_resolution"]["duplicate_groups_before_scoped_occurrence"])
        self.assertEqual(0, self.report["duplicate_asset_resolution"]["duplicate_groups_after_scoped_occurrence"])

    def test_structured_search_classification_and_noise_contract(self) -> None:
        self.assertTrue(all(record["entity_type"] == "hero" for record in self.records))
        self.assertTrue(all(record["content_category_id"] == "hero" for record in self.records))
        self.assertTrue(all(record["content_subcategory_id"] == "hero_trait" for record in self.records))
        self.assertEqual(0, self.report["classification_errors"])
        noise = self.report["noise_validation"]
        self.assertEqual(0, noise["skill_shop_records"])
        self.assertEqual(0, noise["boon_records"])
        self.assertEqual(0, noise["hero_memory_records"])
        self.assertEqual(0, noise["asset_key_in_search_text"])

    def test_landing_contract_contains_scoped_asset_occurrence_and_level(self) -> None:
        tiered = next(record for record in self.records if record["trait_level"] is not None)
        landing = tiered["landing"]
        self.assertEqual("record", landing["locator_level"])
        self.assertEqual(tiered["route"], landing["route"])
        view = landing["view_state"]
        self.assertTrue(view["hero_trait_tab"].startswith("#"))
        self.assertTrue(view["hero_trait_asset_key"])
        self.assertGreaterEqual(view["hero_trait_asset_occurrence"], 1)
        self.assertNotIn("hero_trait_level", view)
        self.assertEqual(tiered["source_locator"]["stable_key"], landing["record_key"])

    def test_search_url_and_browser_landing_runtime(self) -> None:
        for token in (
            "structured_hero_trait_tab", "structured_hero_trait_asset",
            "structured_hero_trait_occurrence", "structured_hero_trait_level",
        ):
            self.assertIn(token, self.search_script)
            self.assertIn(token, self.landing_script)
        self.assertIn("heroTraitTab?pane", self.landing_script)
        self.assertIn("pane.querySelectorAll('.d-flex.border-top.rounded')", self.landing_script)
        self.assertIn("icon.getAttribute('alt')===heroTraitAsset", self.landing_script)
        self.assertIn("nodes[Number(heroTraitOccurrence)-1]", self.landing_script)
        self.assertIn("x.trait_level!==null&&x.trait_level!==undefined", self.search_script)
        self.assertIn("item.textContent.trim()===label", self.landing_script)
        self.assertIn("trigger.addEventListener('shown.bs.tab'", self.landing_script)
        self.assertIn("scrollIntoView", self.landing_script)
        self.assertIn("row.style.backgroundColor='#fef08a'", self.landing_script)
        self.assertNotIn("document.querySelectorAll('img[alt]')", self.landing_script)

    def test_structure_mismatch_does_not_emit_records(self) -> None:
        slug = "Anger"
        source = RAW_ROOT / f"{quote(slug, safe='-_.')}.html"
        html = source.read_text(encoding="utf-8")
        broken = html.replace('class="tab-pane fade show active"', 'class="tab-pane fade"', 1)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "broken.html"
            path.write_text(broken, encoding="utf-8")
            result = HeroTraitParser().parse(ParserInput(
                "ss13", "hero", slug, f"/cn/{slug}/", path,
            ))
        self.assertEqual("structure_mismatch", result["structure_validation"]["status"])
        self.assertEqual([], result["records"])


if __name__ == "__main__":
    unittest.main()
