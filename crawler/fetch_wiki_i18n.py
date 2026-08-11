from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

from crawler.fetch_manifest import USER_AGENT, request_url_for, ssl_context, write_json


ROOT = Path(__file__).resolve().parents[1]


def local_relative_path(resource_url):
    path = unquote(urlsplit(resource_url).path).lstrip("/")
    if path.startswith("i18n/"):
        return Path(path)
    host = (urlsplit(resource_url).hostname or "unknown").replace(":", "_")
    return Path("external") / host / path


def fetch_once(url, timeout):
    request_url = request_url_for(url)
    request = Request(request_url, headers={"User-Agent": USER_AGENT, "Referer": "https://tlidb.com/cn/"})
    with urlopen(request, timeout=timeout, context=ssl_context()) as response:
        return {"body": response.read(), "http_status": response.status,
                "final_url": response.geturl(), "request_url": request_url,
                "content_type": response.headers.get("Content-Type", "")}


def fetch_resources(resources, output, timeout=20, retries=2, rate_limit=0.5,
                    fetcher=fetch_once, sleep=time.sleep):
    report = {"resource_count": len(resources), "downloaded": 0, "cache_hit": 0,
              "failed": 0, "retry_count": 0, "entries": [], "warnings": [], "errors": []}
    for index, item in enumerate(resources):
        if index and rate_limit: sleep(rate_limit)
        source_url = item["resource_url"]; relative = local_relative_path(source_url)
        target = output / "files" / relative
        meta_path = output / "meta" / relative.with_suffix(relative.suffix + ".meta.json")
        if target.is_file() and meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if meta.get("sha256") == hashlib.sha256(target.read_bytes()).hexdigest():
                    report["cache_hit"] += 1; report["entries"].append({"resource_url": source_url,
                        "status": "cache_hit", "local_path": str(relative)})
                    print(f"[{index + 1}/{len(resources)}] Cache {source_url}")
                    continue
            except (OSError, json.JSONDecodeError):
                pass
        error = None
        for attempt in range(retries + 1):
            try:
                response = fetcher(source_url, timeout); body = response["body"]
                if response["http_status"] != 200: raise ValueError(f"HTTP {response['http_status']}")
                json.loads(body.decode("utf-8"))
                target.parent.mkdir(parents=True, exist_ok=True)
                part = target.with_suffix(target.suffix + ".part"); part.write_bytes(body); os.replace(part, target)
                digest = hashlib.sha256(body).hexdigest()
                write_json(meta_path, {"resource_url": source_url,
                    "request_url": response.get("request_url") or request_url_for(source_url),
                    "final_url": response.get("final_url") or source_url,
                    "local_path": str(relative), "http_status": 200,
                    "content_type": response.get("content_type", ""), "sha256": digest,
                    "byte_count": len(body), "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "retry_count": attempt})
                report["downloaded"] += 1; report["retry_count"] += attempt
                report["entries"].append({"resource_url": source_url, "status": "downloaded",
                                           "local_path": str(relative), "sha256": digest})
                print(f"[{index + 1}/{len(resources)}] Downloaded {source_url}")
                error = None; break
            except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
                error = str(exc)
                if attempt < retries: sleep(min(1.0, rate_limit))
        if error:
            report["failed"] += 1; report["retry_count"] += retries
            report["errors"].append({"resource_url": source_url, "error": error})
            print(f"[{index + 1}/{len(resources)}] Failed {source_url}: {error}")
    write_json(output / "fetch-report.json", report)
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Fetch discovered TLIDB native i18n JSON resources")
    parser.add_argument("--discovery", type=Path, default=Path("data/reports/local-wiki/i18n-discovery.json"))
    parser.add_argument("--output", type=Path, default=Path("data/raw/i18n/ss13"))
    parser.add_argument("--timeout", type=float, default=20); parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--rate-limit", type=float, default=0.5); return parser.parse_args(argv)


def resolve(path): return path if path.is_absolute() else ROOT / path


def main(argv=None):
    args = parse_args(argv); discovery = json.loads(resolve(args.discovery).read_text(encoding="utf-8"))
    report = fetch_resources(discovery.get("resources", []), resolve(args.output), args.timeout,
                             args.retries, args.rate_limit)
    print(f"Downloaded: {report['downloaded']} Cache: {report['cache_hit']} Failed: {report['failed']}")
    return 1 if report["failed"] else 0


if __name__ == "__main__": raise SystemExit(main())
