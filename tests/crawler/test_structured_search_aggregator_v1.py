from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from crawler.structured import aggregate_structured_search as aggregator


ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_ROOT = ROOT / "data/generated/structured/ss13"


def _record(record_id: str, entity_type: str = "test") -> dict:
    return {
        "record_id": record_id,
        "entity_id": f"tlidb:cn:{record_id}",
        "entity_title": record_id,
        "record_type": "test_record",
        "section_name": "Test",
        "text": record_id,
        "route": f"/cn/{record_id}/",
        "source_locator": {},
        "landing": {"route": f"/cn/{record_id}/"},
        "entity_type": entity_type,
        "content_category_id": "test",
        "content_category_name_zh": "测试",
        "content_subcategory_id": "test",
        "content_subcategory_name_zh": "测试",
    }


def _module(path: Path, records: list[dict], **updates) -> None:
    value = {
        "schema_version": 1,
        "season_id": "ss13",
        "record_count": len(records),
        "records": records,
    }
    value.update(updates)
    path.write_text(json.dumps(value), encoding="utf-8")


def _registry(root: Path, ids: tuple[str, ...] = ("alpha", "beta")):
    specs = tuple(aggregator.ModuleSpec(item, f"{item}.json") for item in ids)
    for item in ids:
        _module(root / f"{item}.json", [_record(item)])
    return specs


class StructuredSearchAggregatorTest(unittest.TestCase):
    def test_fresh_aggregate_ignores_existing_final_and_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = _registry(root)
            output = root / "structured-search-index.json"
            output.write_text('{"old":true}', encoding="utf-8")
            first, counts = aggregator.aggregate_structured_search(root, output, registry=reversed(registry))
            first_bytes = output.read_bytes()
            second, _ = aggregator.aggregate_structured_search(root, output, registry=registry)
            self.assertEqual(first, second)
            self.assertEqual(output.read_bytes(), first_bytes)
            self.assertEqual([item["record_id"] for item in first["records"]], ["alpha", "beta"])
            self.assertEqual(counts, {"beta": 1, "alpha": 1})
            self.assertEqual(first["record_count"], len(first["records"]))

    def test_duplicate_record_id_is_a_hard_failure_and_preserves_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            specs = (aggregator.ModuleSpec("one", "one.json"), aggregator.ModuleSpec("two", "two.json"))
            _module(root / "one.json", [_record("same")])
            _module(root / "two.json", [_record("same")])
            output = root / "final.json"
            output.write_text("known-good", encoding="utf-8")
            with self.assertRaisesRegex(aggregator.StructuredAggregationError, "duplicate record_id"):
                aggregator.aggregate_structured_search(root, output, registry=specs)
            self.assertEqual(output.read_text(encoding="utf-8"), "known-good")

    def test_invalid_or_missing_required_module_fails(self) -> None:
        cases = (
            (None, None, "missing required"),
            ("only.json", "not-json", "invalid JSON"),
            ("only.json", '{"schema_version":2,"records":[]}', "invalid schema"),
            ("only.json", '{"schema_version":1,"season_id":"ss13","record_count":0,"records":[]}', "empty production"),
        )
        for filename, contents, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                if filename:
                    (root / filename).write_text(contents or "", encoding="utf-8")
                with self.assertRaisesRegex(aggregator.StructuredAggregationError, message):
                    aggregator.build_aggregate(root, registry=(aggregator.ModuleSpec("only", "only.json"),))

    def test_atomic_replace_failure_preserves_previous_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = _registry(root, ("only",))
            output = root / "final.json"
            output.write_text("known-good", encoding="utf-8")
            with mock.patch.object(aggregator.os, "replace", side_effect=OSError("simulated replace failure")):
                with self.assertRaisesRegex(OSError, "simulated"):
                    aggregator.aggregate_structured_search(root, output, registry=registry)
            self.assertEqual(output.read_text(encoding="utf-8"), "known-good")
            self.assertFalse(list(root.glob(".final.json.*.tmp")))

    def test_current_production_modules_preserve_all_records(self) -> None:
        reference = json.loads((PRODUCTION_ROOT / "structured-search-index.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            aggregate, counts = aggregator.aggregate_structured_search(
                PRODUCTION_ROOT, Path(directory) / "structured-search-index.json"
            )
        self.assertEqual(
            {record["record_id"] for record in aggregate["records"]},
            {record["record_id"] for record in reference["records"]},
        )
        self.assertEqual(aggregate["record_count"], reference["record_count"])
        self.assertEqual(aggregate["schema_version"], reference["schema_version"])
        self.assertEqual(aggregate["season_id"], reference["season_id"])
        for module_id in ("ordinary_equipment", "legendary_equipment", "vorax_equipment", "memory", "ethereal_prism", "hero_trait", "remaining_talent", "skill"):
            self.assertGreater(counts[module_id], 0)
        self.assertEqual(counts["equipment_related"], 97 + 408)
        self.assertEqual(counts["pact"], 2351)
        self.assertEqual(counts["fate"], 193)

    def test_registry_is_explicit_and_unknown_json_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = _registry(root, ("only",))
            _module(root / "unregistered.json", [_record("unregistered")])
            aggregate, _ = aggregator.build_aggregate(root, registry=registry)
            self.assertEqual([record["record_id"] for record in aggregate["records"]], ["only"])


if __name__ == "__main__":
    unittest.main()
