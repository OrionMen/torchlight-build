"""Audit the local Ethereal Prism page without generating Entity data."""

from __future__ import annotations

import argparse
import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote


SECTIONS = ("基础词缀", "随机词缀", "Item")
VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


class EtherealPrismInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, Any]] = []
        self.rows: dict[str, list[dict[str, Any]]] = {
            section: [] for section in SECTIONS
        }
        self.row: dict[str, Any] | None = None
        self.section_classes: dict[str, set[str]] = {}
        self.item_links: dict[str, dict[str, str]] = {}
        self.anchor: dict[str, Any] | None = None
        self.image_resource_count = 0
        self.data_attribute_count = 0

    def _section(self) -> str | None:
        return next(
            (frame["section"] for frame in reversed(self.stack) if frame["section"]),
            None,
        )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        section = self._section()
        if tag == "div" and "tab-pane" in classes and attributes.get("id"):
            section = attributes["id"]
            self.section_classes.setdefault(section, set()).update(classes)
        frame = {"tag": tag, "section": section}
        if tag not in VOID_ELEMENTS:
            self.stack.append(frame)

        if tag == "tr" and section in {"基础词缀", "随机词缀"}:
            self.row = {
                "frame": frame,
                "section": section,
                "text": [],
                "modifier_ids": [],
            }
        modifier_id = attributes.get("data-modifier-id")
        if self.row is not None and modifier_id:
            self.row["modifier_ids"].append(modifier_id)
        if tag == "a" and section == "Item" and attributes.get("href"):
            self.anchor = {
                "frame": frame,
                "href": attributes["href"],
                "text": [],
            }
        if tag == "img" and attributes.get("src"):
            self.image_resource_count += 1
        self.data_attribute_count += sum(key.startswith("data-") for key in attributes)

    def handle_data(self, data: str) -> None:
        if self.row is not None:
            self.row["text"].append(data)
        if self.anchor is not None:
            self.anchor["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] != tag:
                continue
            removed = self.stack[index:]
            del self.stack[index:]
            if self.anchor and any(
                frame is self.anchor["frame"] for frame in removed
            ):
                href = unquote(self.anchor["href"])
                if href.startswith("Ethereal_Prism:"):
                    self.item_links[href] = {
                        "id": href,
                        "title": " ".join(" ".join(self.anchor["text"]).split()),
                    }
                self.anchor = None
            if self.row and any(frame is self.row["frame"] for frame in removed):
                if self.row["modifier_ids"]:
                    self.rows[self.row["section"]].append({
                        "text": " ".join(" ".join(self.row["text"]).split()),
                        "modifier_ids": list(dict.fromkeys(self.row["modifier_ids"])),
                    })
                self.row = None
            break


def inspect_ethereal_prism_html(html: str) -> dict[str, Any]:
    parser = EtherealPrismInspector()
    parser.feed(html)

    def section(name: str) -> dict[str, Any]:
        rows = parser.rows[name]
        return {
            "detected": name in parser.section_classes,
            "active_by_default": "active" in parser.section_classes.get(name, set()),
            "row_count": len(rows),
            "modifier_id_count": len({
                modifier_id
                for row in rows
                for modifier_id in row["modifier_ids"]
            }),
            "examples": rows[:3],
            "search_text_source": "visible row text only",
        }

    return {
        "base_affix_section": section("基础词缀"),
        "random_affix_section": section("随机词缀"),
        "item_section": {
            "detected": "Item" in parser.section_classes,
            "linked_item_count": len(parser.item_links),
            "linked_items": list(parser.item_links.values()),
            "search_text_recommendation": "exclude from system Entity summary",
        },
        "image_resource_reference_count": parser.image_resource_count,
        "data_attribute_count": parser.data_attribute_count,
    }


def build_audit(repo: Path) -> dict[str, Any]:
    raw_path = repo / "data/raw/manifests/inventory/raw_html/Ethereal_Prism.html"
    html = raw_path.read_text(encoding="utf-8", errors="replace")
    evidence = inspect_ethereal_prism_html(html)
    recovered = json.loads(
        (repo / "sources/recovered_internal_pages_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    recovered_ids = {entry["id"] for entry in recovered.get("entries", [])}
    linked_items = evidence["item_section"]["linked_items"]
    excluded_pages = [{
        "id": item["id"],
        "title": item["title"],
        "route": f"/cn/{item['id']}/",
        "classification": "related_item_page",
        "raw_snapshot_available": item["id"] in recovered_ids,
        "reason": "independent prism item page; not material and not part of the system Entity summary",
    } for item in linked_items]
    excluded_pages.append({
        "id": "Calibrate_Ethereal_Prism",
        "route": "/cn/Calibrate_Ethereal_Prism/",
        "classification": "support_page",
        "raw_snapshot_available": "Calibrate_Ethereal_Prism" in recovered_ids,
        "reason": "calibration help page, not affix content",
    })
    confirmed = bool(
        evidence["base_affix_section"]["row_count"]
        and evidence["random_affix_section"]["row_count"]
        and evidence["item_section"]["linked_item_count"]
    )
    return {
        "schema_version": 1,
        "entity_candidate": {
            "id": "Ethereal_Prism",
            "title": "异度棱镜",
            "canonical_route": "/cn/Ethereal_Prism/",
            "source_url": "https://tlidb.com/cn/Ethereal_Prism",
            "classification": "system_entity_candidate" if confirmed else "unknown",
            "confirmed": confirmed,
            "one_canonical_system_page": True,
            "entity_model": "one system Entity composed of base and random affix tables",
        },
        "base_affix_section": evidence["base_affix_section"],
        "random_affix_section": evidence["random_affix_section"],
        "related_item_section": evidence["item_section"],
        "excluded_pages": excluded_pages,
        "noise": {
            "material_pages_detected": 0,
            "historical_sections_detected": 0,
            "ui_data_present": evidence["data_attribute_count"] > 0,
            "image_resources_present": evidence["image_resource_reference_count"] > 0,
            "excluded_from_search": [
                "Item tab and linked item cards",
                "internal data-modifier-id/data-hyperlink-id attributes",
                "image src/alt resource names",
                "navigation and footer",
                "DataTable controls and UI labels",
            ],
        },
        "search_recommendation": {
            "include": ["异度棱镜名称", "基础词缀", "随机词缀", "效果说明"],
            "exclude": ["内部 ID", "图片资源名", "UI 数据", "导航", "Item 列表"],
            "base_affix_locator": "#基础词缀 tr containing data-modifier-id",
            "random_affix_locator": "#随机词缀 tr containing data-modifier-id",
        },
        "recommendation": "Generate one system-type Entity for /cn/Ethereal_Prism/ from the two affix sections; keep the 24 linked item pages separate and exclude the Item tab from its clean summary.",
        "warnings": [],
        "errors": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/reports/local-wiki/ethereal-prism-audit-v1.json"),
    )
    args = parser.parse_args()
    repo = args.repo.resolve()
    output = args.output if args.output.is_absolute() else repo / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(build_audit(repo), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
