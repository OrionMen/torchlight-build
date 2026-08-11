import unittest
from pathlib import Path

from crawler.discover_system_manifest import discover_entries_from_html, discover_system


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/system_discovery"
INDEX_URL = "https://tlidb.com/cn/ActiveSkill"


class SystemManifestDiscoveryTest(unittest.TestCase):
    def test_container_scope_names_slugs_counts_and_duplicates(self):
        html = (FIXTURES / "system_index_cards.html").read_text(encoding="utf-8")
        entries, report = discover_entries_from_html(html, INDEX_URL, "active_skill")
        self.assertEqual([item["slug"] for item in entries], ["Flame_Jet", "Ice_Lance"])
        self.assertEqual([item["name_zh"] for item in entries], ["烈焰喷射", "冰锥术"])
        self.assertNotIn("Noise", [item["slug"] for item in entries])
        self.assertEqual(report["displayed_count"], 3)
        self.assertEqual(report["extracted_unique_count"], 2)
        self.assertEqual(report["duplicate_count"], 1)
        self.assertTrue(report["warnings"])
        self.assertTrue(all("source_locator" in item for item in entries))

    def test_count_mismatch_is_success_with_warning(self):
        html = (FIXTURES / "count_mismatch.html").read_text(encoding="utf-8")
        entries, report = discover_entries_from_html(html, "https://tlidb.com/cn/Test", "test")
        self.assertEqual(len(entries), 2)
        self.assertFalse(report["errors"])
        self.assertNotIn("incomplete", report)
        self.assertTrue(any("does not match" in item for item in report["warnings"]))

    def test_manifest_quality_records_duplicates_mismatch_and_confidence(self):
        html = (FIXTURES / "system_index_cards.html").read_text(encoding="utf-8")
        manifest, report = discover_system(
            {"system_id": "active_skill", "index_url": INDEX_URL},
            timeout=1,
            html=html,
        )
        self.assertEqual(manifest["unique_entry_count"], 2)
        self.assertEqual(manifest["duplicate_occurrence_count"], 1)
        self.assertEqual(manifest["quality"]["displayed_entry_count"], 3)
        self.assertEqual(manifest["quality"]["unique_entry_count"], 2)
        self.assertEqual(manifest["quality"]["duplicate_occurrence_count"], 1)
        self.assertTrue(manifest["quality"]["warnings"])
        self.assertGreaterEqual(manifest["discovery_confidence"], 0)
        self.assertLessEqual(manifest["discovery_confidence"], 1)
        self.assertFalse(report["errors"])

    def test_zero_unique_entries_fails(self):
        entries, report = discover_entries_from_html(
            "<section class='system-list'><h2>空目录 /0</h2></section>",
            "https://tlidb.com/cn/Empty",
            "empty",
        )
        self.assertEqual(entries, [])
        self.assertTrue(report["errors"])

    def test_same_input_is_stable_and_does_not_fetch_detail_pages(self):
        html = (FIXTURES / "system_index_cards.html").read_text(encoding="utf-8")
        first, _first_report = discover_entries_from_html(html, INDEX_URL, "active_skill")
        second, _second_report = discover_entries_from_html(html, INDEX_URL, "active_skill")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
