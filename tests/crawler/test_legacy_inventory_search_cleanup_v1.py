from __future__ import annotations

import json
import unittest
from pathlib import Path

from crawler.build_full_wiki_mirror import apply_search_visibility_policy, local_assets


ROOT = Path(__file__).resolve().parents[2]
V1_INDEX = ROOT / "local_wiki/ss13/site/search-index.json"
STRUCTURED_INDEX = ROOT / "data/generated/structured/ss13/structured-search-index.json"
DEPLOYED_APP = ROOT / "local_wiki/ss13/site/_local/search/app.js"


class LegacyInventorySearchCleanupV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v1 = json.loads(V1_INDEX.read_text(encoding="utf-8"))
        cls.pages = cls.v1["pages"]
        cls.structured = json.loads(STRUCTURED_INDEX.read_text(encoding="utf-8"))
        cls.fragrance = [
            record for record in cls.structured["records"]
            if record.get("record_type") == "fragrance_affix"
        ]
        cls.source_app = local_assets()["_local/search/app.js"]
        cls.deployed_app = DEPLOYED_APP.read_text(encoding="utf-8")

    @staticmethod
    def visible(page: dict) -> bool:
        legacy_inventory_fallback = (
            page.get("system_id") == "inventory"
            and not page.get("content_category_id")
            and not page.get("content_subcategory_id")
            and not page.get("entity_type")
        )
        return page.get("entity_visibility") != "hidden" and not legacy_inventory_fallback

    def page(self, page_id: str) -> dict:
        return next(page for page in self.pages if page.get("id") == page_id)

    def test_sandlord_is_legacy_unclassified_inventory_fallback(self) -> None:
        page = self.page("Sandlord_Season")
        self.assertEqual("inventory", page["system_id"])
        self.assertIsNone(page["entity_type"])
        self.assertIsNone(page["content_category_id"])
        self.assertIsNone(page["content_subcategory_id"])
        self.assertFalse(self.visible(page))

        legacy = [
            item for item in self.pages
            if item.get("system_id") == "inventory"
            and not item.get("content_category_id")
            and not item.get("content_subcategory_id")
            and not item.get("entity_type")
        ]
        self.assertGreater(len(legacy), 0)
        self.assertFalse(any(self.visible(item) for item in legacy))

    def test_builder_visibility_policy_marks_legacy_inventory_hidden(self) -> None:
        page = {
            "system_id": "inventory",
            "entity_type": None,
            "entity_visibility": "visible",
            "content_category_id": None,
            "content_subcategory_id": None,
        }
        apply_search_visibility_policy(page)
        self.assertEqual("hidden", page["entity_visibility"])

    def test_formally_classified_inventory_content_is_not_hidden(self) -> None:
        expected = {
            "STR_Helmet": ("equipment", "equipment_craft"),
            "Vorax_Limb:_Head": ("equipment", "equipment_vorax"),
            "Ethereal_Prism": ("talent_board", "talent_ethereal_prism"),
        }
        for page_id, classification in expected.items():
            with self.subTest(page_id=page_id):
                page = dict(self.page(page_id))
                apply_search_visibility_policy(page)
                self.assertEqual(classification, (
                    page["content_category_id"], page["content_subcategory_id"]
                ))
                self.assertNotEqual("hidden", page["entity_visibility"])
                self.assertTrue(self.visible(page))

        legendary = self.page("Necklace_of_Firebird")
        self.assertEqual(("equipment", "equipment_legendary"), (
            legendary["content_category_id"], legendary["content_subcategory_id"]
        ))
        self.assertTrue(self.visible(legendary))

    def test_runtime_has_explicit_legacy_inventory_guard(self) -> None:
        for script in (self.source_app, self.deployed_app):
            self.assertIn("const isLegacyInventoryFallback=", script)
            self.assertIn("x.system_id==='inventory'", script)
            self.assertIn("!x.content_category_id&&!x.content_subcategory_id&&!x.entity_type", script)
            self.assertIn("isLegacyInventoryFallback(x)", script)

    def test_fragrance_structured_records_and_classification_are_complete(self) -> None:
        self.assertEqual(97, len(self.fragrance))
        self.assertTrue(all(record["entity_id"] == "tlidb:cn:Blending_Rituals" for record in self.fragrance))
        self.assertTrue(all(record["content_category_id"] == "equipment_related" for record in self.fragrance))
        self.assertTrue(all(record["content_subcategory_id"] == "equipment_related_fragrance" for record in self.fragrance))
        self.assertTrue(all(record["route"] == "/cn/Blending_Rituals/" for record in self.fragrance))
        self.assertTrue(all(record["search_text"] for record in self.fragrance))

    def test_real_fragrance_match_suppresses_v1_page_result(self) -> None:
        query = "从胸甲获得"
        structured_matches = [
            record for record in self.fragrance
            if query.casefold() in record["search_text"].casefold()
        ]
        self.assertTrue(structured_matches)
        structured_entities = {record["entity_id"] for record in structured_matches}
        v1 = next(page for page in self.pages if page.get("entity_id") == "tlidb:cn:Blending_Rituals")
        self.assertIn(query, v1["plain_text"])
        visible_v1 = [v1] if v1["entity_id"] not in structured_entities else []
        self.assertEqual([], visible_v1)
        self.assertIn("!structuredEntities.has(hit.x.entity_id)", self.source_app)

    def test_no_structured_match_keeps_blending_rituals_v1_fallback(self) -> None:
        query = "调香秘仪 /97"
        self.assertFalse(any(query.casefold() in record["search_text"].casefold() for record in self.fragrance))
        page = next(page for page in self.pages if page.get("entity_id") == "tlidb:cn:Blending_Rituals")
        self.assertIn(query, page["title"])
        self.assertIn("const displayHits=collapseEntityHits(hits.filter", self.source_app)

    def test_generated_runtime_retains_inventory_guard_and_search_schema_stays_8(self) -> None:
        # Full Build is deliberately outside later Structured Parser tasks, so the
        # checked-in generated runtime may trail the source asset until that build.
        self.assertIn("const isLegacyInventoryFallback=", self.deployed_app)
        self.assertEqual(8, self.v1["schema_version"])
        self.assertEqual(28780, self.structured["record_count"])


if __name__ == "__main__":
    unittest.main()
