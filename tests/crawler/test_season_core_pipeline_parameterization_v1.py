from __future__ import annotations

import json
import tempfile
import unittest
import inspect
from pathlib import Path

from crawler.season_context import DEFAULT_SEASON, SeasonContext
from crawler.generate_entity_index_v3 import build_entity_index_v3
from crawler.structured.aggregate_structured_search import (
    ModuleSpec,
    StructuredAggregationError,
    build_aggregate,
)
from crawler.structured import (
    run_equipment_parser, run_equipment_related_parser,
    run_ethereal_prism_parser, run_hero_trait_structured_parser,
    run_legendary_equipment_parser, run_memory_structured_parser,
    run_pact_fate_structured_parsers, run_remaining_talent_structured_parser,
    run_skill_structured_parser, run_vorax_equipment_parser,
)


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "data/reports/local-wiki/season-core-pipeline-parameterization-v1.json"


def _module(path: Path, season: str) -> None:
    path.write_text(json.dumps({
        "schema_version": 1,
        "season_id": season,
        "record_count": 1,
        "records": [{"record_id": f"{season}:record"}],
    }), encoding="utf-8")


class SeasonCorePipelineParameterizationV1Test(unittest.TestCase):
    def test_default_season_and_scoped_paths(self) -> None:
        context = SeasonContext(ROOT)
        self.assertEqual(DEFAULT_SEASON, context.season)
        self.assertEqual(ROOT / "sources/seasons/ss13", context.source_root)
        self.assertEqual(ROOT / "data/raw/manifests/ss13", context.raw_manifest_root)
        self.assertEqual(ROOT / "data/generated/ss13/entity-index-v3.json", context.entity_output)
        self.assertEqual(ROOT / "data/generated/structured/ss13", context.structured_root)

    def test_custom_season_has_no_ss13_path_leakage(self) -> None:
        context = SeasonContext(ROOT, "test14")
        paths = (
            context.source_root, context.system_manifest, context.raw_manifest_root,
            context.entity_output, context.structured_root, context.report_root,
        )
        self.assertTrue(all("test14" in str(path) for path in paths))
        self.assertTrue(all("ss13" not in str(path) for path in paths))

    def test_manifest_and_raw_namespaces_are_isolated(self) -> None:
        first = SeasonContext(ROOT, "ss13")
        second = SeasonContext(ROOT, "test14")
        self.assertNotEqual(first.system_manifest, second.system_manifest)
        self.assertNotEqual(first.source_manifest("hero"), second.source_manifest("hero"))
        self.assertNotEqual(first.raw_manifest_root, second.raw_manifest_root)

    def test_all_production_structured_runners_accept_season(self) -> None:
        functions = (
            run_equipment_parser.generate_equipment_structured_data,
            run_legendary_equipment_parser.generate,
            run_vorax_equipment_parser.generate,
            run_memory_structured_parser.generate,
            run_equipment_related_parser.generate,
            run_ethereal_prism_parser.generate,
            run_pact_fate_structured_parsers.generate,
            run_hero_trait_structured_parser.generate,
            run_remaining_talent_structured_parser.generate,
            run_skill_structured_parser.generate,
        )
        self.assertTrue(all("season" in inspect.signature(function).parameters for function in functions))

    def test_aggregator_uses_requested_season_and_validates_modules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = ModuleSpec("sample", "sample.json")
            _module(root / spec.filename, "test14")
            aggregate, counts = build_aggregate(root, registry=(spec,), season="test14")
            self.assertEqual("test14", aggregate["season_id"])
            self.assertEqual({"sample": 1}, counts)
            with self.assertRaisesRegex(StructuredAggregationError, "season_id"):
                build_aggregate(root, registry=(spec,), season="ss13")

    def test_ss13_aggregate_record_ids_are_preserved(self) -> None:
        root = ROOT / "data/generated/structured/ss13"
        reference = json.loads((root / "structured-search-index.json").read_text(encoding="utf-8"))
        aggregate, _ = build_aggregate(root, season="ss13")
        self.assertEqual(reference["record_count"], aggregate["record_count"])
        self.assertEqual(
            {record["record_id"] for record in reference["records"]},
            {record["record_id"] for record in aggregate["records"]},
        )

    def test_ss13_entity_ids_and_classification_are_preserved(self) -> None:
        reference = json.loads(
            (ROOT / "data/generated/entity-index-v3.json").read_text(encoding="utf-8")
        )
        generated, _ = build_entity_index_v3(ROOT, SeasonContext(ROOT, "ss13"))
        fields = (
            "entity_id", "entity_type", "content_category_id",
            "content_subcategory_id", "entity_visibility",
        )
        self.assertEqual(
            {tuple(item.get(field) for field in fields) for item in reference["entities"]},
            {tuple(item.get(field) for field in fields) for item in generated["entities"]},
        )

    def test_report_declares_pipeline_ready(self) -> None:
        report = json.loads(REPORT.read_text(encoding="utf-8"))
        self.assertIs(report["core_season_parameterization_ready"], True)
        self.assertEqual("ss13", report["default_behavior"]["season"])
        self.assertEqual("test14", report["custom_season_behavior"]["season"])


if __name__ == "__main__":
    unittest.main()
