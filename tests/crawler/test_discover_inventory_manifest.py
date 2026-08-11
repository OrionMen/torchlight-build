import json
import tempfile
import unittest
from pathlib import Path

from crawler.discover_inventory_manifest import (
    confirm_inventory_system,
    discover,
    extract_index_entries,
    inventory_url,
    nested_route_support,
)
from crawler.fetch_all_manifests import RateLimiter, fetch_entry
from crawler.validate_inventory_manifest import (
    audit_index_html,
    decide,
    validate_detail_html,
    validate_static_entries,
)


class InventoryDiscoveryTest(unittest.TestCase):
    def make_raw(self, root):
        raw = root / "raw"; html_dir = raw / "hero/raw_html"; meta_dir = raw / "hero/meta"
        html_dir.mkdir(parents=True); meta_dir.mkdir(parents=True)
        html_dir.joinpath("Page.html").write_text("""
            <a href="/cn/Inventory/STR_Helmet">力量头盔</a>
            <a href="https://tlidb.com/cn/Inventory/INT_Armor?view=1#stats">智慧护甲</a>
            <a href="Inventory/DEX_Boots">敏捷鞋</a>
            <a href="/cn/Inventory/STR_Helmet#again">重复</a>
            <a href="/cn/Anger">非 Inventory</a>
            <a href="https://example.com/cn/Inventory/External">外部</a>
        """, encoding="utf-8")
        meta_dir.joinpath("Page.meta.json").write_text(
            json.dumps({"final_url":"https://tlidb.com/cn/Page"}), encoding="utf-8")
        return raw

    def test_urljoin_inventory_index_uses_standard_file_base(self):
        entry, reason = inventory_url("STR_Helmet", "https://tlidb.com/cn/Inventory")
        self.assertEqual(reason, "accepted")
        self.assertEqual(entry["path"], "/cn/STR_Helmet")
        self.assertEqual(entry["slug"], "STR_Helmet")
        self.assertEqual(entry["url"], "https://tlidb.com/cn/STR_Helmet")
        self.assertNotEqual(entry["url"], "https://tlidb.com/cn/Inventory/STR_Helmet")
        self.assertEqual(entry["raw_href"], "STR_Helmet")

    def test_relative_absolute_root_query_fragment_and_malformed(self):
        base = "https://tlidb.com/cn/Inventory"
        for raw, expected in (
            ("DEX_Helmet", "https://tlidb.com/cn/DEX_Helmet"),
            ("STR_Chest_Armor", "https://tlidb.com/cn/STR_Chest_Armor"),
            ("https://tlidb.com/cn/DEX_Helmet", "https://tlidb.com/cn/DEX_Helmet"),
            ("/cn/STR_Chest_Armor", "https://tlidb.com/cn/STR_Chest_Armor"),
            ("STR_Helmet?q=1#part", "https://tlidb.com/cn/STR_Helmet?q=1"),
        ):
            self.assertEqual(inventory_url(raw, base)[0]["url"], expected)
        self.assertEqual(inventory_url("https://example.com/cn/X", base)[1], "external")
        self.assertEqual(inventory_url("/cn/Inventory/X", base)[1], "not_inventory")

    def test_index_uses_direct_relative_links_and_excludes_navigation(self):
        document = """
          <a href="STR_Helmet">STR Helmet</a>
          <a href="DEX_Helmet">DEX Helmet</a>
          <a href="/cn/Hero">Hero navigation</a>
          <a href="https://tlidb.com/cn/Help">Help navigation</a>
        """
        entries, report = extract_index_entries(document)
        self.assertEqual([item["slug"] for item in entries], ["STR_Helmet", "DEX_Helmet"])
        self.assertEqual(report["duplicate_entries"], 0)

    def test_snapshot_index_merge_manifest_and_completeness(self):
        with tempfile.TemporaryDirectory() as temporary:
            raw = self.make_raw(Path(temporary))
            index_html = "".join(
                f'<a href="Entry_{index}" data-i18n="item_type_list|name|{index}">Entry</a>'
                for index in range(147)
            ) + '<a href="Entry_0" data-i18n="item_type_list|name|dup">重复</a>'
            entries, index_report = extract_index_entries(index_html)
            self.assertEqual(len(entries), 147)
            self.assertEqual(index_report["duplicate_entries"], 1)
            manifest, report = discover(raw, index_html, 200)
            snapshot = report["existing_snapshot"]
            self.assertEqual(snapshot["raw_pages_scanned"], 0)
            self.assertTrue(report["index"]["inventory_index_complete"])
            self.assertEqual(report["index"]["direct_child_entries"], 147)
            self.assertTrue(report["index"]["all_entries_are_direct_children"])
            self.assertTrue(report["manifest"]["confirmed"])
            self.assertEqual(manifest["unique_entry_count"], 147)
            first = manifest["entries"][0]
            self.assertEqual(first["path"], "/cn/Entry_0")
            self.assertEqual(first["url"], "https://tlidb.com/cn/Entry_0")
            self.assertEqual(first["raw_href"], "Entry_0")
            self.assertEqual(first["source_locator"]["route_pattern"], "/cn/<inventory_entry>")
            self.assertEqual(first["source_locator"]["raw_href"], "Entry_0")
            self.assertEqual(first["source_locator"]["resolved_url"], "https://tlidb.com/cn/Entry_0")
            self.assertEqual(nested_route_support(), (True, True))

    def test_incomplete_index_does_not_confirm(self):
        with tempfile.TemporaryDirectory() as temporary:
            raw = self.make_raw(Path(temporary))
            manifest, report = discover(raw, '<a href="STR_Helmet" data-i18n="item_type_list|name|1">Only</a>', 200)
            self.assertIsNone(manifest)
            self.assertFalse(report["manifest"]["confirmed"])
            self.assertFalse(report["index"]["inventory_index_complete"])

    def test_confirm_preserves_other_system_and_source_order(self):
        original = {"systems": [
            {"system_id":"hero","discovery_status":"confirmed","source_order":0},
            {"system_id":"candidate_inventory","discovery_status":"candidate","classification_status":"needs_review",
             "manifest_path":"sources/candidate_inventory_manifest.json","source_order":2},
        ]}
        unchanged = confirm_inventory_system(original, 1, False)
        self.assertEqual(unchanged, original)
        updated = confirm_inventory_system(original, 9, True)
        self.assertEqual(updated["systems"][0], original["systems"][0])
        inventory = updated["systems"][1]
        self.assertEqual(inventory["system_id"], "inventory")
        self.assertEqual(inventory["discovery_status"], "confirmed")
        self.assertEqual(inventory["manifest_path"], "sources/inventory_manifest.json")
        self.assertEqual(inventory["source_order"], 2)

    def test_fetcher_uses_complete_manifest_entry_url(self):
        with tempfile.TemporaryDirectory() as temporary:
            seen = []
            def fake_fetch(url, timeout):
                seen.append(url)
                return {"body":b"<html></html>","http_status":200,"final_url":url}
            entry = {"id":"STR_Helmet","slug":"STR_Helmet","url":"https://tlidb.com/cn/STR_Helmet"}
            result = fetch_entry(entry, Path(temporary), True, 1, 0, RateLimiter(0), fetcher=fake_fetch)
            self.assertEqual(result["status"], "downloaded")
            self.assertEqual(seen, [entry["url"]])
            self.assertTrue(Path(temporary, "raw_html/STR_Helmet.html").is_file())

    def test_index_validation_detects_pagination_and_dynamic_loading(self):
        document = """
            <div class="pagination"><a href="?page=2">下一页</a></div>
            <a href="STR_Helmet" data-i18n="item_type_list|name|1">Helmet</a>
            <script>fetch('/cn/Inventory/list?page=2')</script>
        """
        audit = audit_index_html(document)
        self.assertTrue(audit["pagination_detected"])
        self.assertTrue(audit["dynamic_loading_detected"])
        self.assertEqual(audit["index_unique_direct_children"], 1)

    def test_stable_147_direct_children_have_no_hidden_route_evidence(self):
        document = "".join(f'<a href="Entry_{index}" data-i18n="item_type_list|name|{index}">Entry</a>' for index in range(147))
        audit = audit_index_html(document)
        self.assertEqual(audit["index_unique_direct_children"], 147)
        self.assertEqual(audit["index_deeper_routes"], 0)
        self.assertFalse(audit["pagination_detected"])
        self.assertFalse(audit["dynamic_loading_detected"])
        self.assertEqual(audit["hidden_route_evidence"], [])

    def test_detail_content_valid_404_and_redirect_detection(self):
        url = "https://tlidb.com/cn/STR_Helmet"
        valid_html = '<html><head><title>STR Helmet - TLIDB</title><link rel="canonical" href="/cn/STR_Helmet"></head><body>Inventory</body></html>'
        valid = validate_detail_html(url, 200, url, valid_html)
        self.assertTrue(valid["valid_content_page"])
        self.assertFalse(valid["redirected"])
        redirected = validate_detail_html("http://tlidb.com/cn/STR_Helmet", 200, url, valid_html)
        self.assertTrue(redirected["valid_content_page"])
        self.assertTrue(redirected["redirected"])
        missing = validate_detail_html(url, 404, url, "<title>404 Not Found</title><body>Error response</body>")
        self.assertFalse(missing["valid_content_page"])
        self.assertTrue(missing["error_shell_detected"])
        no_canonical = validate_detail_html(url, 200, url, "<title>STR Helmet - TLIDB</title><body>OK</body>")
        self.assertTrue(no_canonical["valid_content_page"])

    def test_confirmation_success_and_blocked(self):
        entries = [{"id":f"Entry_{index}","slug":f"Entry_{index}",
                    "path":f"/cn/Entry_{index}",
                    "url":f"https://tlidb.com/cn/Entry_{index}"} for index in range(147)]
        static = validate_static_entries(entries)
        index = audit_index_html("".join(f'<a href="Entry_{index}" data-i18n="item_type_list|name|{index}">E</a>' for index in range(147)))
        samples = []
        for index_value in range(5):
            url = entries[index_value]["url"]
            samples.append(validate_detail_html(url, 200, url,
                f'<title>Entry</title><link rel="canonical" href="{url}"><body>OK</body>'))
        # The decision requires the mandatory STR_Helmet sample.
        samples[0] = {**samples[0], "url":"https://tlidb.com/cn/STR_Helmet"}
        ready = decide(200, index, static, samples)
        self.assertTrue(ready["inventory_manifest_ready"])
        blocked_index = dict(index); blocked_index["pagination_detected"] = True
        blocked = decide(200, blocked_index, static, samples)
        self.assertFalse(blocked["inventory_manifest_ready"])


if __name__ == "__main__":
    unittest.main()
