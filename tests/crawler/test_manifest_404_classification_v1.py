from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

from crawler.discover_manifest import classify_href
from crawler.fetch_all_manifests import (
    RateLimiter,
    fetch_system,
    known_missing_config_path,
    load_known_missing_contract,
)
from crawler.fetch_manifest import request_url_for


ROOT = Path(__file__).resolve().parents[2]
SS13_CONTRACT = ROOT / "config/seasons/ss13/known_missing_pages.json"
DROP_ROUTE = "/cn/An_exclusive_drop_from_the_Path_of_the_Brave_gameplay._An_exclusive_drop_from_the_Creation_Engine_gameplay_at_Profound_Timemark_8_or_higher"


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def manifest(*slugs: str) -> dict:
    return {
        "entries": [
            {
                "id": slug,
                "slug": slug,
                "name_zh": slug,
                "url": f"https://tlidb.com/cn/{slug}",
            }
            for slug in slugs
        ]
    }


class Manifest404ClassificationV1Test(unittest.TestCase):
    def test_three_permanent_missing_contracts_cover_three_failures(self) -> None:
        contract = load_known_missing_contract(SS13_CONTRACT, "ss13")
        self.assertEqual(3, len(contract))
        self.assertIn(("drop_source", DROP_ROUTE), contract)
        self.assertIn(("help", "/cn/Hero_Relic"), contract)
        self.assertIn(("hyperlink", "/cn/Hero_Relic"), contract)

    def test_rank_beacon_is_url_fix_not_known_missing(self) -> None:
        contract = load_known_missing_contract(SS13_CONTRACT, "ss13")
        self.assertNotIn(("hyperlink", "/cn/Rank_5%2B_Beacon"), contract)
        self.assertEqual(
            "https://tlidb.com/cn/Rank_5%2B_Beacon",
            request_url_for("https://tlidb.com/cn/Rank_5%2B_Beacon"),
        )
        self.assertEqual(
            "https://tlidb.com/cn/Rank_5%2B_Beacon",
            request_url_for("https://tlidb.com/cn/Rank_5+_Beacon"),
        )

    def test_failed_routes_are_legitimate_discovered_content_links(self) -> None:
        cases = (
            ("https://tlidb.com/cn/Drop_Source", DROP_ROUTE),
            ("https://tlidb.com/cn/Help", "/cn/Hero_Relic"),
            ("https://tlidb.com/cn/Hyperlink", "/cn/Rank_5%2B_Beacon"),
        )
        for index_url, route in cases:
            with self.subTest(route=route):
                canonical, _slug, reason = classify_href(route, index_url)
                self.assertEqual("accepted", reason)
                self.assertEqual(f"https://tlidb.com{route}", canonical)

    def test_permanent_missing_is_not_fetched(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "help.json"
            write_json(source, manifest("Hero_Relic"))
            contract = load_known_missing_contract(SS13_CONTRACT, "ss13")
            report = fetch_system(
                "help", source, root / "raw", 1, RateLimiter(0),
                known_missing_contract=contract,
                fetcher=lambda *_: self.fail("known missing must not use network"),
            )
            self.assertEqual((0, 1, 0), (report["downloaded"], report["known_missing"], report["failed"]))
            self.assertEqual("known_missing_detail", report["entries"][0]["status"])

    def test_unknown_404_remains_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "unknown.json"
            write_json(source, manifest("Unknown"))

            def not_found(url: str, timeout: float) -> dict:
                raise HTTPError(url, 404, "Not Found", {}, None)

            report = fetch_system(
                "help", source, root / "raw", 1, RateLimiter(0), retries=0,
                known_missing_contract=load_known_missing_contract(SS13_CONTRACT, "ss13"),
                fetcher=not_found,
            )
            self.assertEqual((0, 1), (report["known_missing"], report["failed"]))

    def test_transient_server_error_remains_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "transient.json"
            write_json(source, manifest("Transient"))

            def unavailable(url: str, timeout: float) -> dict:
                raise HTTPError(url, 503, "Unavailable", {}, None)

            report = fetch_system(
                "help", source, root / "raw", 1, RateLimiter(0), retries=0,
                known_missing_contract=load_known_missing_contract(SS13_CONTRACT, "ss13"),
                fetcher=unavailable,
            )
            self.assertEqual((0, 1), (report["known_missing"], report["failed"]))

    def test_known_missing_is_scoped_to_system(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "other.json"
            write_json(source, manifest("Hero_Relic"))
            calls = []

            def fetcher(url: str, timeout: float) -> dict:
                calls.append(url)
                return {"body": b"ok", "http_status": 200}

            report = fetch_system(
                "hero", source, root / "raw", 1, RateLimiter(0),
                known_missing_contract=load_known_missing_contract(SS13_CONTRACT, "ss13"),
                fetcher=fetcher,
            )
            self.assertEqual((1, 0), (report["downloaded"], report["known_missing"]))
            self.assertEqual(1, len(calls))

    def test_rerun_reuses_existing_raw_while_skipping_known_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "help.json"
            write_json(source, manifest("Cached", "Hero_Relic"))
            raw = root / "raw"
            body = b"cached"
            (raw / "raw_html").mkdir(parents=True)
            (raw / "raw_html/Cached.html").write_bytes(body)
            write_json(raw / "meta/Cached.meta.json", {
                "http_status": 200,
                "content_length": len(body),
                "html_sha256": hashlib.sha256(body).hexdigest(),
            })
            report = fetch_system(
                "help", source, raw, 1, RateLimiter(0),
                known_missing_contract=load_known_missing_contract(SS13_CONTRACT, "ss13"),
                fetcher=lambda *_: self.fail("cache rerun must not fetch these entries"),
            )
            self.assertEqual((1, 1, 0), (report["cache_hit"], report["known_missing"], report["failed"]))

    def test_custom_season_does_not_load_ss13_contract(self) -> None:
        path = known_missing_config_path("test14")
        self.assertEqual(ROOT / "config/seasons/test14/known_missing_pages.json", path)
        self.assertEqual({}, load_known_missing_contract(path, "test14"))

    def test_rebuild_and_fetch_keep_fail_fast_contract(self) -> None:
        rebuild = (ROOT / "scripts/rebuild_wiki.sh").read_text(encoding="utf-8")
        fetcher = (ROOT / "crawler/fetch_all_manifests.py").read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", rebuild)
        self.assertIn('return 1 if report["failed"] or report["errors"] else 0', fetcher)


if __name__ == "__main__":
    unittest.main()
