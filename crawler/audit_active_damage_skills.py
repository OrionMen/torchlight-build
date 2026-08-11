from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
ATTRIBUTES = ("力量", "敏捷", "智慧")


class Node:
    def __init__(self, tag="root", attrs=None):
        self.tag = tag
        self.attrs = dict(attrs or [])
        self.children = []

    @property
    def classes(self):
        return set(self.attrs.get("class", "").split())


class DOMParser(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, attrs))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def walk(node):
    for child in node.children:
        if isinstance(child, Node):
            yield child
            yield from walk(child)


def text_content(node):
    parts = []
    for child in node.children:
        parts.append(text_content(child) if isinstance(child, Node) else child)
    return "".join(parts)


def normalized_text(node):
    return " ".join(text_content(node).split())


def descendants(node, tag=None):
    return [item for item in walk(node) if tag is None or item.tag == tag]


def current_skill_card(root):
    for node in walk(root):
        classes = node.classes
        if node.tag == "div" and {"card", "ui_item", "popupItem"} <= classes and "previousItem" not in classes:
            return node
    return None


def detect_primary_attributes(root):
    card = current_skill_card(root)
    if card is None:
        return [], None
    name = None
    for heading in descendants(card, "h5"):
        if "card-title" in heading.classes:
            name = normalized_text(heading)
            break
    for row in descendants(card, "div"):
        if "d-flex" not in row.classes:
            continue
        row_text = normalized_text(row)
        if "主属性" not in row_text:
            continue
        return [attribute for attribute in ATTRIBUTES if attribute in row_text], name
    return [], name


def table_levels(table):
    rows = descendants(table, "tr")
    if not rows:
        return []
    headers = descendants(rows[0], "th")
    if not headers or normalized_text(headers[0]).strip().lower() not in {"level", "lv", "等级"}:
        return []
    levels = []
    for row in rows[1:]:
        cells = [child for child in row.children if isinstance(child, Node) and child.tag == "td"]
        if not cells:
            continue
        value = normalized_text(cells[0]).strip()
        if re.fullmatch(r"\d+", value):
            levels.append(int(value))
    return levels


def detect_level_table(root):
    candidates = []
    for card in walk(root):
        if card.tag != "div" or "card" not in card.classes:
            continue
        headers = [node for node in descendants(card) if "card-header" in node.classes]
        if not any(re.search(r"成长\s*/\s*\d+", normalized_text(header)) for header in headers):
            continue
        for table in descendants(card, "table"):
            levels = table_levels(table)
            if len(levels) >= 2:
                candidates.append(levels)
    if not candidates:
        return []
    return max(candidates, key=lambda levels: (len(levels), -min(levels), max(levels)))


def inspect_html(html_text):
    parser = DOMParser()
    parser.feed(html_text)
    attributes, page_name = detect_primary_attributes(parser.root)
    levels = detect_level_table(parser.root)
    return {
        "primary_attribute_tags": attributes,
        "page_name": page_name,
        "has_explicit_level_table": bool(levels),
        "detected_level_min": min(levels) if levels else None,
        "detected_level_max": max(levels) if levels else None,
        "has_level_20": 20 in levels,
        "level_table_row_count": len(levels),
    }


def skill_record(entry, detected):
    return {
        "id": entry.get("id") or entry.get("slug"),
        "name_zh": detected.get("page_name") or entry.get("name_zh"),
        "url": entry.get("url"),
        "primary_attribute_tags": detected["primary_attribute_tags"],
        "has_explicit_level_table": detected["has_explicit_level_table"],
        "detected_level_min": detected["detected_level_min"],
        "detected_level_max": detected["detected_level_max"],
        "has_level_20": detected["has_level_20"],
        "level_table_row_count": detected["level_table_row_count"],
    }


