from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "torchlight-build/0.1 (+manifest discovery)"
TYPE_CONFIG = {
    "hero": {"label": "英雄", "expected_count": 27},
    "help": {"label": "帮助手册", "expected_count": 213},
}
STATIC_SUFFIXES = {
    ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".ico", ".woff", ".woff2", ".ttf", ".map", ".pdf", ".zip",
}
VOID_TAGS = {
    "area", "base", "br", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr",
}


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


class Element:
    def __init__(self, tag: str, attrs=None, parent=None):
        self.tag = tag
        self.attrs = dict(attrs or [])
        self.parent = parent
        self.children: list[Element | str] = []

    def text(self) -> str:
        return clean_text(
            " ".join(child if isinstance(child, str) else child.text() for child in self.children)
        )

    def descendants(self) -> Iterable[Element]:
        for child in self.children:
            if isinstance(child, Element):
                yield child
                yield from child.descendants()


class DOMParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Element("root")
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        node = Element(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in VOID_TAGS:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.current.children.append(Element(tag, attrs, self.current))

    def handle_endtag(self, tag):
        node = self.current
        while node is not self.root:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


def ssl_context():
    verify_paths = ssl.get_default_verify_paths()
    system_ca = Path("/etc/ssl/cert.pem")
    if not verify_paths.cafile and system_ca.is_file():
        return ssl.create_default_context(cafile=str(system_ca))
    return None


def download_index(url: str, timeout: float) -> tuple[bytes, int, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout, context=ssl_context()) as response:
        return response.read(), response.status, response.headers.get_content_charset() or "utf-8"


def classify_href(href: Optional[str], index_url: str) -> tuple[Optional[str], Optional[str], str]:
    if href is None or not href.strip():
        return None, None, "empty"
    raw = href.strip()
    lowered = raw.lower()
    if raw.startswith("#"):
        return None, None, "anchor"
    if lowered.startswith("javascript:"):
        return None, None, "javascript"
    if lowered.startswith("mailto:"):
        return None, None, "mailto"

    absolute = urljoin(index_url, raw)
    parsed = urlsplit(absolute)
    if parsed.scheme.lower() != "https" or (parsed.hostname or "").lower() != "tlidb.com":
        return None, None, "external_domain"
    suffix = Path(parsed.path).suffix.lower()
    if suffix in STATIC_SUFFIXES:
        return None, None, "static_resource"
    match = re.fullmatch(r"/cn/([^/]+)", parsed.path)
    if not match:
        return None, None, "invalid_path"

    slug = unquote(match.group(1))
    canonical = urlunsplit(("https", "tlidb.com", f"/cn/{match.group(1)}", "", ""))
    canonical_index = urlunsplit((*urlsplit(index_url)[:3], "", ""))
    if canonical == canonical_index:
        return None, None, "self"
    return canonical, slug, "accepted"


def links_in(node: Element) -> list[Element]:
    candidates = []
    if node.tag == "a" and "href" in node.attrs:
        candidates.append(node)
    candidates.extend(
        item for item in node.descendants() if item.tag == "a" and "href" in item.attrs
    )
    return candidates


def eligible_link_count(node: Element, index_url: str) -> int:
    urls = [
        canonical
        for link in links_in(node)
        for canonical, _slug, reason in [classify_href(link.attrs.get("href"), index_url)]
        if reason == "accepted" and canonical and link.text()
    ]
    return len(urls)


def locate_list_container(
    root: Element,
    index_url: str,
    label: str,
    expected_count: int,
) -> Optional[Element]:
    marker_pattern = re.compile(rf"{re.escape(label)}\s*/\s*{expected_count}(?:\D|$)")
    markers = [item for item in root.descendants() if marker_pattern.search(item.text())]
    matches: list[Element] = []
    for marker in markers:
        node: Optional[Element] = marker
        while node is not None and node is not root:
            if eligible_link_count(node, index_url) == expected_count:
                matches.append(node)
                break
            node = node.parent
    if not matches:
        return None
    return min(matches, key=lambda item: len(list(item.descendants())))


def validate_entries(entries: list[dict]) -> list[str]:
    errors = []
    urls = [entry.get("url") for entry in entries]
    ids = [entry.get("id") for entry in entries]
    duplicate_urls = sorted({value for value in urls if urls.count(value) > 1})
    duplicate_ids = sorted({value for value in ids if ids.count(value) > 1})
    if duplicate_urls:
        errors.append("duplicate entry URLs: " + ", ".join(duplicate_urls))
    if duplicate_ids:
        errors.append("duplicate entry ids: " + ", ".join(duplicate_ids))
    return errors


def discover_from_html(
    html: str,
    index_url: str,
    entity_type: str,
    expected_count: Optional[int] = None,
    label: Optional[str] = None,
) -> tuple[list[dict], dict]:
    config = TYPE_CONFIG.get(entity_type)
    if config is None and (expected_count is None or label is None):
        raise ValueError("unknown entity type requires label and expected_count")
    expected = expected_count if expected_count is not None else int(config["expected_count"])
    marker_label = label if label is not None else str(config["label"])

    parser = DOMParser()
    parser.feed(html)
    all_links = [item for item in parser.root.descendants() if item.tag == "a" and "href" in item.attrs]
    report = {
        "index_url": index_url,
        "http_status": None,
        "extracted_links_total": len(all_links),
        "filtered_count": 0,
        "deduplicated_count": 0,
        "expected_count": expected,
        "duplicate_occurrences": 0,
        "duplicate_urls": [],
        "duplicate_slugs": [],
        "links_without_text": 0,
        "excluded": {},
        "warnings": [],
        "errors": [],
    }

    container = locate_list_container(parser.root, index_url, marker_label, expected)
    if container is None:
        report["errors"].append(
            f"could not locate stable {marker_label} /{expected} list container"
        )
        report["excluded"]["outside_container"] = len(all_links)
        return [], report

    container_links = links_in(container)
    report["excluded"]["outside_container"] = len(all_links) - len(container_links)
    entries: list[dict] = []
    seen_urls: set[str] = set()
    seen_slugs: set[str] = set()
    duplicate_urls: set[str] = set()
    duplicate_slugs: set[str] = set()
    conflicting_slugs: set[str] = set()
    slug_urls: dict[str, str] = {}
    excluded: dict[str, int] = report["excluded"]

    for link in container_links:
        canonical, slug, reason = classify_href(link.attrs.get("href"), index_url)
        if reason != "accepted":
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        name = link.text()
        if not name:
            report["links_without_text"] += 1
            excluded["without_text"] = excluded.get("without_text", 0) + 1
            continue
        report["filtered_count"] += 1
        if canonical in seen_urls:
            duplicate_urls.add(canonical)
            duplicate_slugs.add(slug)
            continue
        if slug in seen_slugs:
            duplicate_slugs.add(slug)
            if slug_urls.get(slug) != canonical:
                conflicting_slugs.add(slug)
            continue
        seen_urls.add(canonical)
        seen_slugs.add(slug)
        slug_urls[slug] = canonical
        entries.append(
            {
                "id": slug,
                "slug": slug,
                "name_zh": name,
                "url": canonical,
                "source_order": len(entries),
            }
        )

    report["duplicate_urls"] = sorted(duplicate_urls)
    report["duplicate_slugs"] = sorted(duplicate_slugs)
    report["duplicate_occurrences"] = report["filtered_count"] - len(entries)
    report["deduplicated_count"] = len(entries)
    report["errors"].extend(validate_entries(entries))
    if conflicting_slugs:
        report["errors"].append(
            "duplicate slugs mapped to different URLs: " + ", ".join(sorted(conflicting_slugs))
        )
    if report["duplicate_occurrences"]:
        report["warnings"].append(
            f"removed {report['duplicate_occurrences']} duplicate link occurrences; "
            f"manifest contains {len(entries)} unique entries"
        )
    if report["filtered_count"] != expected:
        report["errors"].append(
            f"directory link count mismatch: expected {expected}, "
            f"found {report['filtered_count']}"
        )
    return entries, report


def report_path(entity_type: str) -> Path:
    return ROOT / f"data/reports/manifest-discovery/{entity_type}-manifest-report.json"


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Discover a tlidb directory manifest")
    parser.add_argument("--url", required=True)
    parser.add_argument("--type", required=True, choices=sorted(TYPE_CONFIG))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    report = {
        "index_url": args.url,
        "http_status": None,
        "extracted_links_total": 0,
        "filtered_count": 0,
        "deduplicated_count": 0,
        "expected_count": TYPE_CONFIG.get(args.type, {}).get("expected_count"),
        "duplicate_occurrences": 0,
        "duplicate_urls": [],
        "duplicate_slugs": [],
        "links_without_text": 0,
        "excluded": {},
        "warnings": [],
        "errors": [],
    }
    try:
        body, status, encoding = download_index(args.url, args.timeout)
        fetched_at = datetime.now(timezone.utc).isoformat()
        digest = hashlib.sha256(body).hexdigest()
        if status != 200:
            raise ValueError(f"HTTP {status}")
        try:
            html = body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            html = body.decode("utf-8")
        entries, discovered_report = discover_from_html(html, args.url, args.type)
        report.update(discovered_report)
        report["http_status"] = status
        report["html_sha256"] = digest
        report["fetched_at"] = fetched_at
        if not report["errors"]:
            manifest = {
                "schema_version": 1,
                "source": {
                    "site": "tlidb",
                    "locale": "cn",
                    "index_url": args.url,
                    "fetched_at": fetched_at,
                    "http_status": status,
                    "html_sha256": digest,
                },
                "entity_type": args.type,
                "count": len(entries),
                "entries": entries,
            }
            output = args.output if args.output.is_absolute() else ROOT / args.output
            write_json(output, manifest)
    except HTTPError as exc:
        report["http_status"] = exc.code
        report["errors"].append(f"HTTP {exc.code}")
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        report["errors"].append(str(exc))

    write_json(report_path(args.type), report)
    print("Manifest discovery")
    print(f"- type: {args.type}")
    print(f"- status: {report.get('http_status')}")
    print(f"- links: {report.get('deduplicated_count', 0)}")
    print(f"- duplicate URLs: {len(report.get('duplicate_urls', []))}")
    print(f"- duplicate slugs: {len(report.get('duplicate_slugs', []))}")
    if report["errors"]:
        print("- errors: " + "; ".join(report["errors"]), file=sys.stderr)
        return 1
    print("- errors: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
