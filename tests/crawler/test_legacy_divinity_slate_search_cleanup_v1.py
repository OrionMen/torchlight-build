from __future__ import annotations

import json
import unittest
from pathlib import Path

from crawler.build_full_wiki_mirror import (
    LEGACY_DIVINITY_SLATE_SUBCATEGORY,
    apply_search_visibility_policy,
    local_assets,
)
from crawler.report_legacy_divinity_slate_search_cleanup_v1 import build_report


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "data/reports/local-wiki/legacy-divinity-slate-search-cleanup-v1.json"


class LegacyDivinitySlateSearchCleanupV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.search = json.loads(
            (ROOT / "local_wiki/ss13/site/search-index.json").read_text(encoding="utf-8")
        )
        cls.structured = json.loads(
            (ROOT / "data/generated/structured/ss13/structured-search-index.json").read_text(
                encoding="utf-8"
            )
        )
        cls.entities = json.loads(
            (ROOT / "data/generated/entity-index-v3.json").read_text(encoding="utf-8")
        )["entities"]
        cls.pages = cls.search["pages"]
        cls.legacy = [
            page for page in cls.pages
            if page.get("content_subcategory_id") == LEGACY_DIVINITY_SLATE_SUBCATEGORY
        ]
        cls.report = build_report(ROOT)
        cls.source_app = local_assets()["_local/search/app.js"]
        cls.deployed_app = (
            ROOT / "local_wiki/ss13/site/_local/search/app.js"
        ).read_text(encoding="utf-8")

    def test_legacy_scope_is_complete_and_preserved(self) -> None:
        self.assertEqual(11, len(self.legacy))
        self.assertEqual(
            {"inventory", "path_of_progression"},
            {page["system_id"] for page in self.legacy},
        )
        legacy_entities = [
            entity for entity in self.entities
            if entity.get("content_subcategory_id") == LEGACY_DIVINITY_SLATE_SUBCATEGORY
        ]
        self.assertEqual(11, len(legacy_entities))
        self.assertTrue((ROOT / "sources/path_of_progression_manifest.json").is_file())
        self.assertGreater(
            (ROOT / "data/raw/manifests/path_of_progression/raw_html/Divinity_Slate.html").stat().st_size,
            0,
        )

    def test_generation_policy_hides_every_legacy_page(self) -> None:
        hidden = [apply_search_visibility_policy(dict(page)) for page in self.legacy]
        self.assertTrue(hidden)
        self.assertTrue(all(page["entity_visibility"] == "hidden" for page in hidden))
        self.assertEqual(0, sum(page["entity_visibility"] != "hidden" for page in hidden))

    def test_common_queries_cannot_expose_legacy_results_after_policy(self) -> None:
        for query in ("全部", "技能等级", "中型天赋", "异界", "奖励", "累计击败"):
            with self.subTest(query=query):
                matches = [
                    apply_search_visibility_policy(dict(page))
                    for page in self.legacy
                    if query.casefold()
                    in f"{page.get('title', '')} {page.get('plain_text', '')}".casefold()
                ]
                self.assertFalse(any(page["entity_visibility"] != "hidden" for page in matches))

    def test_runtime_guard_protects_old_v1_and_structured_indexes(self) -> None:
        for script in (self.source_app, self.deployed_app):
            self.assertIn("const isLegacyDivinitySlate=", script)
            self.assertIn("x.content_subcategory_id==='talent_divinity_slate'", script)
            self.assertIn("isLegacyDivinitySlate(x)", script)
            self.assertIn("const matchesStructuredTree=x=>{if(isLegacyDivinitySlate(x))", script)

    def test_content_tree_has_only_current_talent_children(self) -> None:
        tree = json.loads((ROOT / "config/game_content_tree.json").read_text(encoding="utf-8"))
        talent = next(category for category in tree["search_categories"] if category["id"] == "talent_board")
        visible = {
            child["id"] for child in talent["children"]
            if child.get("search_visibility") != "hidden"
        }
        self.assertEqual(
            {
                "talent_hero",
                "talent_new_god",
                "talent_nether_king_entity",
                "talent_ethereal_prism",
            },
            visible,
        )
        self.assertNotIn(LEGACY_DIVINITY_SLATE_SUBCATEGORY, visible)

    def test_current_talent_search_and_structured_records_are_unchanged(self) -> None:
        expected = {
            "talent_hero": (30, 1013),
            "talent_new_god": (1, 36),
            "talent_nether_king_entity": (1, 92),
            "talent_ethereal_prism": (1, 391),
        }
        records = self.structured["records"]
        for subcategory, (page_count, record_count) in expected.items():
            with self.subTest(subcategory=subcategory):
                pages = [p for p in self.pages if p.get("content_subcategory_id") == subcategory]
                self.assertEqual(page_count, len(pages))
                self.assertTrue(all(p.get("entity_visibility") != "hidden" for p in pages))
                self.assertEqual(
                    record_count,
                    sum(r.get("content_subcategory_id") == subcategory for r in records),
                )

    def test_structured_and_search_schemas_are_unchanged(self) -> None:
        self.assertEqual(8, self.search["schema_version"])
        self.assertEqual(28780, self.structured["record_count"])
        self.assertEqual(0, sum(
            record.get("content_subcategory_id") == LEGACY_DIVINITY_SLATE_SUBCATEGORY
            for record in self.structured["records"]
        ))

    def test_report_is_valid_and_has_no_errors(self) -> None:
        self.assertEqual([], self.report["errors"])
        self.assertEqual(11, self.report["before"]["visible_page_results"])
        self.assertEqual(0, self.report["after"]["visible_divinity_slate_results"])
        self.assertFalse(self.report["content_tree_status"]["legacy_primary_entry_present"])
        if REPORT.is_file():
            self.assertIsInstance(json.loads(REPORT.read_text(encoding="utf-8")), dict)


if __name__ == "__main__":
    unittest.main()
