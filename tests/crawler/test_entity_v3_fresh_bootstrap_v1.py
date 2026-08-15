import json
import os
import tempfile
import unittest
from pathlib import Path

from crawler.generate_entity_index_v3 import (
    build_entity_index_v3,
    fresh_bootstrap_report,
)


ROOT = Path(__file__).resolve().parents[2]


class EntityV3FreshBootstrapV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.fresh_root = Path(cls.temp.name)
        (cls.fresh_root / "data").mkdir()
        os.symlink(ROOT / "sources", cls.fresh_root / "sources", target_is_directory=True)
        os.symlink(ROOT / "config", cls.fresh_root / "config", target_is_directory=True)
        os.symlink(ROOT / "data/raw", cls.fresh_root / "data/raw", target_is_directory=True)
        cls.index, cls.generation_report = build_entity_index_v3(cls.fresh_root)
        cls.repeat, _ = build_entity_index_v3(cls.fresh_root)
        cls.reference = json.loads(
            (ROOT / "data/generated/entity-index-v3.json").read_text(encoding="utf-8")
        )
        cls.report = fresh_bootstrap_report(cls.index, cls.reference)
        cls.by_id = {entity["entity_id"]: entity for entity in cls.index["entities"]}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_generation_needs_no_old_generated_or_local_wiki_inputs(self):
        self.assertFalse((self.fresh_root / "local_wiki").exists())
        self.assertFalse((self.fresh_root / "data/generated").exists())
        self.assertFalse((self.fresh_root / "data/reports").exists())
        self.assertEqual(1662, len(self.index["entities"]))

    def test_repeated_generation_is_deterministic(self):
        self.assertEqual(self.index, self.repeat)
        routes = [entity["canonical_route"] for entity in self.index["entities"]]
        self.assertEqual(sorted(routes), routes)
        self.assertEqual(len(routes), len(set(routes)))

    def test_current_identity_and_classification_contract_is_unchanged(self):
        self.assertTrue(self.report["regression_comparison"]["same"])
        self.assertTrue(self.report["regression_comparison"]["same_entity_ids"])
        for key in (
            "missing", "extra", "classification_diffs", "visibility_diffs",
            "route_diffs", "entity_type_diffs",
        ):
            self.assertEqual([], self.report["regression_comparison"][key])

    def test_legendary_owns_duplicate_route(self):
        entity = self.by_id["tlidb:cn:Trinity"]
        self.assertEqual("legendary_equipment", entity["entity_type"])
        self.assertEqual("equipment_legendary", entity["content_subcategory_id"])
        self.assertEqual("legendary_gear", entity["sources"][0]["source_type"])

    def test_recovered_fate_is_bootstrapped_from_destiny_sources(self):
        for slug in (
            "Micro_Fate:_Deterioration_Duration",
            "Micro_Fate:_Trauma_Damage_Mitigation",
        ):
            entity = self.by_id[f"tlidb:cn:{slug}"]
            self.assertEqual("fate", entity["entity_type"])
            self.assertEqual("pact_spirit_destiny", entity["content_subcategory_id"])
        self.assertEqual(193, self.report["entity_counts"]["fate"])

    def test_formal_module_counts_are_preserved(self):
        expected = {
            "ordinary_equipment": 38,
            "legendary_equipment": 332,
            "vorax": 10,
            "memory": 1,
            "equipment_related": 2,
            "ethereal_prism": 1,
            "pact": 175,
            "fate": 193,
            "hero_trait": 27,
            "talent": 32,
            "skill_visible": 721,
        }
        for field, count in expected.items():
            self.assertEqual(count, self.report["entity_counts"][field], field)

    def test_legacy_metadata_and_visibility_are_deterministic(self):
        warehouse = self.by_id["tlidb:cn:Sandlord_Season"]
        self.assertEqual("equipment_type", warehouse["content_subcategory_id"])
        divinity = self.by_id["tlidb:cn:Divinity_Slate"]
        self.assertEqual("talent_divinity_slate", divinity["content_subcategory_id"])
        for route in (
            "/cn/Active_Skill/", "/cn/Legendary_Gear/", "/cn/Destiny/",
        ):
            entity = next(item for item in self.index["entities"] if item["canonical_route"] == route)
            self.assertEqual("hidden", entity["entity_visibility"])

    def test_schema_remains_compatible_with_existing_consumers(self):
        self.assertEqual(3, self.index["schema_version"])
        self.assertTrue(self.report["consumer_compatibility"]["required_fields_present"])
        self.assertFalse(self.report["consumer_compatibility"]["builder_and_structured_changes_required"])


if __name__ == "__main__":
    unittest.main()
