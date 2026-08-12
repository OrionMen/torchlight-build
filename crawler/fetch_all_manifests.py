from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from crawler.fetch_manifest import ROOT, USER_AGENT, request_url_for, ssl_context, write_json


class RateLimiter:
    def __init__(
        self,
        interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.interval = interval
        self.clock = clock
        self.sleep = sleep
        self.lock = threading.Lock()
        self.last_started: float | None = None

    def wait(self) -> None:
        if self.interval <= 0:
            return
        with self.lock:
            now = self.clock()
            if self.last_started is not None:
                remaining = self.interval - (now - self.last_started)
                if remaining > 0:
                    self.sleep(remaining)
                    now = self.clock()
            self.last_started = now


def fetch_once(url: str, timeout: float) -> dict:
    request_url = request_url_for(url)
    request = Request(request_url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout, context=ssl_context()) as response:
        return {
            "body": response.read(),
            "http_status": response.status,
            "content_type": response.headers.get("Content-Type", ""),
            "encoding": response.headers.get_content_charset() or "",
            "final_url": response.geturl(),
            "request_url": request_url,
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
        }


def load_source_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ValueError("manifest entries must be a list")
    urls = [entry.get("url") for entry in entries]
    ids = [entry.get("id") for entry in entries]
    if len(set(urls)) != len(urls) or len(set(ids)) != len(ids):
        raise ValueError("manifest contains duplicate URL or id")
    return data


def format_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "--"
    total = int(seconds)
    days, total = divmod(total, 86400)
    hours, total = divmod(total, 3600)
    minutes, seconds = divmod(total, 60)
    value = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{days}d {value}" if days else value


def human_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{int(value)} B" if unit == "B" else f"{value:.2f} {unit}"
        value /= 1024
    return f"{size} B"


def progress_metrics(completed: int, total: int, elapsed: float) -> tuple[float | None, float | None]:
    if elapsed < 0.1 or completed <= 0:
        return None, None
    speed = completed / elapsed
    eta = max(total - completed, 0) / speed if speed > 0 else None
    return speed, eta


def resolve_manifest_path(system: dict) -> Path:
    system_id = system.get("system_id")
    value = system.get("manifest_path") or f"sources/{system_id}_manifest.json"
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def precompute_page_count(systems: list[dict]) -> tuple[int, dict[str, int], list[dict]]:
    total = 0
    counts = {}
    warnings = []
    for system in systems:
        system_id = system.get("system_id")
        try:
            count = len(load_source_manifest(resolve_manifest_path(system))["entries"])
            counts[system_id] = count
            total += count
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            warnings.append({"system_id": system_id, "warning": f"Manifest unreadable: {exc}"})
    return total, counts, warnings


class ProgressReporter:
    def __init__(self, quiet: bool = False, output: TextIO = sys.stdout,
                 clock: Callable[[], float] = time.monotonic, tty: bool | None = None):
        self.quiet = quiet
        self.output = output
        self.clock = clock
        self.tty = output.isatty() if tty is None else tty
        self.started = 0.0
        self.total_pages = 0
        self.overall_completed = 0
        self.downloaded = 0
        self.cache_hit = 0
        self.failed = 0
        self.known_missing = 0
        self.retry_count = 0
        self.system_id = ""

    def start(self, systems: int, pages: int, max_workers: int, rate_limit: float,
              warnings: list[dict]) -> None:
        self.started = self.clock()
        self.total_pages = pages
        if self.quiet:
            return
        print("=" * 60, file=self.output)
        print("Torchlight Wiki Fetch", file=self.output)
        print(f"Systems: {systems}", file=self.output)
        print(f"Pages: {pages}", file=self.output)
        print(f"Max workers: {max_workers}", file=self.output)
        print(f"Rate limit: {rate_limit}s", file=self.output)
        for warning in warnings:
            print(f"Warning [{warning.get('system_id')}]: {warning['warning']}", file=self.output)
        print("=" * 60, file=self.output, flush=True)

    def system_started(self, index: int, total: int, system_id: str, pages: int) -> None:
        self.system_id = system_id
        if self.quiet:
            return
        print("-" * 60, file=self.output)
        print(f"[System {index}/{total}] {system_id}", file=self.output)
        print(f"Pages: {pages}", file=self.output)
        print(f"Overall before system: {self.overall_completed}/{self.total_pages}", file=self.output)
        print("-" * 60, file=self.output, flush=True)

    def page_completed(self, result: dict, system_completed: int, system_total: int) -> None:
        status = result.get("status")
        self.overall_completed += 1
        self.downloaded += int(status == "downloaded")
        self.cache_hit += int(status == "cache_hit")
        self.failed += int(status == "failed")
        self.known_missing += int(status == "known_missing_detail")
        self.retry_count += result.get("retry_count", 0)
        if self.quiet or (not self.tty and system_completed % 10 and system_completed != system_total):
            return
        speed, eta = progress_metrics(
            self.overall_completed, self.total_pages, self.clock() - self.started
        )
        speed_text = "-" if speed is None else f"{speed:.2f} page/s"
        eta_text = "--" if eta is None else format_duration(eta)
        line = (
            f"[{self.system_id}] {system_completed}/{system_total} | "
            f"Overall {self.overall_completed}/{self.total_pages} | DL {self.downloaded} | "
            f"Cache {self.cache_hit} | Missing {self.known_missing} | Fail {self.failed} | Retry {self.retry_count} | "
            f"{speed_text} | ETA {eta_text}"
        )
        print(line, end="\r" if self.tty else "\n", file=self.output, flush=True)

    def system_complete(self, report: dict) -> None:
        if self.tty and not self.quiet:
            print(file=self.output)
        failed = report["failed"] or report["errors"]
        label = "!" if failed else "✓"
        suffix = " complete with failures" if failed else " complete"
        print(f"{label} {report['system_id']}{suffix}", file=self.output)
        print(f"  Pages: {report['manifest_count']}", file=self.output)
        print(f"  Downloaded: {report['downloaded']}", file=self.output)
        print(f"  Cache: {report['cache_hit']}", file=self.output)
        print(f"  Failed: {report['failed']}", file=self.output)
        print(f"  Known missing: {report['known_missing']}", file=self.output)
        print(f"  Retry: {report['retry_count']}", file=self.output)
        print(f"  Elapsed: {format_duration(report['elapsed'])}", file=self.output, flush=True)
        for error in report["errors"]:
            print(f"  Error: {error.get('error', error)}", file=self.output, flush=True)

    def finished(self, report: dict, report_path: Path) -> None:
        completed = report["downloaded"] + report["cache_hit"] + report["known_missing"] + report["failed"]
        speed, _ = progress_metrics(completed, report["page_count"], report["elapsed"])
        try:
            display_path = report_path.relative_to(ROOT)
        except ValueError:
            display_path = report_path
        print("=" * 60, file=self.output)
        print("Fetch Finished", file=self.output)
        values = (
            ("Systems", report["system_count"]), ("Pages", report["page_count"]),
            ("Downloaded", report["downloaded"]), ("Cache", report["cache_hit"]),
            ("Failed", report["failed"]), ("Retry", report["retry_count"]),
            ("Known missing", report["known_missing"]),
            ("Elapsed", format_duration(report["elapsed"])),
            ("Average speed", "-" if speed is None else f"{speed:.2f} page/s"),
            ("Bytes", human_bytes(report["bytes"])), ("Report", display_path),
        )
        for label, value in values:
            print(f"{label}: {value}", file=self.output)
        if report["failed"] or report["errors"]:
            print("Completed with failures.", file=self.output)
        print("=" * 60, file=self.output, flush=True)

    def interrupted(self) -> None:
        if self.tty and not self.quiet:
            print(file=self.output)
        print("Interrupted by user.", file=self.output)
        print("Completed pages remain cached.", file=self.output)
        print("Run the same command again to resume.", file=self.output, flush=True)


def cache_result(
    entry: dict, html_path: Path, meta_path: Path
) -> tuple[dict | None, dict | None]:
    if not html_path.is_file() or not meta_path.is_file():
        return None, None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        body = html_path.read_bytes()
    except (OSError, json.JSONDecodeError):
        return None, None
    digest = hashlib.sha256(body).hexdigest()
    old_size = len(body)
    invalid_reason = None
    if old_size == 0:
        invalid_reason = "empty_html"
    elif meta.get("content_length") is not None and meta["content_length"] != old_size:
        invalid_reason = "content_length_mismatch"
    elif meta.get("html_sha256") and meta["html_sha256"] != digest:
        invalid_reason = "html_sha256_mismatch"
    elif meta.get("http_status") not in (None, 200):
        invalid_reason = "http_status_not_200"
    if invalid_reason:
        return None, {
            "route": entry.get("path") or urlsplit(entry["url"]).path,
            "id": entry.get("id"),
            "old_size": old_size,
            "reason": invalid_reason,
        }
    normalized = {
        **meta,
        "schema_version": 1,
        "id": entry.get("id"),
        "url": meta.get("url") or meta.get("source_url") or entry["url"],
        "final_url": meta.get("final_url") or meta.get("source_url") or entry["url"],
        "slug": entry["slug"],
        "name_zh": entry.get("name_zh"),
        "http_status": meta.get("http_status", 200),
        "content_type": meta.get("content_type", ""),
        "encoding": meta.get("encoding", ""),
        "download_time": meta.get("download_time") or meta.get("fetched_at"),
        "etag": meta.get("etag"),
        "last_modified": meta.get("last_modified"),
        "html_sha256": digest,
        "content_length": len(body),
        "retry_count": 0,
        "cache_hit": True,
    }
    write_json(meta_path, normalized)
    return {
        "id": entry.get("id"),
        "slug": entry["slug"],
        "url": entry["url"],
        "status": "cache_hit",
        "http_status": normalized["http_status"],
        "bytes": len(body),
        "retry_count": 0,
        "cache_hit": True,
        "html_sha256": digest,
    }, None


def fetch_entry(
    entry: dict,
    output_dir: Path,
    force: bool,
    timeout: float,
    retries: int,
    rate_limiter: RateLimiter,
    fetcher: Callable[[str, float], dict] = fetch_once,
    sleep: Callable[[float], None] = time.sleep,
    backoff_base: float = 0.5,
) -> dict:
    slug = entry.get("slug")
    url = entry.get("url")
    fetch_url = entry.get("request_url") or url
    if not isinstance(slug, str) or not slug or not isinstance(url, str) or not url:
        return {
            "id": entry.get("id"),
            "slug": slug,
            "url": url,
            "status": "failed",
            "bytes": 0,
            "retry_count": 0,
            "cache_hit": False,
            "error": "manifest entry requires non-empty slug and url",
        }
    validation = entry.get("validation") or {}
    if validation.get("status") == "not_found":
        return {
            "id": entry.get("id"), "slug": slug, "url": url,
            "status": "known_missing_detail",
            "http_status": validation.get("http_status", 404),
            "reason": validation.get("reason", "detail_page_missing"),
            "bytes": 0, "retry_count": 0, "cache_hit": False,
        }
    stem = quote(slug, safe="-_.")
    html_path = output_dir / f"raw_html/{stem}.html"
    meta_path = output_dir / f"meta/{stem}.meta.json"
    invalid_cache = None
    if not force:
        cached, invalid_cache = cache_result(entry, html_path, meta_path)
        if cached is not None:
            return cached

    error = ""
    for attempt in range(retries + 1):
        try:
            rate_limiter.wait()
            response = fetcher(fetch_url, timeout)
            body = response["body"]
            status = response["http_status"]
            if status != 200:
                raise ValueError(f"HTTP {status}")
            if not isinstance(body, bytes):
                raise ValueError("HTTP fetcher must return raw bytes")
            if not body:
                raise ValueError("HTTP 200 returned empty body")
            digest = hashlib.sha256(body).hexdigest()
            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_bytes(body)
            meta = {
                "schema_version": 1,
                "id": entry.get("id"),
                "url": url,
                "source_url": url,
                "request_url": response.get("request_url") or request_url_for(fetch_url),
                "final_url": response.get("final_url") or url,
                "slug": slug,
                "name_zh": entry.get("name_zh"),
                "http_status": status,
                "content_type": response.get("content_type", ""),
                "encoding": response.get("encoding", ""),
                "download_time": datetime.now(timezone.utc).isoformat(),
                "etag": response.get("etag"),
                "last_modified": response.get("last_modified"),
                "html_sha256": digest,
                "content_length": len(body),
                "retry_count": attempt,
                "cache_hit": False,
            }
            write_json(meta_path, meta)
            result = {
                "id": entry.get("id"),
                "slug": slug,
                "url": url,
                "request_url": response.get("request_url") or request_url_for(fetch_url),
                "status": "downloaded",
                "http_status": status,
                "bytes": len(body),
                "retry_count": attempt,
                "cache_hit": False,
                "html_sha256": digest,
            }
            if invalid_cache:
                result["invalid_cache"] = invalid_cache
            return result
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError) as exc:
            error = str(exc)
            if attempt < retries:
                sleep(backoff_base * (2 ** attempt))
    result = {
        "id": entry.get("id"),
        "slug": slug,
        "url": url,
        "status": "failed",
        "bytes": 0,
        "retry_count": retries,
        "cache_hit": False,
        "error": error,
    }
    if invalid_cache:
        result["invalid_cache"] = invalid_cache
    return result


