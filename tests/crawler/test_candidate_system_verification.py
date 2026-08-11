import unittest
from pathlib import Path

from crawler.verify_candidate_systems import verify_candidates, verify_html


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/candidate_system_verification"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def system(system_id="candidate_active_skill", url="https://tlidb.com/cn/Active_Skill"):
    return {
        "system_id": system_id,
        "name_zh": "测试系统",
        "index_url": url,
        "discovery_status": "candidate",
        "source_order": 7,
    }


class CandidateSystemVerificationTest(unittest.TestCase):
    def test_confirmed_directory_metrics_deduplication_and_order(self):
        result = verify_html(system(), fixture("confirmed_directory.html"))
        self.assertEqual(result["classification"], "confirmed_directory")
        self.assertTrue(result["manifest_eligible"])
        self.assertEqual(result["recommended_system_id"], "active_skill")
        self.assertEqual(result["unique_entry_count"], 3)
        self.assertEqual(result["duplicate_entry_count"], 1)
        self.assertEqual([item["source_order"] for item in result["_entries"]], [0, 1, 2])
        self.assertEqual(result["external_link_count"], 1)
        self.assertEqual(result["static_asset_link_count"], 1)

    def test_relation_content_navigation_empty_ambiguous_and_single(self):
        cases = {
            "relation_index.html": "relation_index",
            "content_page.html": "content_page",
            "navigation_only.html": "navigation_only",
            "empty_page.html": "empty_or_invalid",
            "ambiguous_directory.html": "needs_review",
            "single_entry_directory.html": "needs_review",
        }
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                result = verify_html(system(), fixture(filename))
                self.assertEqual(result["classification"], expected)
                self.assertGreaterEqual(result["classification_confidence"], 0)
                self.assertLessEqual(result["classification_confidence"], 1)

    def test_unrelated_redirect_is_invalid(self):
        result = verify_html(
            system(),
            fixture("redirected_invalid.html"),
            final_url="https://tlidb.com/cn/Unrelated",
        )
        self.assertEqual(result["classification"], "empty_or_invalid")
        self.assertTrue(result["errors"])

    def test_same_input_is_stable(self):
        first = verify_html(system(), fixture("confirmed_directory.html"))
        second = verify_html(system(), fixture("confirmed_directory.html"))
        self.assertEqual(first, second)

    def test_only_candidate_index_url_is_requested(self):
        calls = []
        body = fixture("confirmed_directory.html").encode("utf-8")
        def fetcher(url, _timeout):
            calls.append(url)
            return body, 200, "utf-8", url

        manifest = {"systems": [system()]}
        results, count = verify_candidates(manifest, None, 1.0, fetcher=fetcher)
        self.assertEqual(count, 1)
        self.assertEqual(calls, ["https://tlidb.com/cn/Active_Skill"])
        self.assertEqual(results[0]["classification"], "confirmed_directory")


if __name__ == "__main__":
    unittest.main()
