from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from crawler.fetch_all_manifests import RateLimiter, format_duration, human_bytes, progress_metrics
from crawler.fetch_manifest import ROOT, ssl_context


ASSET_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0 Safari/537.36"
TLIDB_REFERER = "https://tlidb.com/cn/"
TLIDB_HOSTS = {"tlidb.com", "www.tlidb.com", "cdn.tlidb.com"}


def request_headers(url):
    headers = {"User-Agent": ASSET_USER_AGENT}
    if (urlparse(url).hostname or "").lower() in TLIDB_HOSTS:
        headers["Referer"] = TLIDB_REFERER
    return headers


def fetch_once(url, timeout):
    request = Request(url, headers=request_headers(url))
    try:
        with urlopen(request, timeout=timeout, context=ssl_context()) as response:
            return {"body": response.read(), "http_status": response.status,
                    "content_type": response.headers.get("Content-Type", ""),
                    "etag": response.headers.get("ETag"), "last_modified": response.headers.get("Last-Modified"),
                    "retry_after": response.headers.get("Retry-After")}
    except HTTPError as exc:
        return {"body": b"", "http_status": exc.code, "content_type": exc.headers.get("Content-Type", ""),
                "etag": exc.headers.get("ETag"), "last_modified": exc.headers.get("Last-Modified"),
                "retry_after": exc.headers.get("Retry-After")}


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True); part = path.with_suffix(path.suffix + ".part")
    part.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(part, path)


def cache_result(asset, final_path, meta_path):
    if not final_path.is_file() or not meta_path.is_file(): return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8")); body = final_path.read_bytes()
    except (OSError, json.JSONDecodeError): return None
    digest = hashlib.sha256(body).hexdigest()
    if meta.get("asset_id") != asset["asset_id"] or meta.get("source_url") != asset["source_url"] or meta.get("sha256") != digest:
        return None
    meta["cache_hit"] = True; meta["content_length"] = len(body); atomic_json(meta_path, meta)
    return {"asset_id": asset["asset_id"], "source_url": asset["source_url"], "asset_type": asset["asset_type"],
            "status": "cache_hit", "bytes": len(body), "retry_count": 0, "warnings": []}


def type_warning(asset, content_type):
    expected = asset.get("asset_type"); actual = content_type.split(";", 1)[0].lower()
    matches = {"image": "image/", "stylesheet": "text/css", "javascript": ("javascript", "ecmascript"),
               "font": ("font/", "application/font", "application/vnd.ms-fontobject"), "media": ("audio/", "video/")}
    marker = matches.get(expected)
    if not marker or not actual: return None
    ok = any(part in actual for part in marker) if isinstance(marker, tuple) else (actual.startswith(marker) if marker.endswith("/") else marker in actual)
    return None if ok else f"Expected {expected} but server returned {content_type or 'unknown content type'}."


def retry_after_seconds(value):
    if not value: return None
    if value.replace(".", "", 1).isdigit(): return max(0.0, float(value))
    try: return max(0.0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError): return None


