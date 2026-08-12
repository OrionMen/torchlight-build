"""Audit legendary gear page regions for future search extraction."""

from __future__ import annotations

import argparse
import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote


VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


class LegendaryPageInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, Any]] = []
        self.h1: list[str] = []
        self.current_heading: list[str] | None = None
        self.current_effects: list[str] = []
        self.corrosion_effects: list[str] = []
        self.lore: list[str] = []
        self.capture: dict[str, Any] | None = None
        self.current_cards = 0
        self.previous_cards = 0
        self.corrosion_sections = 0
        self.drop_sections = 0
        self.talent_slate_markers = 0

    def current_card(self) -> dict[str, Any] | None:
        return next((frame["card"] for frame in reversed(self.stack) if frame.get("card")), None)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        parent_card = self.current_card()
        card = parent_card
        if tag == "div" and "card" in classes:
            if "popupItem" in classes and "previousItem" not in classes:
                kind = "current"
                self.current_cards += 1
            elif "previousItem" in classes:
                kind = "previous"
                self.previous_cards += 1
            else:
                kind = "other"
            card = {"kind": kind}
        i18n = attributes.get("data-i18n") or ""
        if tag == "img" and "TalentSlate" in (attributes.get("src") or ""):
            self.talent_slate_markers += 1
        if card and "hyperlink|name|30001" in i18n:
            if card["kind"] != "corrosion":
                self.corrosion_sections += 1
            card["kind"] = "corrosion"
        if card and "Func_Tips_DropSource" in i18n:
            if card["kind"] != "drop_source":
                self.drop_sections += 1
            card["kind"] = "drop_source"
        frame = {"tag": tag, "card": card, "starts_capture": False}
        if tag not in VOID_ELEMENTS:
            self.stack.append(frame)
        if tag == "h1":
            self.current_heading = []
        if attributes.get("data-modifier-id") and card and card["kind"] in {"current", "corrosion"}:
            self.capture = {"kind": card["kind"], "text": [], "frame": frame}
            frame["starts_capture"] = True
        elif "fst-italic" in classes and card and card["kind"] in {"current", "previous"}:
            self.capture = {"kind": "lore", "text": [], "frame": frame}
            frame["starts_capture"] = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1" and self.current_heading is not None:
            value = " ".join(" ".join(self.current_heading).split())
            if value:
                self.h1.append(value)
            self.current_heading = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] != tag:
                continue
            removed = self.stack[index:]
            del self.stack[index:]
            if self.capture and any(frame is self.capture["frame"] for frame in removed):
                value = " ".join(" ".join(self.capture["text"]).split())
                if value:
                    if self.capture["kind"] == "current":
                        self.current_effects.append(value)
                    elif self.capture["kind"] == "corrosion":
                        self.corrosion_effects.append(value)
                    else:
                        self.lore.append(value)
                self.capture = None
            break

    def handle_data(self, data: str) -> None:
        if self.current_heading is not None:
            self.current_heading.append(data)
        if self.capture is not None:
            self.capture["text"].append(data)


def inspect_legendary_html(html: str) -> dict[str, Any]:
    parser = LegendaryPageInspector()
    parser.feed(html)
    return {
        "headings": parser.h1,
        "current_item_card_count": parser.current_cards,
        "previous_item_card_count": parser.previous_cards,
        "main_effect_count": len(parser.current_effects),
        "main_effect_examples": parser.current_effects[:3],
        "corrosion_section_count": parser.corrosion_sections,
        "corrosion_effect_count": len(parser.corrosion_effects),
        "corrosion_effect_examples": parser.corrosion_effects[:3],
        "lore_section_count": len(parser.lore),
        "lore_examples": parser.lore[:1],
        "drop_source_section_count": parser.drop_sections,
        "talent_slate_marker_count": parser.talent_slate_markers,
    }


