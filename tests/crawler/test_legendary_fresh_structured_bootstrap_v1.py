from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from crawler.audit_legendary_structured_dom_v1 import build_audit
from crawler.structured import run_legendary_equipment_parser as runner


ROOT = Path(__file__).resolve().parents[2]


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class LegendaryFreshStructuredBootstrapV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.audit = build_audit(ROOT, "ss13")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temporary.name) / "structured" / "ss13"
        cls.report_path = Path(cls.temporary.name) / "report.json"
        with mock.patch.object(
            runner,
            "build_audit",
            side_effect=ValueError("diagnostic sample unavailable"),
        ):
            cls.results, cls.index, cls.report = runner.generate(
                ROOT, cls.output, cls.report_path, "ss13"
            )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_fresh_season_scoped_input_and_expected_entity_coverage(self) -> None:
        self.assertEqual(332, self.audit["legendary_pages"])
        self.assertEqual(332, self.report["entity_coverage"]["entity_count"])
        self.assertEqual([], self.report["entity_coverage"]["classification_errors"])
        self.assertIn("sources/seasons/ss13", self.audit["input_paths"]["manifest"])
        self.assertIn("data/raw/manifests/ss13", self.audit["input_paths"]["raw_root"])
        self.assertNotEqual(
            str(ROOT / "sources/legendary_gear_manifest.json"),
            self.audit["input_paths"]["manifest"],
        )

    def test_parser_output_is_complete_without_required_audit(self) -> None:
        self.assertEqual(332, len(self.results))
        self.assertEqual(332, self.report["structure_matched"])
        self.assertEqual(0, self.report["structure_mismatches"])
        self.assertEqual(3287, self.index["record_count"])
        self.assertEqual(3287, len({item["record_id"] for item in self.index["records"]}))
        self.assertEqual(1.0, self.report["stable_key_coverage"])
        self.assertEqual("unavailable", self.report["audit"]["status"])
        self.assertTrue(any("diagnostic sample unavailable" in item for item in self.report["warnings"]))

    def test_module_index_is_generated_independently_of_global_aggregate(self) -> None:
        module_path = self.output / "legendary-equipment-structured-index.json"
        self.assertTrue(module_path.is_file())
        self.assertEqual(3287, json.loads(module_path.read_text())["record_count"])
        source = Path(runner.__file__).read_text(encoding="utf-8")
        self.assertNotIn("structured-search-index.json", source)

    def test_empty_case_study_candidates_are_reported_not_raised(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            write_json(
                repo / "sources/seasons/test14/legendary_gear_manifest.json",
                {"entries": []},
            )
            (repo / "data/raw/manifests/test14/legendary_gear/raw_html").mkdir(
                parents=True
            )
            audit = build_audit(repo, "test14")
        self.assertEqual(0, audit["legendary_pages"])
        self.assertEqual(
            0, audit["case_study_selection"]["candidate_counts"]["single_legendary_effect"]
        )
        self.assertIn("single_legendary_effect", audit["case_study_selection"]["unavailable"])
        self.assertTrue(audit["warnings"])
        self.assertIn("sources/seasons/test14", audit["input_paths"]["manifest"])
        self.assertIn("data/raw/manifests/test14", audit["input_paths"]["raw_root"])
        self.assertNotIn("ss13", audit["input_paths"]["manifest"])

    def test_real_structure_mismatch_hard_fails_without_module_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            output = repo / "out"
            report = repo / "report.json"
            write_json(
                repo / "sources/seasons/test14/legendary_gear_manifest.json",
                {"entries": [{"id": "Broken", "slug": "Broken", "name_zh": "Broken"}]},
            )
            write_json(
                repo / "data/generated/test14/entity-index-v3.json",
                {"entities": [{
                    "entity_id": "tlidb:cn:Broken",
                    "entity_type": "legendary_equipment",
                    "content_category_id": "equipment",
                    "content_subcategory_id": "equipment_legendary",
                }]},
            )
            raw = repo / "data/raw/manifests/test14/legendary_gear/raw_html/Broken.html"
            raw.parent.mkdir(parents=True)
            raw.write_text("<html><body>invalid legendary structure</body></html>")
            with self.assertRaisesRegex(
                runner.LegendaryStructuredGenerationError, "structure mismatch"
            ):
                runner.generate(repo, output, report, "test14")
            self.assertFalse(
                (output / "legendary-equipment-structured-index.json").exists()
            )
            self.assertFalse(report.exists())
            self.assertEqual([], list((output / "legendary_equipment").glob("*.json")))

    def test_empty_manifest_hard_fails_without_publishing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            output = repo / "out"
            write_json(
                repo / "sources/seasons/test14/legendary_gear_manifest.json",
                {"entries": []},
            )
            with self.assertRaisesRegex(
                runner.LegendaryStructuredGenerationError, "no equipment definitions"
            ):
                runner.generate(repo, output, repo / "report.json", "test14")
            self.assertFalse(
                (output / "legendary-equipment-structured-index.json").exists()
            )

    def test_atomic_module_replace_preserves_known_good_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legendary-equipment-structured-index.json"
            path.write_text("known-good", encoding="utf-8")
            with mock.patch.object(runner.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    runner.write_atomic_json(path, {"schema_version": 1})
            self.assertEqual("known-good", path.read_text(encoding="utf-8"))
            self.assertEqual([], list(path.parent.glob(f".{path.name}.*.tmp")))


if __name__ == "__main__":
    unittest.main()
