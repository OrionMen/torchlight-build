import json
import tempfile
import unittest
from pathlib import Path

from crawler.discover_missing_internal_pages import (
    classify_response,
    discover,
    semantic_url,
    validate_candidates,
)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class MissingInternalPagesDiscoveryTest(unittest.TestCase):
    def fixture(self, root):
        raw = root / "raw"
        inventory_html = raw / "inventory/raw_html/Inventory.html"
        inventory_html.parent.mkdir(parents=True)
        inventory_html.write_text('''
          <a href="STR_Helmet">Existing</a>
          <a href="Vorax_Limb:_Head">Vorax existing</a>
          <a href="Nether_Kings_Broken_Divinity:_Judgment">Missing</a>
          <a href="Nether_Kings_Broken_Divinity%3A_Judgment">Duplicate encoded</a>
          <a href="https://example.com/X">External</a>
          <a href="/asset/test.png">Asset</a>
        ''', encoding="utf-8")
        for system, slug in (("inventory", "STR_Helmet"), ("inventory", "Vorax_Limb:_Head")):
            path = raw / system / "raw_html" / (slug.replace(":", "%3A") + ".html")
            path.parent.mkdir(parents=True, exist_ok=True); path.write_text("<html></html>", encoding="utf-8")
        manifest = root / "inventory.json"
        write_json(manifest, {"entries": [
            {"id": "Inventory", "slug": "Inventory", "url": "https://tlidb.com/cn/Inventory"},
            {"id": "STR_Helmet", "slug": "STR_Helmet", "url": "https://tlidb.com/cn/STR_Helmet"},
            {"id": "Vorax_Limb:_Head", "slug": "Vorax_Limb:_Head", "url": "https://tlidb.com/cn/Vorax_Limb:_Head"},
        ]})
        systems = root / "systems.json"
        write_json(systems, {"systems": [{"system_id": "inventory", "discovery_status": "confirmed",
                                           "manifest_path": str(manifest)}]})
        catalog = root / "catalog.json"
        write_json(catalog, {"pages": [
            {"system_id": "inventory", "id": "STR_Helmet", "source_url": "https://tlidb.com/cn/STR_Helmet"},
        ]})
        return systems, raw, catalog

    def test_discovers_unique_missing_and_keeps_existing_pages_out(self):
        with tempfile.TemporaryDirectory() as temporary:
            systems, raw, catalog = self.fixture(Path(temporary))
            report = discover(systems, raw, catalog)
            self.assertEqual(report["internal_link_occurrences"], 4)
            self.assertEqual(report["unique_internal_targets"], 3)
            self.assertEqual(report["existing_targets"], 2)
            self.assertEqual(report["unique_missing_candidates"], 1)
            candidate = report["candidates"][0]
            self.assertEqual(candidate["canonical_url"],
                             "https://tlidb.com/cn/Nether_Kings_Broken_Divinity:_Judgment")
            self.assertEqual(candidate["request_url"],
                             "https://tlidb.com/cn/Nether_Kings_Broken_Divinity%3A_Judgment")
            self.assertEqual(candidate["occurrence_count"], 2)
            self.assertEqual(report["validation"]["status"], "not_run")

    def test_standard_source_url_resolution_avoids_wrong_directory(self):
        base = "https://tlidb.com/cn/Nether_Kings_Broken_Divinity"
        self.assertEqual(semantic_url("Nether_Kings_Broken_Divinity:_Judgment", base),
                         "https://tlidb.com/cn/Nether_Kings_Broken_Divinity:_Judgment")
        self.assertNotIn("/Nether_Kings_Broken_Divinity/Nether", semantic_url(
            "Nether_Kings_Broken_Divinity:_Judgment", base))
        self.assertIsNone(semantic_url("https://example.com/X", base))

    def test_validation_classification_and_cache_resume(self):
        candidate = {"canonical_url": "https://tlidb.com/cn/X", "canonical_path": "/cn/X",
                     "request_url": "https://tlidb.com/cn/X", "slug": "X", "source_examples": []}
        self.assertEqual(classify_response(candidate, 404, candidate["canonical_url"], "")["status"], "not_found")
        self.assertEqual(classify_response(candidate, 503, candidate["canonical_url"], "")["status"], "network_error")
        self.assertEqual(classify_response(candidate, 200, candidate["canonical_url"], "<title>X</title>")["status"], "available")
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "cache.json"
            write_json(cache, {"results": {candidate["canonical_url"]: {"status": "available", "http_status": 200}}})
            report = {"candidates": [dict(candidate)]}
            def must_not_run(item, timeout):
                raise AssertionError("stable cached result must be resumed")
            validated = validate_candidates(report, cache, 1, 0, 1, validator=must_not_run)
            self.assertEqual(validated["validation"]["available"], 1)


if __name__ == "__main__":
    unittest.main()
