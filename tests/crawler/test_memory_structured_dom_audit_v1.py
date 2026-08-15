from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crawler.audit_memory_structured_dom_v1 import build_report


REPO = Path(__file__).resolve().parents[2]


class MemoryStructuredDomAuditV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = build_report(REPO)

    def test_sources_and_single_entity_model_are_complete(self) -> None:
        self.assertTrue(self.report["source_completeness"]["authorized_sources_complete"])
        self.assertTrue(self.report["entity_model"]["entity_present"])
        self.assertEqual("memory_system", self.report["entity_model"]["entity_type"])
        self.assertFalse(self.report["entity_model"]["memory_revival_is_independent_entity"])

    def test_five_sections_and_candidate_types(self) -> None:
        self.assertEqual(5, len(self.report["sections"]))
        self.assertTrue(all(section["structure_status"] == "matched" for section in self.report["sections"]))
        self.assertEqual(
            {
                "memory_base_attribute",
                "memory_fixed_affix",
                "memory_random_affix",
                "memory_revival_affix",
                "memory_revival_moon_affix",
            },
            {item["record_type"] for item in self.report["candidate_record_types"]},
        )

    def test_record_counts_and_stable_key_coverage(self) -> None:
        self.assertEqual(755, self.report["record_counts"]["total"])
        self.assertEqual(755, self.report["stable_identity"]["records_with_stable_key"])
        self.assertEqual(1.0, self.report["stable_identity"]["coverage"])
        self.assertEqual(0, self.report["duplicate_key_analysis"]["duplicate_stable_key_count"])

    def test_landing_uses_actual_supplemental_route(self) -> None:
        landing = self.report["supplemental_source_landing"]
        self.assertEqual("tlidb:cn:Hero_Memories", landing["entity_id"])
        self.assertEqual("/cn/Memory_Revival/", landing["revival_record_route"])
        self.assertTrue(landing["contract_supported"])
        self.assertEqual(755, self.report["locator_support"]["record_level"])

    def test_whitelist_and_framework_contract(self) -> None:
        self.assertEqual(
            ["基础属性", "固有词缀", "随机词缀", "复苏词缀", "复苏词缀（月相）"],
            self.report["noise_exclusions"]["whitelist_only"],
        )
        self.assertTrue(self.report["framework_compatibility"]["compatible"])
        self.assertEqual([], self.report["errors"])

    def test_report_is_json_serializable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps(self.report, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(1, json.loads(path.read_text(encoding="utf-8"))["schema_version"])


if __name__ == "__main__":
    unittest.main()
