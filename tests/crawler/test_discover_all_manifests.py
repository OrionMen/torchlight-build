import tempfile
import unittest
from pathlib import Path

from crawler.discover_all_manifests import run_batch


class DiscoverAllManifestsTest(unittest.TestCase):
    def setUp(self):
        self.data = {
            "systems": [
                {"system_id": "confirmed", "index_url": "https://tlidb.com/cn/Confirmed", "discovery_status": "confirmed"},
                {"system_id": "candidate", "index_url": "https://tlidb.com/cn/Candidate", "discovery_status": "candidate"},
            ]
        }

    @staticmethod
    def discoverer(system, _timeout):
        return {
            "system_id": system["system_id"],
            "entries": [{"id": "One", "url": "https://tlidb.com/cn/One"}],
            "unique_entry_count": 1,
        }, {"warnings": [], "errors": []}

    def test_existing_is_skipped_and_force_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "confirmed_manifest.json").write_text("{}", encoding="utf-8")
            skipped, failures = run_batch(self.data, output, discoverer=self.discoverer)
            forced, forced_failures = run_batch(self.data, output, force=True, discoverer=self.discoverer)
        self.assertEqual(failures, 0)
        self.assertEqual(skipped["skipped_existing"], 1)
        self.assertEqual(skipped["skipped_candidate"], 1)
        self.assertEqual(forced_failures, 0)
        self.assertEqual(forced["generated"], 1)

    def test_warnings_generate_manifest_and_are_aggregated(self):
        def warning_discoverer(system, _timeout):
            return {
                "system_id": system["system_id"],
                "entries": [{"id": "One", "url": "https://tlidb.com/cn/One"}],
                "displayed_entry_count": 3,
                "unique_entry_count": 1,
                "duplicate_occurrence_count": 2,
                "discovery_confidence": 0.65,
            }, {
                "warnings": [
                    "2 duplicate link occurrence(s) removed",
                    "displayed count 3 does not match unique count 1",
                ],
                "errors": [],
            }

        with tempfile.TemporaryDirectory() as directory:
            report, failures = run_batch(
                self.data,
                Path(directory),
                force=True,
                discoverer=warning_discoverer,
            )
            self.assertTrue((Path(directory) / "confirmed_manifest.json").is_file())
        self.assertEqual(failures, 0)
        self.assertEqual(report["generated"], 0)
        self.assertEqual(report["generated_with_warning"], 1)
        self.assertEqual(report["failed"], 0)
        self.assertEqual(report["warning_count"], 2)
        self.assertEqual(report["duplicate_removed_total"], 2)
        self.assertEqual(report["displayed_count_mismatch_total"], 1)

    def test_zero_unique_entries_is_failure(self):
        def empty_discoverer(system, _timeout):
            return {
                "system_id": system["system_id"],
                "entries": [],
                "unique_entry_count": 0,
            }, {"warnings": [], "errors": []}

        with tempfile.TemporaryDirectory() as directory:
            report, failures = run_batch(
                self.data,
                Path(directory),
                force=True,
                discoverer=empty_discoverer,
            )
        self.assertEqual(failures, 1)
        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["generated"], 0)
        self.assertEqual(report["generated_with_warning"], 0)


if __name__ == "__main__":
    unittest.main()