def fetch_asset(asset, output_root, force, timeout, retry, limiter, fetcher=fetch_once,
                sleep: Callable[[float], None] = time.sleep, backoff=0.5):
    relative = Path(asset["local_relative_path"]); final_path = output_root / relative
    meta_path = output_root / "meta" / asset["asset_id"][:2] / asset["asset_id"][2:4] / f"{asset['asset_id']}.meta.json"
    part_path = final_path.with_suffix(final_path.suffix + ".part")
    if part_path.exists(): part_path.unlink()
    if not force:
        cached = cache_result(asset, final_path, meta_path)
        if cached: return cached
    error = ""; warnings = []
    for attempt in range(retry + 1):
        try:
            limiter.wait(); response = fetcher(asset["source_url"], timeout); status = response["http_status"]
            if status == 200:
                body = response["body"]
                if not isinstance(body, bytes): raise ValueError("asset response body must be bytes")
                final_path.parent.mkdir(parents=True, exist_ok=True); part_path.write_bytes(body)
                digest = hashlib.sha256(body).hexdigest(); os.replace(part_path, final_path)
                warning = type_warning(asset, response.get("content_type", ""))
                if warning: warnings.append(warning)
                meta = {"asset_id": asset["asset_id"], "source_url": asset["source_url"],
                        "asset_type": asset["asset_type"], "http_status": status,
                        "content_type": response.get("content_type", ""), "content_length": len(body),
                        "download_time": datetime.now(timezone.utc).isoformat(), "etag": response.get("etag"),
                        "last_modified": response.get("last_modified"), "sha256": digest,
                        "retry_count": attempt, "cache_hit": False,
                        "local_relative_path": asset["local_relative_path"], "warnings": warnings}
                atomic_json(meta_path, meta)
                return {"asset_id": asset["asset_id"], "source_url": asset["source_url"],
                        "asset_type": asset["asset_type"], "status": "downloaded", "bytes": len(body),
                        "retry_count": attempt, "warnings": warnings}
            error = f"HTTP {status}"
            should_retry = status == 429 or 500 <= status < 600
            if not should_retry or attempt >= retry: break
            delay = retry_after_seconds(response.get("retry_after"))
            if delay is None: delay = backoff * (2 ** attempt)
            sleep(delay)
        except (URLError, TimeoutError, OSError, ConnectionError, ValueError, KeyError) as exc:
            error = str(exc)
            if attempt >= retry: break
            sleep(backoff * (2 ** attempt))
    if part_path.exists(): part_path.unlink()
    return {"asset_id": asset["asset_id"], "source_url": asset["source_url"], "asset_type": asset["asset_type"],
            "status": "failed", "bytes": 0, "retry_count": attempt, "warnings": warnings, "error": error}


class AssetProgress:
    def __init__(self, total, season, workers, rate, quiet=False, output: TextIO=sys.stdout,
                 clock: Callable[[], float]=time.monotonic, tty=None):
        self.total=total; self.season=season; self.workers=workers; self.rate=rate; self.quiet=quiet
        self.output=output; self.clock=clock; self.tty=output.isatty() if tty is None else tty
        self.started=clock(); self.done=self.dl=self.cache=self.fail=self.retries=self.bytes=0

    def start(self):
        if self.quiet: return
        print("="*60, "\nTLIDB Asset Fetch", f"\nSeason: {self.season}", f"\nAssets: {self.total}",
              f"\nWorkers: {self.workers}", f"\nRate limit: {self.rate}s", "\n"+"="*60, file=self.output, flush=True)

    def update(self, result):
        self.done+=1; self.dl+=result["status"]=="downloaded"; self.cache+=result["status"]=="cache_hit"
        self.fail+=result["status"]=="failed"; self.retries+=result.get("retry_count",0); self.bytes+=result.get("bytes",0) if result["status"]=="downloaded" else 0
        if self.quiet or (not self.tty and self.done%10 and self.done!=self.total): return
        speed,eta=progress_metrics(self.done,self.total,self.clock()-self.started)
        line=(f"[Assets] {self.done}/{self.total} | DL {self.dl} | Cache {self.cache} | Fail {self.fail} | "
              f"Retry {self.retries} | {'-' if speed is None else f'{speed:.2f}/s'} | ETA {'--' if eta is None else format_duration(eta)} | {human_bytes(self.bytes)}")
        print(line,end="\r" if self.tty else "\n",file=self.output,flush=True)

    def finish(self, report, report_path):
        if self.tty and not self.quiet: print(file=self.output)
        completed=report["downloaded"]+report["cache_hit"]+report["failed"]
        speed,_=progress_metrics(completed,report["manifest_asset_count"],report["elapsed"])
        print("="*60,"\nAsset Fetch Finished",f"\nAssets: {report['manifest_asset_count']}",
              f"\nDownloaded: {report['downloaded']}",f"\nCache: {report['cache_hit']}",
              f"\nFailed: {report['failed']}",f"\nRetry: {report['retry_count']}",
              f"\nBytes: {human_bytes(report['bytes'])}",f"\nElapsed: {format_duration(report['elapsed'])}",
              f"\nAverage: {'-' if speed is None else f'{speed:.2f} assets/s'}",f"\nReport: {report_path}",
              "\n"+"="*60,file=self.output,flush=True)

    def interrupted(self):
        print("Interrupted by user.\nCompleted assets remain cached.\nRun the same command again to resume.",file=self.output,flush=True)


