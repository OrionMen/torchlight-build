from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from crawler.season_context import SeasonContext
from crawler import build_full_wiki_mirror as mirror_builder
from crawler.structured.aggregate_structured_search import PRODUCTION_MODULES


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/rebuild_wiki.sh"
REPORT = ROOT / "data/reports/local-wiki/season-rebuild-orchestrator-v1.json"


def dry_run(*args: str) -> str:
    return subprocess.run(
        [str(SCRIPT), *args], cwd=ROOT, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    ).stdout


class SeasonRebuildOrchestratorV1Test(unittest.TestCase):
    def test_default_is_explicit_ss13(self) -> None:
        self.assertEqual(dry_run("--dry-run"), dry_run("--season", "ss13", "--dry-run"))

    def test_custom_season_paths_are_isolated(self) -> None:
        output = dry_run("--season", "test14", "--dry-run")
        expected = (
            "sources/seasons/test14", "data/raw/manifests/test14",
            "data/generated/test14", "data/generated/structured/test14",
            "data/raw/assets/test14", "data/raw/i18n/test14",
            "local_wiki/test14/site",
        )
        self.assertTrue(all(value in output for value in expected))
        self.assertNotIn("/ss13", output)

    def test_dry_run_does_not_create_season_outputs(self) -> None:
        context = SeasonContext(ROOT, "dryrun_fixture_14")
        paths = (context.source_root, context.raw_manifest_root, context.entity_output.parent,
                 context.structured_root, context.asset_root, context.i18n_root,
                 context.report_root, context.mirror_output)
        before = [path.exists() for path in paths]
        dry_run("--season", context.season, "--dry-run")
        self.assertEqual(before, [path.exists() for path in paths])

    def test_asset_i18n_and_builder_use_custom_paths(self) -> None:
        output = dry_run("--season", "test14", "--dry-run")
        self.assertIn("--asset-root data/raw/assets/test14/files", output)
        self.assertIn("--i18n-root data/raw/i18n/test14/files", output)
        self.assertIn("--output local_wiki/test14/site", output)

    def test_builder_defaults_are_derived_from_requested_season(self) -> None:
        with mock.patch.object(mirror_builder, "build", return_value={"errors": []}) as build:
            self.assertEqual(0, mirror_builder.main(["--season", "test14"]))
        positional = build.call_args.args
        keywords = build.call_args.kwargs
        self.assertEqual(ROOT / "data/raw/manifests/test14", positional[1])
        self.assertEqual(ROOT / "data/raw/assets/test14/asset-manifest.json", positional[2])
        self.assertEqual(ROOT / "local_wiki/test14/site", positional[4])
        self.assertEqual(ROOT / "data/generated/test14/entity-index-v3.json", keywords["entity_index_path"])
        self.assertEqual(
            ROOT / "data/generated/structured/test14/structured-search-index.json",
            keywords["structured_search_index_path"],
        )

    def test_all_structured_modules_precede_aggregate_and_mirror(self) -> None:
        output = dry_run("--season", "test14", "--dry-run")
        runner_marker = "crawler.structured.run_"
        self.assertEqual(10, output.count(runner_marker))
        self.assertEqual(11, len(PRODUCTION_MODULES))
        last_runner = output.rfind(runner_marker)
        aggregate = output.index("crawler.structured.aggregate_structured_search")
        mirror = output.index("crawler.build_full_wiki_mirror")
        validation = output.index("crawler.validate_season_rebuild")
        self.assertLess(last_runner, aggregate)
        self.assertLess(aggregate, mirror)
        self.assertLess(mirror, validation)

    def test_convergence_and_fail_fast_contract(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", source)
        self.assertIn("max_rounds=8", source)
        self.assertIn("recovered-pages-convergence", source)
        self.assertIn("asset-convergence", source)

    def test_validation_contract_lists_required_runtime_outputs(self) -> None:
        source = (ROOT / "crawler/validate_season_rebuild.py").read_text(encoding="utf-8")
        for value in (
            "context.entity_output", "structured-search-index.json", "search-index.json",
            "catalog.json", "_local/search/app.js", "_local/mirror.js",
        ):
            self.assertIn(value, source)

    def test_report_is_ready(self) -> None:
        report = json.loads(REPORT.read_text(encoding="utf-8"))
        self.assertIs(report["fresh_clone_rebuild_orchestrator_ready"], True)
        self.assertEqual([], report["errors"])


if __name__ == "__main__":
    unittest.main()
