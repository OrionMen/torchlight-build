from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError

from crawler import discover_recovered_internal_pages as discovery
from crawler.fetch_all_manifests import (
    RateLimiter,
    fetch_system,
    update_recovered_rejected_state,
)


ROOT = Path(__file__).resolve().parents[2]


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def fixture(root: Path, href: str = "Candidate") -> tuple[Path, Path]:
    sources = root / "sources"
    raw = root / "raw"
    child = sources / "sample_manifest.json"
    write_json(child, {"entries": [{
        "id": "Index", "slug": "Index", "url": "https://tlidb.com/cn/Index",
    }]})
    systems = sources / "system_manifest.json"
    write_json(systems, {"systems": [{
        "system_id": "sample", "discovery_status": "confirmed",
        "manifest_path": str(child),
    }]})
    html = raw / "sample/raw_html/Index.html"
    html.parent.mkdir(parents=True)
    html.write_text(f'<a href="{href}">candidate</a>', encoding="utf-8")
    return systems, raw


def pending_entry(page_id: str = "Candidate", request_url: str | None = None) -> dict:
    return {
        "id": page_id,
        "slug": page_id,
        "url": f"https://tlidb.com/cn/{page_id}",
        "request_url": request_url or f"https://tlidb.com/cn/{page_id}",
        "source_examples": [{
            "system_id": "sample", "page_id": "Index",
            "source_url": "https://tlidb.com/cn/Index", "raw_href": page_id,
        }],
    }


def fetch_manifest(path: Path, *entries: dict) -> None:
    write_json(path, {
        "system_id": "recovered_internal_pages",
        "entries": list(entries),
    })


def response(body: bytes = b"<html>ok</html>") -> dict:
    return {"body": body, "http_status": 200}