def fetch_system(
    system_id: str,
    manifest_path: Path,
    output_dir: Path,
    max_workers: int,
    rate_limiter: RateLimiter,
    force: bool = False,
    timeout: float = 20.0,
    retries: int = 2,
    fetcher: Callable[[str, float], dict] = fetch_once,
    sleep: Callable[[float], None] = time.sleep,
    progress_callback: Callable[[dict, int, int], None] | None = None,
) -> dict:
    started = time.monotonic()
    report = {
        "schema_version": 1,
        "system_id": system_id,
        "manifest": str(manifest_path),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "manifest_count": 0,
        "downloaded": 0,
        "cache_hit": 0,
        "failed": 0,
        "known_missing": 0,
        "invalid_empty_cache_count": 0,
        "invalid_empty_cache_examples": [],
        "retry_count": 0,
        "bytes": 0,
        "elapsed": 0.0,
        "warnings": [],
        "errors": [],
        "entries": [],
    }
    try:
        manifest = load_source_manifest(manifest_path)
        entries = manifest["entries"]
        report["manifest_count"] = len(entries)
        results: dict[int, dict] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    fetch_entry,
                    entry,
                    output_dir,
                    force,
                    timeout,
                    retries,
                    rate_limiter,
                    fetcher,
                    sleep,
                ): index
                for index, entry in enumerate(entries)
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    results[index] = future.result()
                except Exception as exc:
                    results[index] = {
                        "id": entries[index].get("id"),
                        "slug": entries[index].get("slug"),
                        "url": entries[index].get("url"),
                        "status": "failed",
                        "bytes": 0,
                        "retry_count": 0,
                        "cache_hit": False,
                        "error": str(exc),
                    }
                if progress_callback is not None:
                    progress_callback(results[index], len(results), len(entries))
        report["entries"] = [results[index] for index in sorted(results)]
        for result in report["entries"]:
            report["downloaded"] += int(result["status"] == "downloaded")
            report["cache_hit"] += int(result["status"] == "cache_hit")
            report["failed"] += int(result["status"] == "failed")
            report["known_missing"] += int(result["status"] == "known_missing_detail")
            invalid_cache = result.get("invalid_cache") or {}
            if invalid_cache.get("reason") == "empty_html":
                report["invalid_empty_cache_count"] += 1
                report["invalid_empty_cache_examples"].append({
                    "route": invalid_cache.get("route"),
                    "old_size": invalid_cache.get("old_size", 0),
                })
            report["retry_count"] += result.get("retry_count", 0)
            if result["status"] == "downloaded":
                report["bytes"] += result.get("bytes", 0)
            if result.get("error"):
                report["errors"].append({"id": result.get("id"), "error": result["error"]})
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report["errors"].append({"error": str(exc)})
    report["elapsed"] = round(time.monotonic() - started, 3)
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_json(output_dir / "reports/fetch-report.json", report)
    return report


