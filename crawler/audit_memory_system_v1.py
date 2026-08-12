"""Audit Hero Memories and Memory Revival HTML structure without changing entities."""

from __future__ import annotations

import argparse
import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


HERO_SECTIONS = ("基础属性", "固有词缀", "随机词缀")
REVIVAL_SECTIONS = ("复苏词缀", "复苏词缀（月相）")
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


class MemorySectionInspector(HTMLParser):
    """Collect table rows only from explicitly named tab panes."""

    def __init__(self, sections: tuple[str, ...]) -> None:
        super().__init__(convert_charrefs=True)
        self.sections = set(sections)
        self.stack: list[dict[str, Any]] = []
        self.rows: dict[str, list[str]] = {section: [] for section in sections}
        self.section_seen: dict[str, int] = {section: 0 for section in sections}
        self.current_row: dict[str, Any] | None = None
        self.item_tabs = 0
        self.material_mentions = 0
        self.internal_id_attributes = 0
        self.image_resources = 0
        self.navigation_nodes = 0
        self.script_nodes = 0

    def _section(self) -> str | None:
        return next(
            (frame["section"] for frame in reversed(self.stack) if frame["section"]),
            None,
        )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        section = self._section()
        if tag == "div" and "tab-pane" in classes:
            pane_id = attributes.get("id")
            if pane_id in self.sections:
                section = pane_id
                self.section_seen[pane_id] += 1
            elif pane_id == "Item":
                self.item_tabs += 1
        if "data-modifier-id" in attributes:
            self.internal_id_attributes += 1
        if tag == "img" and attributes.get("src"):
            self.image_resources += 1
        if tag in {"nav", "footer"}:
            self.navigation_nodes += 1
        if tag in {"script", "style"}:
            self.script_nodes += 1
        frame = {"tag": tag, "section": section}
        if tag not in VOID_TAGS:
            self.stack.append(frame)
        if tag == "tr" and section in self.sections:
            self.current_row = {"section": section, "frame": frame, "text": []}

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] != tag:
                continue
            removed = self.stack[index:]
            del self.stack[index:]
            if self.current_row and any(
                frame is self.current_row["frame"] for frame in removed
            ):
                text = " ".join(" ".join(self.current_row["text"]).split())
                if text and not text.casefold().startswith("tier modifier level weight"):
                    self.rows[self.current_row["section"]].append(text)
                self.current_row = None
            break

    def handle_data(self, data: str) -> None:
        if "材料" in data:
            self.material_mentions += 1
        if self.current_row is not None:
            self.current_row["text"].append(data)


def inspect_file(path: Path, sections: tuple[str, ...]) -> dict[str, Any]:
    if not path.is_file() or not path.stat().st_size:
        raise ValueError(f"missing or empty HTML: {path}")
    parser = MemorySectionInspector(sections)
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    result = {}
    for section in sections:
        rows = parser.rows[section]
        result[section] = {
            "detected": parser.section_seen[section] == 1,
            "dom_locator": f"div.tab-pane#{section} table.DataTable tbody tr",
            "row_count": len(rows),
            "examples": rows[:3],
        }
    return {
        "sections": result,
        "noise_evidence": {
            "item_tabs": parser.item_tabs,
            "material_text_mentions": parser.material_mentions,
            "internal_modifier_id_attributes": parser.internal_id_attributes,
            "image_resources": parser.image_resources,
            "navigation_nodes": parser.navigation_nodes,
            "script_style_nodes": parser.script_nodes,
        },
    }


def build_report(repo: Path) -> dict[str, Any]:
    hero_path = repo / "data/raw/manifests/inventory/raw_html/Hero_Memories.html"
    revival_path = repo / "data/raw/manifests/help/raw_html/Memory_Revival.html"
    hero = inspect_file(hero_path, HERO_SECTIONS)
    revival = inspect_file(revival_path, REVIVAL_SECTIONS)
    return {
        "schema_version": 1,
        "hero_memory": {
            "canonical_route": "/cn/Hero_Memories/",
            "entity_candidate": True,
            "recommended_entity_model": "single_system_entity",
            "base_attributes": hero["sections"]["基础属性"],
            "fixed_affixes": hero["sections"]["固有词缀"],
            "random_affixes": hero["sections"]["随机词缀"],
            "noise_evidence": hero["noise_evidence"],
        },
        "revival": {
            "canonical_route": "/cn/Memory_Revival/",
            "independent_entity": False,
            "recommended_role": "hero_memory_affix_source",
            "normal_affixes": revival["sections"]["复苏词缀"],
            "moon_affixes": revival["sections"]["复苏词缀（月相）"],
            "noise_evidence": revival["noise_evidence"],
        },
        "search_recommendation": {
            "include": [
                "基础属性词缀效果",
                "固有词缀效果",
                "随机词缀效果",
                "普通复苏词缀效果",
                "月相复苏词缀效果",
            ],
            "exclude": [
                "Item 页面和 Item 列表",
                "材料与复苏操作说明",
                "导航和页脚",
                "UI 图片资源名",
                "data-modifier-id 等内部 ID",
                "Tier、Level、Weight tooltip 元数据",
                "脚本和样式内容",
            ],
            "deduplication": "Use the three dedicated Hero Memories tabs; do not also index the aggregate 词缀 tab.",
        },
        "recommendation": "Generate one Hero Memories system entity. Merge Memory Revival normal and moon affixes into it as supplemental affix data; do not create a separate Revival entity.",
        "warnings": [],
        "errors": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/reports/local-wiki/memory-system-audit-v1.json"),
    )
    args = parser.parse_args()
    repo = args.repo.resolve()
    output = args.output if args.output.is_absolute() else repo / args.output
    report = build_report(repo)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
