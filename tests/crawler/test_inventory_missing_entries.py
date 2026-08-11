import json
import tempfile
import unittest
from pathlib import Path

from crawler.fetch_all_manifests import RateLimiter, fetch_system
from crawler.fix_inventory_manifest_routes import apply_inventory_validation


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


class InventoryMissingEntriesTest(unittest.TestCase):
    def test_retracted_not_found_entries_are_all_available(self):
        entries = [{"id": f"Available_{index}", "slug": f"Available_{index}"} for index in range(146)]
        entries.append({"id": "Vorax_Limb:_Head", "slug": "Vorax_Limb:_Head",
                        "validation": {"status": "not_found", "http_status": 404}})
        validated = apply_inventory_validation({"entries": entries})
        statuses = [entry["validation"]["status"] for entry in validated["entries"]]
        self.assertEqual(statuses.count("available"), 147)
        self.assertEqual(statuses.count("not_found"), 0)
        self.assertEqual(len(validated["entries"]), 147)
        vorax = next(entry for entry in validated["entries"] if entry["id"] == "Vorax_Limb:_Head")
        self.assertEqual(vorax["validation"], {"status": "available", "http_status": 200})

    def test_revalidated_vorax_is_not_skipped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "inventory.json"
            write_json(manifest, {"entries": [{
                "id": "Vorax_Limb:_Head", "slug": "Vorax_Limb:_Head",
                "url": "https://tlidb.com/cn/Vorax_Limb:_Head",
                "validation": {"status": "available", "http_status": 200},
            }]})
            calls = []
            def fetcher(url, timeout):
                calls.append(url)
                return {"body": b"ok", "http_status": 200, "final_url": url}
            report = fetch_system("inventory", manifest, root / "raw", 1, RateLimiter(0),
                                  fetcher=fetcher)
            self.assertEqual(calls, ["https://tlidb.com/cn/Vorax_Limb:_Head"])
            self.assertEqual(report["known_missing"], 0)
            self.assertEqual(report["failed"], 0)
            self.assertEqual(report["entries"][0]["status"], "downloaded")
            meta = json.loads((root / "raw/meta/Vorax_Limb%3A_Head.meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["source_url"], "https://tlidb.com/cn/Vorax_Limb:_Head")
            self.assertEqual(meta["request_url"], "https://tlidb.com/cn/Vorax_Limb%3A_Head")

    def test_unvalidated_other_system_keeps_existing_fetch_behavior(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "hero.json"
            write_json(manifest, {"entries": [{
                "id": "Broken", "slug": "Broken", "url": "https://tlidb.com/cn/Broken",
            }]})
            report = fetch_system("hero", manifest, root / "raw", 1, RateLimiter(0), retries=0,
                                  fetcher=lambda url, timeout: (_ for _ in ()).throw(OSError("failed")))
            self.assertEqual(report["known_missing"], 0)
            self.assertEqual(report["failed"], 1)


if __name__ == "__main__":
    unittest.main()