def selected_systems(system_manifest: dict, requested_id: str | None) -> list[dict]:
    systems = system_manifest.get("systems")
    if not isinstance(systems, list):
        raise ValueError("system manifest must contain a systems list")
    confirmed = [item for item in systems if item.get("discovery_status") == "confirmed"]
    if requested_id is None:
        return confirmed
    matches = [item for item in confirmed if item.get("system_id") == requested_id]
    if len(matches) != 1:
        raise ValueError(f"unknown confirmed system_id: {requested_id}")
    return matches


def orchestrate(
    system_manifest: dict,
    output_root: Path,
    report_path: Path,
    requested_id: str | None,
    force: bool,
    max_workers: int,
    rate_limit: float,
    timeout: float,
    retries: int,
    fetcher: Callable[[str, float], dict] = fetch_once,
    sleep: Callable[[float], None] = time.sleep,
    progress: ProgressReporter | None = None,
) -> dict:
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    systems = selected_systems(system_manifest, requested_id)
    total_pages, page_counts, preflight_warnings = precompute_page_count(systems)
    if progress is not None:
        progress.start(len(systems), total_pages, max_workers, rate_limit, preflight_warnings)
    limiter = RateLimiter(rate_limit, sleep=sleep)
    reports = []
    total_errors = []
    for system_index, system in enumerate(systems, 1):
        system_id = system.get("system_id")
        manifest_path = resolve_manifest_path(system)
        if progress is not None:
            progress.system_started(
                system_index, len(systems), system_id, page_counts.get(system_id, 0)
            )
        system_report = fetch_system(
            system_id,
            manifest_path,
            output_root / system_id,
            max_workers,
            limiter,
            force=force,
            timeout=timeout,
            retries=retries,
            fetcher=fetcher,
            sleep=sleep,
            progress_callback=progress.page_completed if progress is not None else None,
        )
        reports.append(system_report)
        if progress is not None:
            progress.system_complete(system_report)
        total_errors.extend(
            {"system_id": system_id, **error} for error in system_report["errors"]
        )
    report = {
        "schema_version": 1,
        "started_at": started_at,
        "system_count": len(reports),
        "page_count": sum(item["manifest_count"] for item in reports),
        "downloaded": sum(item["downloaded"] for item in reports),
        "cache_hit": sum(item["cache_hit"] for item in reports),
        "failed": sum(item["failed"] for item in reports),
        "known_missing": sum(item["known_missing"] for item in reports),
        "invalid_empty_cache_count": sum(
            item["invalid_empty_cache_count"] for item in reports
        ),
        "invalid_empty_cache_examples": [
            {"system_id": item["system_id"], **example}
            for item in reports
            for example in item["invalid_empty_cache_examples"]
        ],
        "retry_count": sum(item["retry_count"] for item in reports),
        "bytes": sum(item["bytes"] for item in reports),
        "elapsed": round(time.monotonic() - started, 3),
        "warnings": preflight_warnings + [
            {"system_id": item["system_id"], "warning": warning}
            for item in reports
            for warning in item["warnings"]
        ],
        "errors": total_errors,
        "systems": [
            {
                key: item[key]
                for key in (
                    "system_id", "manifest_count", "downloaded", "cache_hit",
                    "known_missing", "invalid_empty_cache_count",
                    "invalid_empty_cache_examples", "failed", "retry_count",
                    "bytes", "elapsed", "warnings", "errors",
                )
            }
            for item in reports
        ],
    }
    write_json(report_path, report)
    if progress is not None:
        progress.finished(report, report_path)
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Fetch raw HTML for all confirmed system manifests")
    parser.add_argument("--system-manifest", type=Path, default=Path("sources/system_manifest.json"))
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--system-id")
    selection.add_argument("--all", action="store_true")
    selection.add_argument("--manifest", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("data/raw/manifests"))
    parser.add_argument("--report", type=Path, default=Path("data/reports/fetch-all/all-fetch-report.json"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--rate-limit", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    progress = None
    try:
        if args.max_workers < 1 or args.rate_limit < 0 or args.timeout <= 0 or args.retries < 0:
            raise ValueError("invalid max-workers, rate-limit, timeout, or retries")
        manifest_path = args.system_manifest if args.system_manifest.is_absolute() else ROOT / args.system_manifest
        output_root = args.output_root if args.output_root.is_absolute() else ROOT / args.output_root
        report_path = args.report if args.report.is_absolute() else ROOT / args.report
        if args.manifest:
            direct_path = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
            direct = load_source_manifest(direct_path)
            direct_system_id = direct.get("system_id") or direct_path.stem.removesuffix("_manifest")
            system_manifest = {"systems": [{"system_id": direct_system_id,
                "discovery_status": "confirmed", "manifest_path": str(direct_path)}]}
            requested_id = direct_system_id
        else:
            system_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            requested_id = None if args.all else args.system_id
        progress = ProgressReporter(quiet=args.quiet)
        report = orchestrate(
            system_manifest,
            output_root,
            report_path,
            requested_id,
            args.force,
            args.max_workers,
            args.rate_limit,
            args.timeout,
            args.retries,
            progress=progress,
        )
        return 1 if report["failed"] or report["errors"] else 0
    except KeyboardInterrupt:
        if progress is None:
            progress = ProgressReporter(quiet=args.quiet)
        progress.interrupted()
        return 130
    except Exception as exc:
        if args.debug:
            traceback.print_exc()
        print(f"All-system raw fetch failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