def build_audit(repo: Path) -> dict[str, Any]:
    manifest = json.loads(
        (repo / "sources/legendary_gear_manifest.json").read_text(encoding="utf-8")
    )
    raw_root = repo / "data/raw/manifests/legendary_gear/raw_html"
    entities = []
    warnings = []
    for entry in manifest.get("entries", []):
        raw_path = raw_root / f"{quote(entry['slug'], safe='-_.')}.html"
        if not raw_path.is_file():
            warnings.append({"id": entry["id"], "warning": "raw_html_missing"})
            evidence = inspect_legendary_html("")
            raw_status = "missing"
        else:
            html = raw_path.read_text(encoding="utf-8", errors="replace")
            evidence = inspect_legendary_html(html)
            raw_status = "available" if html else "empty"
            if not html:
                warnings.append({"id": entry["id"], "warning": "raw_html_empty"})
        entity_page = bool(
            evidence["current_item_card_count"]
            and entry.get("name_zh") in evidence["headings"]
            and not evidence["talent_slate_marker_count"]
        )
        classification = (
            "legendary_entity" if entity_page
            else "non_equipment_page" if evidence["talent_slate_marker_count"]
            else "unknown"
        )
        entities.append({
            "id": entry["id"],
            "title": entry.get("name_zh") or entry["id"],
            "url": entry["url"],
            "classification": classification,
            "entity_page_confirmed": entity_page,
            "raw_status": raw_status,
            **evidence,
        })
    by_id = {item["id"]: item for item in entities}
    example_ids = [
        "Thunder_Channeling_Prosthetics",
        "Crosser",
        "Frozen_Sight",
        "Glorious_Journey",
        "Omniscient_Prototype",
        "Awaiting",
    ]
    analyzable = [item for item in entities if item["raw_status"] == "available"]
    return {
        "schema_version": 1,
        "total_pages": len(entities),
        "raw_pages_available": len(analyzable),
        "raw_pages_empty": sum(item["raw_status"] == "empty" for item in entities),
        "raw_pages_missing": sum(item["raw_status"] == "missing" for item in entities),
        "confirmed_entity_pages": sum(item["entity_page_confirmed"] for item in entities),
        "non_equipment_pages": sum(item["classification"] == "non_equipment_page" for item in entities),
        "entities": entities,
        "examples": [by_id[item_id] for item_id in example_ids],
        "page_region_model": {
            "legendary_entity": ".card.ui_item.popupItem:not(.previousItem)",
            "lore_section": ".fst-italic inside current item card",
            "corrosion_section": "card header data-i18n=hyperlink|name|30001",
            "other_noise": [
                ".previousItem historical cards",
                "Drop Source card (Func_Tips_DropSource)",
                "nav/footer/script/style",
                "data-modifier-id and other internal attributes",
            ],
        },
        "search_include_sections": [
            "h1 equipment name",
            "current SS13 .popupItem modifier text",
            "fixed modifier text",
            "Corroded/已侵蚀 card modifier text",
        ],
        "search_exclude_sections": [
            "current and historical .fst-italic lore",
            ".previousItem historical season cards",
            "Drop Source card",
            "navigation and footer",
            "internal IDs and attributes",
            "unrelated data tables",
        ],
        "search_recommendation": {
            "include": ["装备名称", "主效果", "固定词条", "已侵蚀效果"],
            "exclude": ["背景故事", "Lore", "掉落来源", "内部 ID", "数据表"],
            "one_page_one_entity": all(item["entity_page_confirmed"] for item in analyzable),
            "analyzed_legendary_pages_are_entities": all(
                item["entity_page_confirmed"]
                for item in analyzable
                if item["classification"] != "non_equipment_page"
            ),
            "scope_note": "Conclusion applies to non-empty local snapshots; empty snapshots remain unaudited.",
        },
        "warnings": warnings,
        "errors": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output", type=Path,
        default=Path("data/reports/local-wiki/legendary-gear-audit-v1.json"),
    )
    args = parser.parse_args()
    repo = args.repo.resolve()
    report = build_audit(repo)
    output = args.output if args.output.is_absolute() else repo / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
