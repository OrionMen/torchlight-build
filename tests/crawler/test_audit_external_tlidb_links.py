import json
import tempfile
import unittest
from pathlib import Path

from crawler.audit_external_tlidb_links import audit, external_tlidb_canonical


class ExternalTlidbLinksAuditTest(unittest.TestCase):
    def test_classifies_catalog_rewrite_bug_and_missing_candidates(self):
        with tempfile.TemporaryDirectory() as temporary:
            site = Path(temporary) / "site"
            page = site / "cn/Page/index.html"; page.parent.mkdir(parents=True)
            page.write_text('''
              <a href="https://tlidb.com/cn/STR_Helmet">STR</a>
              <a href="https://tlidb.com/cn/Nether_Kings_Broken_Divinity%3A_Judgment">Nether</a>
              <a href="https://www.tlidb.com/cn/Vorax_Limb%3A_Head">Vorax</a>
              <a href="https://example.com/cn/External">External</a>
              <a href="https://cdn.tlidb.com/a.png">Asset</a>
            ''', encoding="utf-8")
            (site / "catalog.json").write_text(json.dumps({"pages": [{
                "system_id": "inventory", "id": "STR_Helmet",
                "source_url": "https://tlidb.com/cn/STR_Helmet", "route": "cn/STR_Helmet/",
            }]}), encoding="utf-8")
            report = audit(site, site / "catalog.json")
            self.assertEqual(report["total_external_tlidb_internal_links"], 3)
            self.assertEqual(report["unique_urls"], 3)
            self.assertEqual(report["classification"]["catalog_entry_still_external"]["count"], 1)
            self.assertEqual(report["classification"]["catalog_incomplete_candidates"]["count"], 2)
            urls = {item["canonical_url"]: item for item in report["urls"]}
            self.assertTrue(urls["https://tlidb.com/cn/STR_Helmet"]["exists_in_catalog"])
            self.assertFalse(urls["https://tlidb.com/cn/Nether_Kings_Broken_Divinity:_Judgment"]["exists_in_catalog"])
            self.assertFalse(urls["https://tlidb.com/cn/Vorax_Limb:_Head"]["exists_in_catalog"])

    def test_canonical_filter_excludes_external_and_assets(self):
        self.assertEqual(external_tlidb_canonical("https://www.tlidb.com/cn/Vorax_Limb%3A_Head"),
                         "https://tlidb.com/cn/Vorax_Limb:_Head")
        self.assertIsNone(external_tlidb_canonical("https://example.com/cn/X"))
        self.assertIsNone(external_tlidb_canonical("https://tlidb.com/cn/app.js"))


if __name__ == "__main__":
    unittest.main()