class RecoveredPending404ConvergenceV1Test(unittest.TestCase):
    def test_recovered_only_404_becomes_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "pending.json"
            fetch_manifest(source, pending_entry())
            report = fetch_system(
                "recovered_internal_pages", source, root / "raw", 1, RateLimiter(0),
                retries=2, reject_recovered_404=True,
                fetcher=lambda url, timeout: (_ for _ in ()).throw(
                    HTTPError(url, 404, "Not Found", {}, None)
                ),
            )
            self.assertEqual((1, 0, 0), (
                report["rejected_permanent_404"], report["failed"], report["retry_count"]
            ))

    def test_rejected_candidate_is_excluded_from_production_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            systems, raw = fixture(Path(temporary))
            result = discovery.discover_recovered_pages(
                systems, raw, rejected_routes={"/cn/Candidate/"}
            )
            self.assertEqual(0, discovery.build_manifest(result)["entry_count"])
            self.assertEqual(["/cn/Candidate/"], result["rejected_routes_seen"])

    def test_rejected_candidate_is_not_pending_next_round(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            systems, raw = fixture(Path(temporary))
            result = discovery.discover_recovered_pages(
                systems, raw, rejected_routes={"/cn/Candidate/"}
            )
            self.assertEqual(0, result["pending_unfetched_count"])
            self.assertEqual(0, discovery.build_pending_fetch_manifest(result)["entry_count"])

    def test_formal_manifest_404_is_not_recovered_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "formal.json"
            fetch_manifest(source, pending_entry())
            report = fetch_system(
                "formal", source, root / "raw", 1, RateLimiter(0), retries=0,
                fetcher=lambda url, timeout: (_ for _ in ()).throw(
                    HTTPError(url, 404, "Not Found", {}, None)
                ),
            )
            self.assertEqual((0, 1), (report["rejected_permanent_404"], report["failed"]))

    def test_5xx_stays_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "pending.json"
            fetch_manifest(source, pending_entry())
            report = fetch_system(
                "recovered_internal_pages", source, root / "raw", 1, RateLimiter(0),
                retries=0, reject_recovered_404=True,
                fetcher=lambda url, timeout: (_ for _ in ()).throw(
                    HTTPError(url, 503, "Unavailable", {}, None)
                ),
            )
            self.assertEqual((0, 1), (report["rejected_permanent_404"], report["failed"]))

    def test_network_error_stays_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "pending.json"
            fetch_manifest(source, pending_entry())
            report = fetch_system(
                "recovered_internal_pages", source, root / "raw", 1, RateLimiter(0),
                retries=0, reject_recovered_404=True,
                fetcher=lambda url, timeout: (_ for _ in ()).throw(URLError("offline")),
            )
            self.assertEqual((0, 1), (report["rejected_permanent_404"], report["failed"]))

    def test_valid_recovered_page_fetches_normally(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "pending.json"
            fetch_manifest(source, pending_entry())
            report = fetch_system(
                "recovered_internal_pages", source, root / "raw", 1, RateLimiter(0),
                reject_recovered_404=True, fetcher=lambda url, timeout: response(),
            )
            self.assertEqual((1, 0, 0), (
                report["downloaded"], report["rejected_permanent_404"], report["failed"]
            ))

    def test_encoded_route_is_fetched_before_any_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "pending.json"
            entry = pending_entry("Rank_5+_Beacon", "https://tlidb.com/cn/Rank_5%2B_Beacon")
            fetch_manifest(source, entry)
            seen = []

            def fetcher(url: str, timeout: float) -> dict:
                seen.append(url)
                return response()

            report = fetch_system(
                "recovered_internal_pages", source, root / "raw", 1, RateLimiter(0),
                reject_recovered_404=True, fetcher=fetcher,
            )
            self.assertEqual(["https://tlidb.com/cn/Rank_5%2B_Beacon"], seen)
            self.assertEqual(1, report["downloaded"])

    def test_rejected_state_retains_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ss13/rejected.json"
            state = update_recovered_rejected_state(
                path, "ss13", [{**pending_entry(), "status": "rejected_permanent_404"}]
            )
            self.assertEqual(1, state["entry_count"])
            self.assertEqual("Index", state["entries"][0]["source_examples"][0]["page_id"])
            self.assertEqual({"/cn/Candidate/"}, discovery.load_rejected_routes(path))

    def test_rejected_state_is_season_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ss13/rejected.json"
            update_recovered_rejected_state(path, "ss13", [])
            with self.assertRaisesRegex(ValueError, "invalid recovered rejected state"):
                update_recovered_rejected_state(path, "test14", [])

    def test_existing_raw_is_reused_on_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "pending.json"
            fetch_manifest(source, pending_entry())
            raw = root / "raw"
            body = b"cached"
            (raw / "raw_html").mkdir(parents=True)
            (raw / "raw_html/Candidate.html").write_bytes(body)
            write_json(raw / "meta/Candidate.meta.json", {
                "http_status": 200,
                "content_length": len(body),
                "html_sha256": hashlib.sha256(body).hexdigest(),
            })
            report = fetch_system(
                "recovered_internal_pages", source, raw, 1, RateLimiter(0),
                reject_recovered_404=True,
                fetcher=lambda *_: self.fail("valid cache must be reused"),
            )
            self.assertEqual((1, 0), (report["cache_hit"], report["failed"]))

    def test_valid_fetch_then_discovery_converges(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            systems, raw = fixture(root)
            first = discovery.discover_recovered_pages(systems, raw)
            pending = root / "pending.json"
            write_json(pending, discovery.build_pending_fetch_manifest(first))
            fetched = fetch_system(
                "recovered_internal_pages", pending, raw / "recovered_internal_pages",
                1, RateLimiter(0), reject_recovered_404=True,
                fetcher=lambda *_: response(),
            )
            self.assertEqual(1, fetched["downloaded"])
            second = discovery.discover_recovered_pages(systems, raw)
            self.assertEqual(0, second["pending_unfetched_count"])
            self.assertEqual(1, discovery.build_manifest(second)["entry_count"])

    def test_pending_manifest_retains_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            systems, raw = fixture(Path(temporary))
            pending = discovery.build_pending_fetch_manifest(
                discovery.discover_recovered_pages(systems, raw)
            )
            source = pending["entries"][0]["source_examples"][0]
            self.assertEqual("Candidate", source["raw_href"])
            self.assertEqual("Index", source["page_id"])

    def test_max_round_and_stable_set_guards_remain_fail_fast(self) -> None:
        script = (ROOT / "scripts/rebuild_wiki.sh").read_text(encoding="utf-8")
        self.assertIn("round<=max_rounds", script)
        self.assertIn("previous_pending_hash", script)
        self.assertIn("did not reach zero pending routes", script)
        self.assertIn('--rejected-state "$recovered_rejected"', script)
        self.assertIn('--recovered-rejected-output "$recovered_rejected"', script)
        self.assertIn('recovered_rejected="$report_root/recovered-rejected-pages.json"', script)
        self.assertIn("set -euo pipefail", script)


if __name__ == "__main__":
    unittest.main()
