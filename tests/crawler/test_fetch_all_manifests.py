import hashlib
import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from crawler.fetch_all_manifests import (
    ProgressReporter,
    RateLimiter,
    fetch_system,
    format_duration,
    main,
    orchestrate,
    precompute_page_count,
    progress_metrics,
)


def response(body=b"<html>ok</html>"):
    return {
        "body": body,
        "http_status": 200,
        "content_type": "text/html; charset=utf-8",
        "encoding": "utf-8",
        "final_url": "https://tlidb.com/cn/Entry",
        "etag": '"fixture"',
        "last_modified": "Thu, 01 Jan 2026 00:00:00 GMT",
    }


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def source_manifest(*slugs):
    return {
        "entries": [
            {"id": slug, "slug": slug, "name_zh": slug, "url": f"https://tlidb.com/cn/{slug}"}
            for slug in slugs
        ]
    }


class FetchAllManifestsTest(unittest.TestCase):
    def test_progress_helpers_and_page_precompute(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "three.json"
            write_json(manifest, source_manifest("One", "Two", "Three"))
            systems = [{"system_id": "three", "manifest_path": str(manifest)}]
            total, counts, warnings = precompute_page_count(systems)
            self.assertEqual((total, counts, warnings), (3, {"three": 3}, []))
        self.assertEqual(progress_metrics(0, 10, 0), (None, None))
        self.assertEqual(progress_metrics(1, 10, 0.01), (None, None))
        self.assertEqual(progress_metrics(5, 10, 2), (2.5, 2.0))
        self.assertEqual(format_duration(93784), "1d 02:03:04")

    def test_cache_hit_and_force(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            output = root / "raw"
            write_json(manifest_path, source_manifest("Entry"))
            calls = []

            def fetcher(url, timeout):
                calls.append(url)
                return response()

            first = fetch_system("fixture", manifest_path, output, 1, RateLimiter(0), fetcher=fetcher)
            self.assertEqual((first["downloaded"], first["cache_hit"]), (1, 0))

            def must_not_fetch(url, timeout):
                raise AssertionError("cache should skip HTTP")

            cached = fetch_system("fixture", manifest_path, output, 1, RateLimiter(0), fetcher=must_not_fetch)
            self.assertEqual((cached["downloaded"], cached["cache_hit"]), (0, 1))
            meta = json.loads((output / "meta/Entry.meta.json").read_text(encoding="utf-8"))
            for key in (
                "url", "slug", "http_status", "content_type", "encoding", "download_time",
                "etag", "last_modified", "html_sha256", "content_length", "retry_count", "cache_hit",
            ):
                self.assertIn(key, meta)
            self.assertTrue(meta["cache_hit"])
            self.assertEqual(meta["html_sha256"], hashlib.sha256(b"<html>ok</html>").hexdigest())

            forced = fetch_system(
                "fixture", manifest_path, output, 1, RateLimiter(0), force=True, fetcher=fetcher
            )
            self.assertEqual((forced["downloaded"], forced["cache_hit"]), (1, 0))
            self.assertEqual(len(calls), 2)

    def test_http_200_empty_body_is_failure_and_not_cached(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            output = root / "raw"
            write_json(manifest_path, source_manifest("Empty"))
            report = fetch_system(
                "fixture", manifest_path, output, 1, RateLimiter(0), retries=0,
                fetcher=lambda url, timeout: response(b""),
            )
            self.assertEqual((report["downloaded"], report["failed"]), (0, 1))
            self.assertIn("empty body", report["errors"][0]["error"])
            self.assertFalse((output / "raw_html/Empty.html").exists())
            self.assertFalse((output / "meta/Empty.meta.json").exists())

    def test_zero_byte_cache_is_invalidated_and_refetched(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            output = root / "raw"
            write_json(manifest_path, source_manifest("Entry"))
            (output / "raw_html").mkdir(parents=True)
            (output / "raw_html/Entry.html").write_bytes(b"")
            write_json(output / "meta/Entry.meta.json", {
                "http_status": 200,
                "content_length": 0,
                "html_sha256": hashlib.sha256(b"").hexdigest(),
            })
            calls = []

            def fetcher(url, timeout):
                calls.append(url)
                return response(b"fresh html")

            report = fetch_system(
                "fixture", manifest_path, output, 1, RateLimiter(0), fetcher=fetcher
            )
            self.assertEqual((report["downloaded"], report["cache_hit"]), (1, 0))
            self.assertEqual(1, report["invalid_empty_cache_count"])
            self.assertEqual(
                [{"route": "/cn/Entry", "old_size": 0}],
                report["invalid_empty_cache_examples"],
            )
            self.assertEqual(1, len(calls))
            self.assertEqual(b"fresh html", (output / "raw_html/Entry.html").read_bytes())

    def test_cache_length_or_hash_mismatch_is_refetched(self):
        for meta in (
            {"content_length": 99},
            {"content_length": 6, "html_sha256": "wrong"},
        ):
            with self.subTest(meta=meta), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                manifest_path = root / "manifest.json"
                output = root / "raw"
                write_json(manifest_path, source_manifest("Entry"))
                (output / "raw_html").mkdir(parents=True)
                (output / "raw_html/Entry.html").write_bytes(b"cached")
                write_json(output / "meta/Entry.meta.json", meta)
                report = fetch_system(
                    "fixture", manifest_path, output, 1, RateLimiter(0),
                    fetcher=lambda url, timeout: response(b"replacement"),
                )
                self.assertEqual((report["downloaded"], report["cache_hit"]), (1, 0))
                self.assertEqual(
                    b"replacement", (output / "raw_html/Entry.html").read_bytes()
                )

    def test_retry_and_failure_do_not_stop_batch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            write_json(manifest_path, source_manifest("Retry", "Broken"))
            calls = {"Retry": 0, "Broken": 0}

            def fetcher(url, timeout):
                slug = url.rsplit("/", 1)[-1]
                calls[slug] += 1
                if slug == "Retry" and calls[slug] == 1:
                    raise OSError("temporary")
                if slug == "Broken":
                    raise OSError("permanent")
                return response(b"retry-ok")

            report = fetch_system(
                "fixture", manifest_path, root / "raw", 1, RateLimiter(0), retries=1,
                fetcher=fetcher, sleep=lambda delay: None,
            )
            self.assertEqual((report["downloaded"], report["failed"]), (1, 1))
            self.assertEqual(report["retry_count"], 2)
            self.assertEqual(calls, {"Retry": 2, "Broken": 2})
            self.assertTrue((root / "raw/raw_html/Retry.html").is_file())
            self.assertEqual(report["entries"][1]["status"], "failed")

    def test_aggregate_report_uses_confirmed_systems_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.json"
            second = root / "second.json"
            write_json(first, source_manifest("One"))
            write_json(second, source_manifest("Two", "Three"))
            system_manifest = {
                "systems": [
                    {"system_id": "first", "discovery_status": "confirmed", "manifest_path": str(first)},
                    {"system_id": "second", "discovery_status": "confirmed", "manifest_path": str(second)},
                    {"system_id": "candidate", "discovery_status": "candidate"},
                ]
            }
            total_path = root / "reports/all-fetch-report.json"
            report = orchestrate(
                system_manifest, root / "raw", total_path, None, False, 2, 0, 1, 0,
                fetcher=lambda url, timeout: response(url.encode()), sleep=lambda delay: None,
            )
            self.assertEqual(report["system_count"], 2)
            self.assertEqual(report["page_count"], 3)
            self.assertEqual(report["downloaded"], 3)
            self.assertEqual(report["failed"], 0)
            self.assertEqual([item["system_id"] for item in report["systems"]], ["first", "second"])
            self.assertTrue(total_path.is_file())
            self.assertTrue((root / "raw/first/reports/fetch-report.json").is_file())
            self.assertTrue((root / "raw/second/reports/fetch-report.json").is_file())

    def test_quiet_cache_heavy_progress_and_multi_system_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.json"
            second = root / "second.json"
            write_json(first, source_manifest("Cached", "Fresh"))
            write_json(second, source_manifest("Broken"))
            cached_dir = root / "raw/first"
            write_json(cached_dir / "meta/Cached.meta.json", {"url": "https://tlidb.com/cn/Cached"})
            (cached_dir / "raw_html").mkdir(parents=True)
            (cached_dir / "raw_html/Cached.html").write_bytes(b"cached")
            system_manifest = {"systems": [
                {"system_id": "first", "discovery_status": "confirmed", "manifest_path": str(first)},
                {"system_id": "second", "discovery_status": "confirmed", "manifest_path": str(second)},
            ]}
            output = StringIO()
            progress = ProgressReporter(quiet=True, output=output, tty=False)

            def fetcher(url, timeout):
                if url.endswith("Broken"):
                    raise OSError("broken")
                return response()

            report = orchestrate(
                system_manifest, root / "raw", root / "all.json", None, False, 1, 0, 1, 0,
                fetcher=fetcher, sleep=lambda delay: None, progress=progress,
            )
            self.assertEqual((report["downloaded"], report["cache_hit"], report["failed"]), (1, 1, 1))
            self.assertEqual(progress.overall_completed, 3)
            self.assertNotIn("Overall ", output.getvalue())
            self.assertIn("first complete", output.getvalue())
            self.assertIn("complete with failures", output.getvalue())

    def test_interrupt_message_preserves_existing_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            system_manifest = root / "systems.json"
            cached = root / "cached.html"
            write_json(system_manifest, {"systems": []})
            cached.write_bytes(b"keep")
            output = StringIO()
            reporter = ProgressReporter(output=output, tty=False)
            with patch("crawler.fetch_all_manifests.ProgressReporter", return_value=reporter), \
                    patch("crawler.fetch_all_manifests.orchestrate", side_effect=KeyboardInterrupt):
                result = main(["--system-manifest", str(system_manifest), "--all"])
            self.assertEqual(result, 130)
            self.assertEqual(cached.read_bytes(), b"keep")
            self.assertIn("Interrupted by user.", output.getvalue())
            self.assertIn("remain cached", output.getvalue())


if __name__ == "__main__":
    unittest.main()
