from __future__ import annotations

import argparse
import hashlib
import json
import ssl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "torchlight-build/0.1 (+manifest fetch)"


def request_url_for(source_url: str) -> str:
    parsed = urlsplit(source_url)
    # Keep an encoded plus encoded. Some TLIDB routes use %2B as a literal
    # path identity and return 404 when it is rewritten to a bare "+".
    safe_segment = "-._~!$&'()*,;=@"
    encoded_path = "/".join(quote(unquote(segment), safe=safe_segment)
                            for segment in parsed.path.split("/"))
    return urlunsplit((parsed.scheme, parsed.netloc, encoded_path, parsed.query, ""))


def ssl_context():
    paths = ssl.get_default_verify_paths()
    system_ca = Path("/etc/ssl/cert.pem")
    if not paths.cafile and system_ca.is_file():
        return ssl.create_default_context(cafile=str(system_ca))
    return None


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ValueError("manifest entries must be a list")
    urls = [entry.get("url") for entry in entries]
    ids = [entry.get("id") for entry in entries]
    if len(set(urls)) != len(urls) or len(set(ids)) != len(ids):
        raise ValueError("manifest contains duplicate URL or id")
    return data


def fetch_once(url: str, timeout: float) -> tuple[bytes, int, str, str, str, str]:
    request_url = request_url_for(url)
    request = Request(request_url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout, context=ssl_context()) as response:
        return (
            response.read(),
            response.status,
            response.headers.get("Content-Type", ""),
            response.headers.get_content_charset() or "",
            response.geturl(),
            request_url,
        )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Fetch pages listed by a source manifest")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.retries < 0 or args.interval < 0 or args.timeout <= 0:
        print("Fetch failed: invalid timeout, retries, or interval", file=sys.stderr)
        return 1
    if args.limit is not None and args.limit < 1:
        print("Fetch failed: limit must be positive", file=sys.stderr)
        return 1

    manifest_path = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    output = args.output if args.output.is_absolute() else ROOT / args.output
    report_path = output / "reports/fetch-report.json"
    report = {
        "schema_version": 1,
        "manifest": str(args.manifest),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "requested": 0,
        "fetched": 0,
        "cached": 0,
        "failed": 0,
        "retry_count": 0,
        "entries": [],
        "errors": [],
    }
    try:
        manifest = load_manifest(manifest_path)
        entries = manifest["entries"][: args.limit] if args.limit else manifest["entries"]
        report["requested"] = len(entries)
        for index, entry in enumerate(entries):
            if index and args.interval:
                time.sleep(args.interval)
            slug = entry.get("slug")
            url = entry.get("url")
            if not isinstance(slug, str) or not slug or not isinstance(url, str) or not url:
                raise ValueError("manifest entry requires non-empty slug and url")
            stem = quote(slug, safe="-_.")
            html_path = output / f"raw_html/{stem}.html"
            meta_path = output / f"meta/{stem}.meta.json"
            if not args.force and html_path.is_file() and meta_path.is_file():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                digest = hashlib.sha256(html_path.read_bytes()).hexdigest()
                if meta.get("sha256") == digest:
                    if not meta.get("final_url"):
                        meta["final_url"] = meta.get("source_url", url)
                        write_json(meta_path, meta)
                    report["cached"] += 1
                    report["entries"].append(
                        {
                            "id": entry.get("id"),
                            "status": "cached",
                            "http_status": meta.get("http_status"),
                            "final_url": meta.get("final_url"),
                            "bytes": meta.get("byte_count"),
                            "sha256": digest,
                            "attempts": 0,
                            "retries": 0,
                        }
                    )
                    continue

            error = None
            for attempt in range(args.retries + 1):
                try:
                    body, status, content_type, encoding, final_url, request_url = fetch_once(url, args.timeout)
                    if status != 200:
                        raise ValueError(f"HTTP {status}")
                    digest = hashlib.sha256(body).hexdigest()
                    html_path.parent.mkdir(parents=True, exist_ok=True)
                    html_path.write_bytes(body)
                    meta = {
                        "schema_version": 1,
                        "id": entry.get("id"),
                        "slug": slug,
                        "name_zh": entry.get("name_zh"),
                        "source_url": url,
                        "request_url": request_url,
                        "final_url": final_url,
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "http_status": status,
                        "content_type": content_type,
                        "encoding": encoding,
                        "byte_count": len(body),
                        "sha256": digest,
                    }
                    write_json(meta_path, meta)
                    report["fetched"] += 1
                    report["retry_count"] += attempt
                    report["entries"].append(
                        {
                            "id": entry.get("id"),
                            "status": "fetched",
                            "http_status": status,
                            "final_url": final_url,
                            "bytes": len(body),
                            "sha256": digest,
                            "attempts": attempt + 1,
                            "retries": attempt,
                        }
                    )
                    error = None
                    break
                except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
                    error = str(exc)
                    if attempt < args.retries:
                        time.sleep(min(args.interval, 1.0))
            if error is not None:
                report["failed"] += 1
                report["retry_count"] += args.retries
                report["errors"].append({"id": entry.get("id"), "error": error})
                report["entries"].append(
                    {
                        "id": entry.get("id"),
                        "status": "failed",
                        "attempts": args.retries + 1,
                        "retries": args.retries,
                        "error": error,
                    }
                )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report["failed"] += 1
        report["errors"].append({"error": str(exc)})

    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_json(report_path, report)
    if args.report:
        extra_report = args.report if args.report.is_absolute() else ROOT / args.report
        if extra_report != report_path:
            write_json(extra_report, report)
    print("Manifest fetch")
    print(f"- requested: {report['requested']}")
    print(f"- fetched: {report['fetched']}")
    print(f"- cached: {report['cached']}")
    print(f"- failed: {report['failed']}")
    print(f"- retries: {report['retry_count']}")
    print(f"- report: {report_path.relative_to(ROOT) if report_path.is_relative_to(ROOT) else report_path}")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
