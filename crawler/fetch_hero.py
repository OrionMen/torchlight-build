from __future__ import annotations

import hashlib
import json
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://tlidb.com/cn/Anger"
HERO_ID = "rehan-anger"
SEASON = "ss13"
RAW_PATH = ROOT / "data/raw/heroes/ss13/rehan-anger.html"
META_PATH = ROOT / "data/raw/heroes/ss13/rehan-anger.meta.json"


def main() -> int:
    request = Request(
        SOURCE_URL,
        headers={"User-Agent": "torchlight-build/0.1 (+local research tool)"},
    )
    verify_paths = ssl.get_default_verify_paths()
    context = None
    system_ca = Path("/etc/ssl/cert.pem")
    if not verify_paths.cafile and system_ca.is_file():
        context = ssl.create_default_context(cafile=str(system_ca))
    try:
        with urlopen(request, timeout=20, context=context) as response:
            status = response.status
            content_type = response.headers.get("Content-Type", "")
            encoding = response.headers.get_content_charset() or ""
            body = response.read()
    except HTTPError as exc:
        print(f"Fetch failed: HTTP {exc.code}", file=sys.stderr)
        return 1
    except (URLError, TimeoutError, OSError) as exc:
        print(f"Fetch failed: {exc}", file=sys.stderr)
        return 1

    if status != 200:
        print(f"Fetch failed: HTTP {status}", file=sys.stderr)
        return 1

    digest = hashlib.sha256(body).hexdigest()
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_PATH.write_bytes(body)
    meta = {
        "schema_version": 1,
        "hero_id": HERO_ID,
        "season": SEASON,
        "source_url": SOURCE_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "http_status": status,
        "content_type": content_type,
        "encoding": encoding,
        "byte_count": len(body),
        "sha256": digest,
    }
    META_PATH.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("Fetched hero page")
    print(f"- status: {status}")
    print(f"- bytes: {len(body)}")
    print(f"- output: {RAW_PATH.relative_to(ROOT)}")
    print(f"- sha256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
