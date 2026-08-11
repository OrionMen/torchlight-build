import tempfile
import unittest
from pathlib import Path

from crawler.discover_all_manifests import run_batch
from crawler.discover_systems import extract_system_candidates


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/system_discovery"


class SystemDiscoveryTest(unittest.TestCase):
    def test_navigation_filtering_mapping_deduplication_and_order(self):
        html = (FIXTURES / "top_navigation.html").read_text(encoding="utf-8")
        systems, report = extract_system_candidates(html, "https://tlidb.com/cn/")
        self.assertEqual(
            [item["system_id"] for item in systems],
            ["hero", "help", "candidate_activeskill"],
        )
        self.assertEqual(systems[0]["index_url"], "https://tlidb.com/cn/Hero")
        self.assertEqual([item["source_order"] for item in systems], [0, 1, 2])
        self.assertEqual(report["duplicate_system_url_count"], 1)
        excluded = report["excluded_link_counts_by_reason"]
        self.assertEqual(excluded["external_domain"], 1)
        self.assertEqual(excluded["static_resource"], 1)
        self.assertEqual(excluded["ordinary_content_page"], 1)

    def test_known_mapping_and_unknown_candidate_are_stable(self):
        html = (FIXTURES / "ambiguous_system_links.html").read_text(encoding="utf-8")
        first, _report = extract_system_candidates(html, "https://tlidb.com/cn/")
        second, _report = extract_system_candidates(html, "https://tlidb.com/cn/")
        self.assertEqual(first, second)
        self.assertEqual(first[0]["system_id"], "candidate_mysteryworkshop")
        self.assertEqual(first[0]["classification_status"], "needs_review")
        self.assertEqual(first[1]["system_id"], "hero")
        self.assertEqual(first[1]["discovery_status"], "confirmed")

    def test_batch_only_processes_confirmed_and_continues_after_failure(self):
        data = {
            "systems": [
                {"system_id": "one", "index_url": "https://tlidb.com/cn/One", "discovery_status": "confirmed"},
                {"system_id": "candidate_two", "index_url": "https://tlidb.com/cn/Two", "discovery_status": "candidate"},
                {"system_id": "three", "index_url": "https://tlidb.com/cn/Three", "discovery_status": "confirmed"},
            ]
        }
        def discoverer(system, _timeout):
            if system["system_id"] == "one":
                raise ValueError("fixture failure")
            return {
                "entries": [{"id": "One", "url": "https://tlidb.com/cn/One"}],
                "unique_entry_count": 1,
            }, {"warnings": [], "errors": []}

        with tempfile.TemporaryDirectory() as directory:
            report, failures = run_batch(data, Path(directory), discoverer=discoverer)
        self.assertEqual(failures, 1)
        self.assertEqual(report["generated"], 1)
        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["skipped_candidate"], 1)


if __name__ == "__main__":
    unittest.main()