def audit(manifest_path: Path, raw_dir: Path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("entries", [])
    result = {
        "manifest_count": len(entries),
        "primary_attribute_skill_count": 0,
        "eligible_skill_count": 0,
        "strength_count": 0,
        "dexterity_count": 0,
        "intelligence_count": 0,
        "multi_attribute_count": 0,
        "eligible_with_level20_count": 0,
        "eligible_missing_level20_count": 0,
        "eligible_skills": [],
        "rejected_primary_attribute_without_level_table": [],
        "eligible_level20_missing": [],
        "warnings": [],
        "errors": [],
    }
    if len(entries) != 204:
        result["warnings"].append(f"Expected 204 manifest entries, found {len(entries)}.")
    seen = set()
    for entry in entries:
        identity = entry.get("id") or entry.get("slug")
        if not identity or identity in seen:
            result["errors"].append(f"Duplicate or missing manifest id: {identity!r}")
            continue
        seen.add(identity)
        slug = entry.get("slug") or identity
        html_path = raw_dir / f"{quote(slug, safe='-_.')}.html"
        if not html_path.is_file():
            result["errors"].append(f"Missing HTML for {identity}: {html_path.name}")
            continue
        try:
            detected = inspect_html(html_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            result["errors"].append(f"Unable to read {identity}: {exc}")
            continue
        if not detected["primary_attribute_tags"]:
            continue
        result["primary_attribute_skill_count"] += 1
        record = skill_record(entry, detected)
        if not detected["has_explicit_level_table"]:
            result["rejected_primary_attribute_without_level_table"].append(record)
            continue
        result["eligible_skills"].append(record)
        if detected["has_level_20"]:
            result["eligible_with_level20_count"] += 1
        else:
            result["eligible_level20_missing"].append(record)
            result["warnings"].append(f"Eligible skill {identity} has no Lv20 row.")

    result["eligible_skill_count"] = len(result["eligible_skills"])
    result["eligible_missing_level20_count"] = len(result["eligible_level20_missing"])
    for record in result["eligible_skills"]:
        tags = record["primary_attribute_tags"]
        result["strength_count"] += int("力量" in tags)
        result["dexterity_count"] += int("敏捷" in tags)
        result["intelligence_count"] += int("智慧" in tags)
        result["multi_attribute_count"] += int(len(tags) > 1)
    return result


def markdown_report(result):
    lines = [
        "# Active Skill Phase 1 Damage Skill Audit", "", "## Summary", "",
        f"- Manifest skills: {result['manifest_count']}",
        f"- Primary attribute skills: {result['primary_attribute_skill_count']}",
        f"- Eligible skills: {result['eligible_skill_count']}",
        f"- Strength: {result['strength_count']}",
        f"- Dexterity: {result['dexterity_count']}",
        f"- Intelligence: {result['intelligence_count']}",
        f"- Multi attribute: {result['multi_attribute_count']}",
        f"- Eligible with Lv20: {result['eligible_with_level20_count']}",
        f"- Eligible missing Lv20: {result['eligible_missing_level20_count']}", "",
        "## Eligible skills", "",
        "| ID | Name | Attributes | Level range | Rows | Lv20 |",
        "|---|---|---|---:|---:|---|",
    ]
    for item in result["eligible_skills"]:
        level_range = f"{item['detected_level_min']}-{item['detected_level_max']}"
        lines.append(
            f"| {item['id']} | {item['name_zh']} | {', '.join(item['primary_attribute_tags'])} | "
            f"{level_range} | {item['level_table_row_count']} | {'yes' if item['has_level_20'] else 'no'} |"
        )
    lines.extend(["", "## Rejected: primary attribute without explicit level table", ""])
    for item in result["rejected_primary_attribute_without_level_table"]:
        lines.append(f"- {item['id']} — {item['name_zh']}")
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {warning}" for warning in result["warnings"])
    lines.extend(["", "## Errors", ""])
    lines.extend(f"- {error}" for error in result["errors"])
    return "\n".join(lines).rstrip() + "\n"


def write_reports(result, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "phase1-damage-skill-audit.json"
    md_path = output_dir / "phase1-damage-skill-audit.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(result), encoding="utf-8")
    return json_path, md_path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Audit local Active Skill primary tags and level tables")
    parser.add_argument("--manifest", type=Path, default=ROOT / "sources/active_skill_manifest.json")
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw/manifests/active_skill/raw_html")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/reports/active-skill-research")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    result = audit(args.manifest, args.raw_dir)
    json_path, md_path = write_reports(result, args.output_dir)
    print(f"Manifest skills: {result['manifest_count']}")
    print(f"Primary attribute skills: {result['primary_attribute_skill_count']}")
    print(f"Eligible skills: {result['eligible_skill_count']}")
    print(f"Eligible with Lv20: {result['eligible_with_level20_count']}")
    print(f"Eligible missing Lv20: {result['eligible_missing_level20_count']}")
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
