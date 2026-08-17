from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from crawler import generate_entity_index_v3 as entity_v3
from crawler.discover_system_manifest import discover_system, inventory_directory_entries
from crawler.verify_candidate_systems import apply_results, backup_path_for_manifest, verify_html


ROOT = Path(__file__).resolve().parents[2]


def inventory_candidate() -> dict:
    return {
        "system_id": "candidate_inventory",
        "name_zh": "Stash",
        "index_slug": "Inventory",
        "index_url": "https://tlidb.com/cn/Inventory",
        "discovery_status": "candidate",
        "manifest_path": "sources/seasons/test14/candidate_inventory_manifest.json",
        "source_order": 4,
    }


def structural_inventory_html(count: int = 12) -> str:
    links = []
    for index in range(count):
        marker = f' data-i18n="item_type_list|name|{index}"' if index < 4 else ""
        links.append(f'<a href="Equipment_{index}"{marker}>Equipment {index}</a>')
    return "<html><body>" + "".join(links) + "</body></html>"


class EntityFreshInventoryBootstrapV1Test(unittest.TestCase):
    def test_real_fresh_inventory_snapshot_is_structurally_confirmed(self) -> None:
        path = ROOT / "data/raw/manifests/ss13/codex/raw_html/Inventory.html"
        result = verify_html(inventory_candidate(), path.read_text(encoding="utf-8"))
        self.assertEqual("confirmed_directory", result["classification"])
        self.assertEqual("flat_relative_inventory_directory", result["directory_signature"])
        self.assertEqual(147, result["unique_entry_count"])
        self.assertEqual("inventory", result["recommended_system_id"])

    def test_custom_season_uses_structure_not_specific_entity(self) -> None:
        html = structural_inventory_html()
        result = verify_html(inventory_candidate(), html)
        self.assertEqual("confirmed_directory", result["classification"])
        self.assertEqual(12, result["unique_entry_count"])
        self.assertNotIn("STR_Helmet", html)

    def test_manifest_discovery_uses_same_inventory_contract(self) -> None:
        system = {**inventory_candidate(), "system_id": "inventory"}
        manifest, report = discover_system(system, 1.0, html=structural_inventory_html())
        self.assertEqual(12, manifest["unique_entry_count"])
        self.assertEqual("flat_relative_inventory_directory", report["directory_signature"])
        self.assertTrue(manifest["entries"][0]["url"].endswith("/cn/Equipment_0"))

    def test_production_required_candidate_does_not_remain_needs_review(self) -> None:
        candidate = inventory_candidate()
        result = verify_html(candidate, structural_inventory_html())
        manifest = {"systems": [candidate]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources/seasons/test14/system_manifest.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(manifest), encoding="utf-8")
            apply_results(
                path, manifest, [result], backup_path_for_manifest(path), False, "now"
            )
            applied = json.loads(path.read_text(encoding="utf-8"))["systems"][0]
        self.assertEqual("inventory", applied["system_id"])
        self.assertEqual("confirmed", applied["discovery_status"])
        self.assertEqual("verified", applied["verification_status"])

    def test_inventory_contract_has_no_specific_equipment_hardcode(self) -> None:
        self.assertNotIn("STR_Helmet", inspect.getsource(inventory_directory_entries))

    def test_current_fresh_input_uses_cached_canonical_inventory_index(self) -> None:
        index, _report = entity_v3._bootstrap_v2_from_sources(ROOT)
        entries, snapshot = entity_v3._inventory_snapshot_entries(ROOT)
        ids = {item["entity_id"] for item in index["entities"]}
        self.assertIsNotNone(snapshot)
        self.assertEqual(147, len(entries))
        self.assertEqual(
            38,
            sum(f"tlidb:cn:{slug}" in ids for slug in entity_v3.ORDINARY_EQUIPMENT_IDS),
        )

    def test_complete_formal_inventory_coverage_is_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sources/seasons/test14"
            source.mkdir(parents=True)
            source.joinpath("system_manifest.json").write_text(json.dumps({"systems": [{
                "system_id": "inventory",
                "discovery_status": "confirmed",
                "manifest_path": "sources/seasons/test14/inventory_manifest.json",
            }]}), encoding="utf-8")
            entities = [{
                "entity_id": f"tlidb:cn:{slug}",
                "entity_type": "equipment",
                "content_subcategory_id": "equipment_craft",
            } for slug in entity_v3.ORDINARY_EQUIPMENT_IDS]
            previous = entity_v3._SEASON_CONTEXT
            try:
                entity_v3._SEASON_CONTEXT = entity_v3.SeasonContext(root, "test14")
                readiness = entity_v3.entity_stage_readiness(root, {"entities": entities})
            finally:
                entity_v3._SEASON_CONTEXT = previous
        self.assertTrue(readiness["ready"])
        self.assertEqual(38, readiness["ordinary_equipment_generated"])

    def test_missing_report_samples_are_explicit_not_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sources/seasons/test14"
            source.mkdir(parents=True)
            for system in ("craft", "legendary_gear"):
                source.joinpath(f"{system}_manifest.json").write_text(
                    json.dumps({"entries": []}), encoding="utf-8"
                )
            previous = entity_v3._SEASON_CONTEXT
            try:
                entity_v3._SEASON_CONTEXT = entity_v3.SeasonContext(root, "test14")
                report = entity_v3.equipment_craft_enrichment_filter_v2_report(
                    root, {"entities": []}
                )
            finally:
                entity_v3._SEASON_CONTEXT = previous
        self.assertEqual(
            ["STR_Helmet", "Belt", "Crossbow"],
            report["examples"]["unavailable"]["accepted"],
        )
        self.assertTrue(report["warnings"])

    def test_report_failure_does_not_publish_entity_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "entity-index-v3.json"
            index = {"schema_version": 3, "entities": []}
            with (
                mock.patch.object(entity_v3, "build_entity_index_v3", return_value=(index, {})),
                mock.patch.object(entity_v3, "entity_stage_readiness", return_value={"ready": True, "errors": []}),
                mock.patch.object(
                    entity_v3, "equipment_craft_enrichment_filter_v2_report",
                    side_effect=RuntimeError("injected report failure"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "injected report failure"):
                    entity_v3.main([
                        "--repo", str(root), "--season", "test14",
                        "--output", str(output),
                    ])
            self.assertFalse(output.exists())

    def test_generation_source_contract_excludes_old_outputs(self) -> None:
        source = inspect.getsource(entity_v3._bootstrap_manifest_sources)
        self.assertNotIn("search-index", source)
        self.assertNotIn("local_wiki", source)
        self.assertNotIn("entity-index", source)


if __name__ == "__main__":
    unittest.main()
