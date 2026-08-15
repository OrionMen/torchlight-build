from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crawler.generate_entity_index_v3 import build_entity_index_v3
from crawler.recover_legendary_refetch_v1 import (
    NON_EQUIPMENT_IDS,
    build_recovery_report,
    refresh_search_ownership,
    source_health,
)


ROOT = Path(__file__).resolve().parents[2]


class LegendaryRefetchRecoveryV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.entity_index, _ = build_entity_index_v3(ROOT)
        cls.old_search = json.loads(
            (ROOT / "local_wiki/ss13/site/search-index.json").read_text(encoding="utf-8")
        )
        cls.search, cls.stats = refresh_search_ownership(cls.old_search, cls.entity_index)
        cls.by_entity = {
            entity["entity_id"]: entity for entity in cls.entity_index["entities"]
        }

    def test_all_339_manifest_raw_files_are_nonempty(self) -> None:
        self.assertEqual(
            {
                "manifest_pages": 339,
                "raw_present": 339,
                "nonempty_raw": 339,
                "zero_byte_raw": 0,
                "missing_raw": 0,
            },
            source_health(ROOT),
        )

    def test_332_legendary_entities_have_expected_type_and_classification(self) -> None:
        entities = [
            entity
            for entity in self.entity_index["entities"]
            if entity.get("entity_type") == "legendary_equipment"
        ]
        self.assertEqual(332, len(entities))
        self.assertTrue(
            all(
                entity.get("content_category_id") == "equipment"
                and entity.get("content_subcategory_id") == "equipment_legendary"
                for entity in entities
            )
        )

    def test_seven_non_equipment_manifest_pages_are_not_legendary_entities(self) -> None:
        self.assertEqual(7, len(NON_EQUIPMENT_IDS))
        for slug in NON_EQUIPMENT_IDS:
            entity = self.by_entity.get(f"tlidb:cn:{slug}")
            self.assertNotEqual("legendary_equipment", (entity or {}).get("entity_type"))

    def test_all_65_historically_empty_entities_are_recovered(self) -> None:
        fetch = json.loads(
            (ROOT / "data/raw/manifests/legendary_gear/reports/fetch-report.json").read_text(
                encoding="utf-8"
            )
        )
        downloaded = {entry["id"] for entry in fetch["entries"] if entry["status"] == "downloaded"}
        self.assertEqual(65, len(downloaded))
        self.assertTrue(
            {f"tlidb:cn:{slug}" for slug in downloaded} <= set(self.by_entity)
        )

    def test_firebird_entity_and_search_ownership_are_correct(self) -> None:
        entity = self.by_entity["tlidb:cn:Necklace_of_Firebird"]
        self.assertEqual("legendary_equipment", entity["entity_type"])
        self.assertEqual("equipment", entity["content_category_id"])
        self.assertEqual("equipment_legendary", entity["content_subcategory_id"])
        pages = [
            page
            for page in self.search["pages"]
            if page.get("entity_id") == "tlidb:cn:Necklace_of_Firebird"
        ]
        self.assertEqual(1, len(pages))
        page = pages[0]
        self.assertEqual("legendary_gear", page["system_id"])
        self.assertEqual("equipment_legendary", page["content_subcategory_id"])
        self.assertIn("淬火之鸟", page["plain_text"])

    def test_firebird_does_not_match_craft_filter_or_duplicate_search_route(self) -> None:
        pages = [
            page
            for page in self.search["pages"]
            if page.get("id") == "Necklace_of_Firebird"
        ]
        self.assertEqual(1, len(pages))
        self.assertNotEqual("equipment_craft", pages[0]["content_subcategory_id"])
        self.assertNotEqual("craft", pages[0]["system_id"])

    def test_search_schema_remains_8_and_report_has_no_errors(self) -> None:
        self.assertEqual(8, self.search["schema_version"])
        report = build_recovery_report(ROOT, self.entity_index, self.search)
        self.assertEqual(332, report["legendary_entities"]["actual"])
        self.assertEqual(65, report["legendary_entities"]["recovered_from_empty_raw"])
        self.assertEqual([], report["errors"])


if __name__ == "__main__":
    unittest.main()
