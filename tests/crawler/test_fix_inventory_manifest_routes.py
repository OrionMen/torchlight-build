import unittest

from crawler.fix_inventory_manifest_routes import fix_manifest, resolve_inventory_href


class FixInventoryManifestRoutesTest(unittest.TestCase):
    def test_relative_inventory_routes_use_standard_urljoin(self):
        base = "https://tlidb.com/cn/Inventory"
        self.assertEqual(resolve_inventory_href(base, "STR_Helmet"),
                         ("https://tlidb.com/cn/STR_Helmet", "/cn/STR_Helmet"))
        self.assertEqual(resolve_inventory_href(base, "DEX_Helmet"),
                         ("https://tlidb.com/cn/DEX_Helmet", "/cn/DEX_Helmet"))

    def test_absolute_root_relative_query_and_fragment(self):
        base = "https://tlidb.com/cn/Inventory"
        cases = (
            ("https://tlidb.com/cn/STR_Helmet", "https://tlidb.com/cn/STR_Helmet"),
            ("/cn/DEX_Helmet", "https://tlidb.com/cn/DEX_Helmet"),
            ("STR_Helmet?v=1", "https://tlidb.com/cn/STR_Helmet?v=1"),
            ("STR_Helmet#stats", "https://tlidb.com/cn/STR_Helmet"),
        )
        for raw_href, expected in cases:
            self.assertEqual(resolve_inventory_href(base, raw_href)[0], expected)

    def test_manifest_preserves_fields_and_never_builds_nested_route(self):
        source = {
            "source": {"index_url": "https://tlidb.com/cn/Inventory", "http_status": 200},
            "entries": [{
                "id": "STR_Helmet", "slug": "STR_Helmet", "name_zh": "STR Helmet",
                "source_order": 0,
                "url": "https://tlidb.com/cn/Inventory/STR_Helmet",
                "path": "/cn/Inventory/STR_Helmet",
                "source_locator": {"raw_href": "STR_Helmet", "source": "index"},
            }],
        }
        fixed = fix_manifest(source)
        entry = fixed["entries"][0]
        self.assertEqual(entry["url"], "https://tlidb.com/cn/STR_Helmet")
        self.assertEqual(entry["path"], "/cn/STR_Helmet")
        self.assertNotIn("/cn/Inventory/", entry["url"])
        self.assertEqual(entry["source_locator"]["raw_href"], "STR_Helmet")
        self.assertEqual(entry["source_locator"]["resolved_url"], entry["url"])
        self.assertEqual(entry["source_locator"]["route_pattern"], "/cn/<inventory_entry>")
        self.assertEqual(entry["name_zh"], "STR Helmet")

    def test_legacy_entry_uses_slug_as_raw_href(self):
        fixed = fix_manifest({
            "source": {"index_url": "https://tlidb.com/cn/Inventory"},
            "entries": [{"id": "DEX_Helmet", "slug": "DEX_Helmet", "source_locator": {}}],
        })
        self.assertEqual(fixed["entries"][0]["source_locator"]["raw_href"], "DEX_Helmet")
        self.assertEqual(fixed["entries"][0]["url"], "https://tlidb.com/cn/DEX_Helmet")


if __name__ == "__main__":
    unittest.main()
