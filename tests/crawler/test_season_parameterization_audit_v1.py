from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "data/reports/local-wiki/season-parameterization-audit-v1.json"


class SeasonParameterizationAuditV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = json.loads(REPORT.read_text(encoding="utf-8"))

    def test_report_schema_and_verdict(self) -> None:
        self.assertEqual(1, self.report["schema_version"])
        self.assertIs(self.report["season_rebuild_ready"], False)
        self.assertEqual("BLOCKED", self.report["audit_verdict"])
        self.assertGreater(self.report["hardcoded_ss13_count"], 0)

    def test_all_pipeline_sections_have_valid_status(self) -> None:
        expected = {
            "discovery", "manifest", "fetch", "entity", "structured",
            "aggregator", "assets", "i18n", "builder", "runtime",
        }
        self.assertEqual(expected, set(self.report["statuses"]))
        self.assertTrue(set(self.report["statuses"].values()) <= {"READY", "PARTIAL", "BLOCKED"})
        for section in expected:
            self.assertEqual(self.report["statuses"][section], self.report[section]["status"])

    def test_findings_are_classified_and_actionable(self) -> None:
        self.assertTrue(self.report["findings"])
        self.assertTrue(self.report["p0_blockers"])
        self.assertTrue(self.report["p1_improvements"])
        for finding in self.report["findings"]:
            self.assertIn(finding["category"], {"default", "configurable_missing", "blocker"})
            self.assertTrue(finding["file"])
            self.assertTrue(finding["impact"])
            self.assertTrue(finding["recommendation"])

    def test_recommended_cli_defines_all_scoped_outputs(self) -> None:
        cli = self.report["recommended_cli"]
        self.assertEqual("./scripts/rebuild_wiki.sh --season ss14", cli["command"])
        self.assertTrue({
            "system_manifest", "child_manifests", "raw_root", "entity_index",
            "structured_root", "asset_manifest", "asset_root", "i18n_root",
            "mirror_output", "report_root",
        } <= set(cli["derived_paths"]))


if __name__ == "__main__":
    unittest.main()
