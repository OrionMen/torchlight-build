import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crawler.build_recovered_internal_pages_manifest import build_manifest, build_validation_report
from crawler.fetch_all_manifests import RateLimiter, fetch_system, main as fetch_main


class RecoveredInternalPagesManifestTest(unittest.TestCase):
    def candidates(self):
        values = []
        for index in range(1803):
            slug = f"Recovered_{index}"
            values.append({"canonical_url": f"https://tlidb.com/cn/{slug}",
                           "canonical_path": f"/cn/{slug}", "request_url": f"https://tlidb.com/cn/{slug}",
                           "slug": slug, "validation": {"status": "available", "http_status": 200},
                           "source_examples": [{"source_url": "https://tlidb.com/cn/Index", "raw_href": slug}]})
        values.append({"canonical_url": "https://tlidb.com/cn/Nether_Kings_Broken_Divinity:_Judgment",
                       "canonical_path": "/cn/Nether_Kings_Broken_Divinity:_Judgment",
                       "request_url": "https://tlidb.com/cn/Nether_Kings_Broken_Divinity%3A_Judgment",
                       "slug": "Nether_Kings_Broken_Divinity:_Judgment",
                       "validation": {"status": "available", "http_status": 200},
                       "source_examples": [{"source_url": "https://tlidb.com/cn/Index",
                                            "raw_href": "Nether_Kings_Broken_Divinity%3A_Judgment"}]})
        return values

    def test_builds_1804_validated_entries_and_preserves_canonical_transport_split(self):
        report = {"validation": {"available": 1804, "not_found": 0, "network_error": 0},
                  "candidates": self.candidates()}
        manifest = build_manifest(report)
        self.assertEqual(manifest["entry_count"], 1804)
        self.assertEqual(manifest["source"], {"type": "internal_link_recovery"})
        nether = next(item for item in manifest["entries"] if item["slug"].endswith(":_Judgment"))
        self.assertEqual(nether["url"], "https://tlidb.com/cn/Nether_Kings_Broken_Divinity:_Judgment")
        self.assertEqual(nether["request_url"], "https://tlidb.com/cn/Nether_Kings_Broken_Divinity%3A_Judgment")
        self.assertFalse(any(item["slug"] in {"Vorax_Limb:_Head", "STR_Helmet"} for item in manifest["entries"]))

    def test_duplicate_canonical_is_removed(self):
        candidates = self.candidates()
        duplicate = dict(candidates[0])
        duplicate["source_examples"] = [{"source_url": "https://tlidb.com/cn/Other", "raw_href": "Recovered_0"}]
        candidates.append(duplicate)
        manifest = build_manifest({"validation": {"available": 1805}, "candidates": candidates})
        self.assertEqual(manifest["entry_count"], 1804)
        self.assertEqual(manifest["duplicate_removed"], 1)
        self.assertEqual(len(manifest["entries"][0]["source_examples"]), 2)

    def test_vorax_canonical_and_transport_urls_are_preserved_when_available(self):
        candidate = {"canonical_url": "https://tlidb.com/cn/Vorax_Limb:_Head",
                     "canonical_path": "/cn/Vorax_Limb:_Head",
                     "request_url": "https://tlidb.com/cn/Vorax_Limb%3A_Head",
                     "slug": "Vorax_Limb:_Head", "validation": {"status": "available", "http_status": 200},
                     "source_examples": []}
        entry = build_manifest({"candidates": [candidate]})["entries"][0]
        self.assertEqual(entry["url"], candidate["canonical_url"])
        self.assertEqual(entry["request_url"], candidate["request_url"])

    def test_only_available_entries_are_confirmed_and_all_results_remain_in_validation_report(self):
        candidates = self.candidates()[:2]
        candidates[1]["validation"] = {"status": "network_error"}
        candidates.append({"canonical_url": "https://tlidb.com/cn/Not_Found",
                           "canonical_path": "/cn/Not_Found", "request_url": "https://tlidb.com/cn/Not_Found",
                           "slug": "Not_Found", "validation": {"status": "not_found", "http_status": 404},
                           "source_examples": []})
        discovery = {"validation": {"available": 1, "network_error": 1, "not_found": 1},
                     "candidates": candidates}
        manifest = build_manifest(discovery)
        self.assertEqual(manifest["entry_count"], 1)
        report = build_validation_report(discovery)
        self.assertEqual(report["candidate_count"], 3)
        self.assertEqual((report["available"], report["not_found"], report["network_error"]), (1, 1, 1))

    def test_fetch_uses_manifest_request_url(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); manifest_path = root / "recovered.json"
            entry = build_manifest({"validation": {"available": 1804},
                                    "candidates": self.candidates()})["entries"][-1]
            manifest_path.write_text(json.dumps({"entries": [entry]}), encoding="utf-8")
            seen = []
            def fetcher(url, timeout):
                seen.append(url); return {"body": b"ok", "http_status": 200, "final_url": url}
            report = fetch_system("recovered_internal_pages", manifest_path, root / "raw", 1,
                                  RateLimiter(0), fetcher=fetcher)
            self.assertEqual(seen, [entry["request_url"]])
            self.assertEqual(report["downloaded"], 1)

    def test_standalone_manifest_cli_does_not_require_system_manifest_membership(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); manifest_path = root / "recovered.json"
            manifest_path.write_text(json.dumps({"system_id": "recovered_internal_pages",
                                                  "entries": [self.candidates()[0]]}), encoding="utf-8")
            with patch("crawler.fetch_all_manifests.orchestrate",
                       return_value={"failed": 0, "errors": []}) as orchestrate:
                result = fetch_main(["--manifest", str(manifest_path),
                                     "--output-root", str(root / "raw"),
                                     "--report", str(root / "report.json"), "--quiet"])
            self.assertEqual(result, 0)
            supplied_systems = orchestrate.call_args.args[0]["systems"]
            self.assertEqual(supplied_systems[0]["system_id"], "recovered_internal_pages")


if __name__ == "__main__":
    unittest.main()
