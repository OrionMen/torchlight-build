"""Audit TLIDB talent pages as player-facing Entity candidates."""

from __future__ import annotations

import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote


SPECIAL_IDS = {"New_God", "Nether_King"}
VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


class TalentPageInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, Any]] = []
        self.title: list[str] = []
        self.heading: dict[str, Any] | None = None
        self.capture: dict[str, Any] | None = None
        self.row: dict[str, Any] | None = None
        self.talents: list[dict[str, Any]] = []
        self.tab_sections: dict[str, set[str]] = {}
        self.image_resource_names = 0

    def _tab(self) -> dict[str, Any] | None:
        return next(
            (frame["tab"] for frame in reversed(self.stack) if frame.get("tab")),
            None,
        )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        tab = self._tab()
        if tag == "div" and "tab-pane" in classes:
            tab = {
                "id": attributes.get("id") or "unnamed",
                "active": bool({"active", "show"} & classes),
            }
            self.tab_sections.setdefault(tab["id"], set()).update(classes)
        frame = {"tag": tag, "tab": tab}
        if tag not in VOID_ELEMENTS:
            self.stack.append(frame)
        if tag == "div" and "col" in classes and self.row is None:
            self.row = {
                "frame": frame,
                "talent_id": None,
                "text": [],
                "tab_id": tab.get("id") if tab else None,
                "active_tab": tab.get("active") if tab else True,
            }
        if tag == "title":
            self.heading = {"kind": "title", "text": [], "frame": frame}
        elif tag in {"h1", "h5"}:
            self.heading = {"kind": tag, "text": [], "frame": frame}
        talent_id = attributes.get("data-talent-id")
        if talent_id:
            if self.row is not None:
                self.row["talent_id"] = talent_id
            else:
                self.capture = {
                    "frame": frame,
                    "talent_id": talent_id,
                    "text": [],
                    "tab_id": tab.get("id") if tab else None,
                    "active_tab": tab.get("active") if tab else True,
                }
        if tag == "img" and attributes.get("src"):
            self.image_resource_names += 1

    def handle_data(self, data: str) -> None:
        if self.heading is not None:
            self.heading["text"].append(data)
        if self.capture is not None:
            self.capture["text"].append(data)
        if self.row is not None:
            self.row["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] != tag:
                continue
            removed = self.stack[index:]
            del self.stack[index:]
            if self.heading and any(
                frame is self.heading["frame"] for frame in removed
            ):
                text = " ".join(" ".join(self.heading["text"]).split())
                if text:
                    if self.heading["kind"] == "title":
                        self.title.append(text)
                    else:
                        self.title.append(text)
                self.heading = None
            if self.capture and any(
                frame is self.capture["frame"] for frame in removed
            ):
                text = " ".join(" ".join(self.capture["text"]).split())
                self.talents.append({
                    "talent_id": self.capture["talent_id"],
                    "text": text,
                    "tab_id": self.capture["tab_id"],
                    "active_tab": self.capture["active_tab"],
                })
                self.capture = None
            if self.row and any(frame is self.row["frame"] for frame in removed):
                if self.row["talent_id"]:
                    text = " ".join(" ".join(self.row["text"]).split())
                    self.talents.append({
                        "talent_id": self.row["talent_id"],
                        "text": text,
                        "tab_id": self.row["tab_id"],
                        "active_tab": self.row["active_tab"],
                    })
                self.row = None
            break


def inspect_talent_html(html: str, expected_name: str | None = None) -> dict[str, Any]:
    parser = TalentPageInspector()
    parser.feed(html)
    current = [talent for talent in parser.talents if talent["active_tab"]]
    historical = [talent for talent in parser.talents if not talent["active_tab"]]
    cache_sections = sorted(
        section for section in parser.tab_sections if "_cache-" in section
    )
    excluded_sections = sorted(
        section for section in parser.tab_sections
        if section in {"ProfessionTree", "Item"} or "_cache-" in section
    )
    title_detected = bool(
        expected_name
        and any(expected_name in heading for heading in parser.title)
    )
    return {
        "title_detected": title_detected,
        "headings": parser.title,
        "current_talent_count": len(current),
        "current_talent_text_count": sum(bool(item["text"]) for item in current),
        "current_talent_examples": current[:3],
        "historical_talent_count": len(historical),
        "historical_tab_sections": cache_sections,
        "excluded_tab_sections": excluded_sections,
        "has_profession_tree": "ProfessionTree" in parser.tab_sections,
        "has_item_section": "Item" in parser.tab_sections,
        "image_resource_reference_count": parser.image_resource_names,
    }


def _directory_evidence(repo: Path) -> dict[str, Any]:
    path = repo / "local_wiki/ss13/site/cn/Talent/index.html"
    if not path.is_file():
        return {
            "id": "Talent",
            "route": "/cn/Talent/",
            "classification": "category_page",
            "raw_status": "missing",
            "entity_recommendation": "exclude",
        }
    html = path.read_text(encoding="utf-8", errors="replace")
    links = len(set(re.findall(r'href=["\'](?:[^"\']*/)?(?:God|Goddess|New_God|Nether_King|The_Brave|Onslaughter|Warlord)[^"\']*["\']', html)))
    return {
        "id": "Talent",
        "route": "/cn/Talent/",
        "classification": "category_page",
        "raw_status": "available",
        "detected_entity_link_count": links,
        "entity_recommendation": "exclude",
    }


def build_audit(repo: Path) -> dict[str, Any]:
    manifest = json.loads(
        (repo / "sources/talent_manifest.json").read_text(encoding="utf-8")
    )
    raw_root = repo / "data/raw/manifests/talent/raw_html"
    groups: dict[str, list[dict[str, Any]]] = {
        "hero_talent": [],
        "new_god": [],
        "nether_king": [],
    }
    warnings = []
    for entry in manifest.get("entries", []):
        path = raw_root / f"{quote(entry['slug'], safe='-_.')}.html"
        if not path.is_file():
            warnings.append({"id": entry["id"], "warning": "raw_html_missing"})
            evidence = inspect_talent_html("", entry.get("name_zh"))
            raw_status = "missing"
        else:
            html = path.read_text(encoding="utf-8", errors="replace")
            evidence = inspect_talent_html(html, entry.get("name_zh"))
            raw_status = "available" if html else "empty"
        confirmed = bool(
            raw_status == "available"
            and evidence["title_detected"]
            and evidence["current_talent_count"]
            and evidence["current_talent_count"]
            == evidence["current_talent_text_count"]
        )
        item = {
            "id": entry["id"],
            "title": entry.get("name_zh") or entry["id"],
            "url": entry["url"],
            "canonical_route": f"/cn/{entry['slug']}/",
            "classification": "talent_entity" if confirmed else "unknown",
            "entity_confirmed": confirmed,
            "raw_status": raw_status,
            **evidence,
        }
        group = (
            "new_god" if entry["id"] == "New_God"
            else "nether_king" if entry["id"] == "Nether_King"
            else "hero_talent"
        )
        groups[group].append(item)

    excluded = [_directory_evidence(repo)]
    entity_count = sum(
        item["entity_confirmed"]
        for items in groups.values()
        for item in items
    )
    recommendation = {
        "include": ["名称", "主要属性", "标签", "描述", "天赋效果", "核心机制"],
        "exclude": ["导航", "内部 ID", "图片资源名", "UI 数据", "历史版本"],
        "current_effect_locator": "elements carrying data-talent-id in the current/default page content",
        "historical_locator": "inactive *_cache-* tab-pane sections",
        "category_page_visibility": "hidden",
        "entity_page_visibility": "visible",
    }
    return {
        "schema_version": 1,
        "hero_talent": {
            "entities": groups["hero_talent"],
            "excluded_pages": excluded,
            "search_recommendation": recommendation,
        },
        "new_god": {
            "entities": groups["new_god"],
            "excluded_pages": [],
            "search_recommendation": recommendation,
        },
        "nether_king": {
            "entities": groups["nether_king"],
            "excluded_pages": [],
            "search_recommendation": recommendation,
        },
        "summary": {
            "manifest_count": len(manifest.get("entries", [])),
            "hero_talent_entity_count": sum(
                item["entity_confirmed"] for item in groups["hero_talent"]
            ),
            "new_god_entity_count": sum(
                item["entity_confirmed"] for item in groups["new_god"]
            ),
            "nether_king_entity_count": sum(
                item["entity_confirmed"] for item in groups["nether_king"]
            ),
            "entity_count": entity_count,
            "excluded_count": len(excluded),
            "raw_available": sum(
                item["raw_status"] == "available"
                for items in groups.values()
                for item in items
            ),
            "historical_effects_excluded": sum(
                item["historical_talent_count"]
                for items in groups.values()
                for item in items
            ),
        },
        "warnings": warnings,
        "errors": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/reports/local-wiki/talent-system-entity-audit-v1.json"),
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