def fetch_manifest(manifest_path, output_root, force=False, max_workers=4, rate_limit=0.2,
                   timeout=20, retry=3, quiet=False, fetcher=fetch_once, sleep=time.sleep, progress=None):
    started=time.monotonic(); manifest=json.loads(manifest_path.read_text(encoding="utf-8")); assets=manifest.get("assets",[])
    limiter=RateLimiter(rate_limit,sleep=sleep); progress=progress or AssetProgress(len(assets),manifest.get("season","unknown"),max_workers,rate_limit,quiet)
    progress.start(); results={}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures={executor.submit(fetch_asset,a,output_root,force,timeout,retry,limiter,fetcher,sleep):i for i,a in enumerate(assets)}
        for future in as_completed(futures):
            i=futures[future]
            try: results[i]=future.result()
            except Exception as exc:
                a=assets[i]; results[i]={"asset_id":a["asset_id"],"source_url":a["source_url"],"asset_type":a["asset_type"],"status":"failed","bytes":0,"retry_count":0,"warnings":[],"error":str(exc)}
            progress.update(results[i])
    ordered=[results[i] for i in sorted(results)]; failed=[{k:r.get(k) for k in ("asset_id","source_url","asset_type","error")} for r in ordered if r["status"]=="failed"]
    warnings=[{"asset_id":r["asset_id"],"warning":w} for r in ordered for w in r.get("warnings",[])]
    report={"season":manifest.get("season"),"manifest_asset_count":len(assets),
            "downloaded":sum(r["status"]=="downloaded" for r in ordered),"cache_hit":sum(r["status"]=="cache_hit" for r in ordered),
            "failed":len(failed),"retry_count":sum(r.get("retry_count",0) for r in ordered),
            "bytes":sum(r.get("bytes",0) for r in ordered if r["status"]=="downloaded"),
            "elapsed":round(time.monotonic()-started,3),"asset_type_counts":dict(Counter(a.get("asset_type","other") for a in assets)),
            "failed_assets":failed,"warnings":warnings,"errors":[]}
    report_path=manifest_path.parent/"reports/asset-fetch-report.json"; atomic_json(report_path,report); progress.finish(report,report_path)
    return report


def parse_args(argv=None):
    p=argparse.ArgumentParser(description="Fetch assets from a TLIDB asset manifest")
    p.add_argument("--manifest",type=Path,default=Path("data/raw/assets/ss13/asset-manifest.json")); p.add_argument("--output-root",type=Path,default=Path("data/raw/assets/ss13/files"))
    p.add_argument("--force",action="store_true"); p.add_argument("--max-workers",type=int,default=4); p.add_argument("--rate-limit",type=float,default=.2)
    p.add_argument("--timeout",type=float,default=20); p.add_argument("--retry",type=int,default=3); p.add_argument("--quiet",action="store_true"); return p.parse_args(argv)


def main(argv=None):
    args=parse_args(argv); manifest=args.manifest if args.manifest.is_absolute() else ROOT/args.manifest; output=args.output_root if args.output_root.is_absolute() else ROOT/args.output_root
    try:
        if args.max_workers<1 or args.rate_limit<0 or args.timeout<=0 or args.retry<0: raise ValueError("invalid fetch option")
        report=fetch_manifest(manifest,output,args.force,args.max_workers,args.rate_limit,args.timeout,args.retry,args.quiet)
        return 1 if report["failed"] or report["errors"] else 0
    except KeyboardInterrupt:
        AssetProgress(0,"unknown",args.max_workers,args.rate_limit,args.quiet,output=sys.stdout).interrupted(); return 130
    except Exception as exc:
        print(f"Asset fetch failed: {exc}",file=sys.stderr); return 1


if __name__=="__main__": raise SystemExit(main())
