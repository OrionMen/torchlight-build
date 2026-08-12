from __future__ import annotations

import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin


ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://tlidb.com/cn/Anger"
HERO_ID = "rehan-anger"
SEASON = "ss13"
RAW_REL = Path("data/raw/heroes/ss13/rehan-anger.html")
META_REL = Path("data/raw/heroes/ss13/rehan-anger.meta.json")
PARSED_REL = Path("data/parsed/heroes/ss13/rehan-anger.json")
REPORT_REL = Path("data/reports/rehan-anger-ss13-parse-report.json")
RAW_PATH = ROOT / RAW_REL
META_PATH = ROOT / META_REL
PARSED_PATH = ROOT / PARSED_REL
REPORT_PATH = ROOT / REPORT_REL
CORE_NODES = {"义愤填膺", "怒不可遏", "顾此失彼", "尽情挥发", "暴怒原罪"}
VOID_TAGS = {"area", "base", "br", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
BLOCK_TAGS = {"div", "p", "li", "section", "article"}


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


class Element:
    def __init__(self, tag: str, attrs=None, parent=None):
        self.tag = tag
        self.attrs = dict(attrs or [])
        self.parent = parent
        self.children: list[Element | str] = []
        self.order = -1

    def text(self) -> str:
        return clean(" ".join(child if isinstance(child, str) else child.text() for child in self.children))

    def own_text(self) -> str:
        return clean(" ".join(child for child in self.children if isinstance(child, str)))

    def descendants(self) -> Iterable[Element]:
        for child in self.children:
            if isinstance(child, Element):
                yield child
                yield from child.descendants()


class TreeParser(HTMLParser):
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
        node = Element(tag, attrs, self.current)
        self.current.children.append(node)

    def handle_endtag(self, tag):
        node = self.current
        while node is not self.root:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


def has_class(node: Element, name: str) -> bool:
    return name in node.attrs.get("class", "").split()


def image_data(node: Element, base_url: str = SOURCE_URL) -> dict:
    images = [item for item in node.descendants() if item.tag == "img"]
    if not images:
        return {"alt": None, "url": None}
    image = images[0]
    src = image.attrs.get("src")
    return {
        "alt": clean(image.attrs.get("alt", "")) or None,
        "url": urljoin(base_url, src) if src else None,
    }


def split_dom_lines(node: Element) -> list[str]:
    lines: list[str] = []
    parts: list[str] = []

    def flush() -> None:
        text = clean(" ".join(parts))
        if text:
            lines.append(text)
        parts.clear()

    def visit(item: Element | str, root: bool = False) -> None:
        if isinstance(item, str):
            if clean(item):
                parts.append(item)
            return
        if item.tag == "br":
            flush()
            return
        is_block = not root and item.tag in BLOCK_TAGS
        if is_block:
            flush()
        for child in item.children:
            visit(child)
        if is_block:
            flush()

    visit(node, root=True)
    flush()
    return lines


def direct_break_segments(node: Element) -> list[str]:
    segments: list[str] = []
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, Element) and child.tag == "br":
            text = clean(" ".join(parts))
            if text:
                segments.append(text)
            parts.clear()
        elif isinstance(child, Element):
            if child.tag != "img" and child.text():
                parts.append(child.text())
        elif clean(child):
            parts.append(child)
    text = clean(" ".join(parts))
    if text:
        segments.append(text)
    return segments


def parse_node(box: Element, index: int, base_url: str = SOURCE_URL) -> dict:
    content = next(
        (child for child in box.children if isinstance(child, Element) and has_class(child, "flex-grow-1")),
        box,
    )
    title = next(
        (item.text() for item in content.descendants() if has_class(item, "fw-bold") and item.text()),
        "",
    )
    source_text = content.text()
    level_match = re.search(r"需求等级\s*(\d+)", source_text)
    levels: list[dict] = []
    tier_nodes = [item for item in content.descendants() if has_class(item, "tierLevel")]
    if tier_nodes:
        for tier in tier_nodes:
            explicit = re.fullmatch(r"等级\s*(\d+)", tier.text())
            if not explicit or tier.parent is None:
                continue
            siblings = tier.parent.children
            position = siblings.index(tier)
            effect_lines: list[str] = []
            for sibling in siblings[position + 1:]:
                if not isinstance(sibling, Element):
                    continue
                if sibling.tag == "hr" or has_class(sibling, "tierLevel"):
                    break
                effect_lines.extend(split_dom_lines(sibling))
            levels.append({"level": int(explicit.group(1)), "lines": effect_lines})
    else:
        body = [
            child for child in content.children
            if isinstance(child, Element)
            and child is not next(
                (item for item in content.children if isinstance(item, Element) and has_class(item, "fw-bold")),
                None,
            )
            and child.tag != "hr"
        ]
        lines = [line for item in body for line in split_dom_lines(item)]
        lines = [
            line for line in lines
            if line != title
            and not re.fullmatch(r"需求等级\s*\d+", line)
            and line not in {"展开", "收起", "查看"}
        ]
        levels.append({"level": None, "lines": lines})
    if not levels:
        levels = [{"level": None, "lines": []}]
    return {
        "index": index,
        "name": title,
        "required_level": int(level_match.group(1)) if level_match else None,
        "icon": image_data(box, base_url),
        "levels": levels,
        "source_text": source_text,
    }


def _direct_elements(node: Element, tag: Optional[str] = None) -> list[Element]:
    return [
        child
        for child in node.children
        if isinstance(child, Element) and (tag is None or child.tag == tag)
    ]


def parse_hero_html(
    html: str,
    *,
    entity_id: str,
    name_zh: str,
    page_url: str,
    raw_sha256: str,
    season: str = "ss13",
) -> dict:
    """将单个英雄页面忠实转换为网页结构数据，不解释游戏语义。"""

    parser = TreeParser()
    parser.feed(html)
    elements = list(parser.root.descendants())
    for order, element in enumerate(elements):
        element.order = order

    trait_headers = [
        item
        for item in elements
        if item.tag == "h5"
        and has_class(item, "card-header")
        and re.fullmatch(r".+?\s*-\s*英雄特性\s*/\s*\d+", item.text())
    ]
    if not trait_headers:
        raise ValueError("hero trait header was not found")
    trait_header = trait_headers[0]
    trait_name = clean(trait_header.text().split(" - ", 1)[0])
    trait_card = trait_header.parent
    if trait_card is None:
        raise ValueError("hero trait container was not found")

    boxes: list[Element] = []
    for item in trait_card.descendants():
        if not has_class(item, "d-flex") or not has_class(item, "border-top"):
            continue
        content = next(
            (
                child
                for child in _direct_elements(item)
                if has_class(child, "flex-grow-1")
            ),
            None,
        )
        if content and any(has_class(child, "fw-bold") for child in _direct_elements(content)):
            boxes.append(item)
    nodes = [parse_node(box, index, page_url) for index, box in enumerate(boxes)]
    if not nodes:
        raise ValueError("hero nodes were not found")

    hero_cards = []
    first_node_order = boxes[0].order
    for item in elements:
        if item.tag != "div" or not has_class(item, "card-body") or item.order >= first_node_order:
            continue
        direct = _direct_elements(item)
        if any(child.tag == "img" and has_class(child, "size128") for child in direct):
            hero_cards.append(item)
    if not hero_cards:
        raise ValueError("hero summary card was not found")
    hero_card = hero_cards[-1]

    direct_links = [child for child in _direct_elements(hero_card, "a") if child.text()]
    character_link = direct_links[0] if direct_links else None
    character_name = character_link.text() if character_link else ""
    skill_link = next(
        (
            link
            for link in direct_links
            if link is not character_link and any(item.tag == "img" for item in link.descendants())
        ),
        None,
    )
    recommended_skill = {
        "name": skill_link.text() if skill_link else "",
        "url": urljoin(page_url, skill_link.attrs.get("href", "")) if skill_link else None,
    }
    excluded_segments = {character_name, recommended_skill["name"]}
    summary_candidates = [
        segment
        for segment in direct_break_segments(hero_card)
        if segment and segment not in excluded_segments and recommended_skill["name"] not in segment
    ]
    summary = max(summary_candidates, key=len) if summary_candidates else ""
    if not summary:
        raise ValueError("hero summary was not found")

    portrait_node = next(
        (
            child
            for child in _direct_elements(hero_card, "img")
            if has_class(child, "size128") and child.attrs.get("src")
        ),
        None,
    )
    portrait = {
        "alt": clean(portrait_node.attrs.get("alt", "")) or None if portrait_node else None,
        "url": urljoin(page_url, portrait_node.attrs["src"]) if portrait_node else None,
    }

    parse_warnings: list[str] = []
    structured_nodes = []
    for node in nodes:
        levels = []
        for level in node["levels"]:
            level_value = level["level"]
            level_key = str(level_value) if level_value is not None else "unspecified"
            effects = []
            for effect_index, text in enumerate(level["lines"]):
                effect_id = (
                    f"{season}.hero.{entity_id}.node.{node['index']}."
                    f"level.{level_key}.effect.{effect_index}"
                )
                effects.append(
                    {
                        "effect_id": effect_id,
                        "text": text,
                        "source": {
                            "url": page_url,
                            "node_index": node["index"],
                            "node_name": node["name"],
                            "trait_level": level_value,
                            "effect_index": effect_index,
                            "raw_html_sha256": raw_sha256,
                        },
                    }
                )
            levels.append({"level": level_value, "effects": effects})
        structured_nodes.append(
            {
                "index": node["index"],
                "name": node["name"],
                "required_level": node["required_level"],
                "icon": node["icon"],
                "levels": levels,
                "source_text": node["source_text"],
            }
        )

    return {
        "schema_version": 1,
        "season": season,
        "entity_type": "hero_trait",
        "entity_id": entity_id,
        "name_zh": name_zh or f"{character_name}|{trait_name}",
        "character_name_zh": character_name,
        "trait_name_zh": trait_name,
        "hero_label": trait_header.text(),
        "page_url": page_url,
        "raw_html_sha256": raw_sha256,
        "summary": summary,
        "portrait": portrait,
        "recommended_skill": recommended_skill,
        "nodes": structured_nodes,
        "parse_warnings": parse_warnings,
    }


def write_report(report: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    report = {
        "schema_version": 1,
        "hero_id": HERO_ID,
        "season": SEASON,
        "success": False,
        "raw_sha256_verified": False,
        "node_count": 0,
        "node_names": [],
        "nodes_with_required_level": 0,
        "nodes_with_explicit_levels": 0,
        "total_effect_lines": 0,
        "skill_shop_excluded": True,
        "summary_clean": False,
        "recommended_skill_found": False,
        "portrait_found": False,
        "nodes_with_multiple_effect_lines": 0,
        "warnings": [],
        "errors": [],
    }
    try:
        if not RAW_PATH.is_file():
            raise ValueError("raw HTML does not exist")
        if not META_PATH.is_file():
            raise ValueError("meta JSON does not exist")
        try:
            meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"meta JSON is invalid: {exc}") from exc

        raw = RAW_PATH.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != meta.get("sha256"):
            raise ValueError("raw HTML SHA-256 does not match meta")
        report["raw_sha256_verified"] = True

        encoding = meta.get("encoding") or "utf-8"
        try:
            html = raw.decode(encoding)
        except (LookupError, UnicodeDecodeError) as exc:
            raise ValueError(f"raw HTML decoding failed: {exc}") from exc

        parser = TreeParser()
        parser.feed(html)
        elements = list(parser.root.descendants())
        for order, element in enumerate(elements):
            element.order = order

        title_node = next((item for item in elements if item.tag == "title" and item.text()), None)
        page_title = title_node.text() if title_node else ""

        first_title = next(
            (item for item in elements if has_class(item, "fw-bold") and item.text() == "怒火"),
            None,
        )
        if first_title is None or first_title.parent is None or first_title.parent.parent is None:
            raise ValueError("first hero node container was not found")
        first_box = first_title.parent.parent

        shop_orders = [
            item.order for item in elements
            if "技能商店" in item.own_text() and item.order > first_box.order
        ]
        shop_order = min(shop_orders) if shop_orders else len(elements)
        boxes = []
        seen = set()
        for item in elements:
            if item.order < first_box.order or item.order >= shop_order or not has_class(item, "fw-bold"):
                continue
            name = item.text()
            box = item.parent.parent if item.parent and item.parent.parent else None
            if not box or box.order in seen or not has_class(box, "d-flex") or not has_class(box, "border-top"):
                continue
            seen.add(box.order)
            boxes.append(box)

        nodes = [parse_node(box, index) for index, box in enumerate(boxes)]
        names = [node["name"] for node in nodes]

        preceding = [item for item in elements if item.order < first_box.order]
        named = [
            item.own_text() for item in preceding
            if item.own_text() and any(term in item.own_text() for term in ("狂人", "雷恩"))
        ]
        name = min(named, key=len) if named else ""
        if not name:
            anger_titles = [item.own_text() for item in preceding if item.own_text() == "怒火"]
            name = anger_titles[0] if anger_titles else ""

        label_node = next(
            (
                item for item in preceding
                if item.tag == "h5"
                and has_class(item, "card-header")
                and item.text().startswith("怒火 - 英雄特性")
            ),
            None,
        )
        hero_label = label_node.text() if label_node else ""

        name_link = next(
            (item for item in preceding if item.tag == "a" and item.own_text() == name),
            None,
        )
        hero_card = name_link.parent if name_link else None
        segments = direct_break_segments(hero_card) if hero_card else []
        summary_candidates = [
            segment for segment in segments
            if segment != name
            and "暴走巨刃" not in segment
            and any(term in segment for term in ("怒气", "暴气", "战斗属性"))
        ]
        summary = max(summary_candidates, key=len) if summary_candidates else ""

        recommended = {"name": "", "url": None}
        if hero_card:
            skill_links = [
                child for child in hero_card.children
                if isinstance(child, Element)
                and child.tag == "a"
                and child is not name_link
                and child.text()
                and child.attrs.get("href")
                and any(item.tag == "img" for item in child.descendants())
            ]
            if skill_links:
                recommended = {
                    "name": skill_links[0].text(),
                    "url": urljoin(SOURCE_URL, skill_links[0].attrs["href"]),
                }

        portrait = {"alt": None, "url": None}
        if hero_card:
            portrait_node = next(
                (
                    child for child in hero_card.children
                    if isinstance(child, Element)
                    and child.tag == "img"
                    and "size128" in child.attrs.get("class", "").split()
                    and child.attrs.get("src")
                ),
                None,
            )
            if portrait_node:
                portrait = {
                    "alt": clean(portrait_node.attrs.get("alt", "")) or None,
                    "url": urljoin(SOURCE_URL, portrait_node.attrs["src"]),
                }

        errors = []
        if not name:
            errors.append("hero name was not found")
        if not summary:
            errors.append("hero summary was not found")
        if not nodes:
            errors.append("no hero nodes were found")
        if nodes and names[0] != "怒火":
            errors.append("first node is not 怒火")
        missing = sorted(CORE_NODES - set(names))
        if missing:
            errors.append("missing core nodes: " + ", ".join(missing))
        if len(nodes) > 20:
            errors.append("node count exceeds 20")
        if any("技能商店" in name for name in names):
            errors.append("skill shop content was parsed as a node")
        summary_clean = bool(summary) and name not in summary and "暴走巨刃" not in summary
        recommended_skill_found = bool(recommended["name"])
        portrait_found = bool(portrait["url"])
        nodes_with_multiple_effect_lines = sum(
            any(len(level["lines"]) > 1 for level in node["levels"]) for node in nodes
        )
        total_effect_lines = sum(
            len(level["lines"]) for node in nodes for level in node["levels"]
        )
        if not summary_clean:
            errors.append("hero summary contains unrelated card content")
        if not recommended_skill_found:
            errors.append("recommended skill was not found")
        if nodes and nodes_with_multiple_effect_lines == 0:
            report["warnings"].append("Effect lines could not be split from the page structure.")
            errors.append("all node levels contain at most one effect line")
        if total_effect_lines < 15:
            errors.append("total effect lines is below 15")
        if not portrait_found:
            report["warnings"].append("Hero portrait could not be reliably identified.")

        report.update({
            "node_count": len(nodes),
            "node_names": names,
            "nodes_with_required_level": sum(node["required_level"] is not None for node in nodes),
            "nodes_with_explicit_levels": sum(
                any(level["level"] is not None for level in node["levels"]) for node in nodes
            ),
            "total_effect_lines": total_effect_lines,
            "skill_shop_excluded": not any("技能商店" in node["source_text"] for node in nodes),
            "summary_clean": summary_clean,
            "recommended_skill_found": recommended_skill_found,
            "portrait_found": portrait_found,
            "nodes_with_multiple_effect_lines": nodes_with_multiple_effect_lines,
            "errors": errors,
        })
        if errors:
            raise ValueError("; ".join(errors))

        parsed = {
            "schema_version": 1,
            "hero_id": HERO_ID,
            "season": SEASON,
            "source": {
                "url": SOURCE_URL,
                "raw_file": RAW_REL.as_posix(),
                "meta_file": META_REL.as_posix(),
                "fetched_at": meta.get("fetched_at"),
                "sha256": meta.get("sha256"),
            },
            "name": name,
            "page_title": page_title,
            "hero_label": hero_label,
            "summary": summary,
            "recommended_skill": recommended,
            "portrait": portrait,
            "nodes": nodes,
        }
        encoded = json.dumps(parsed, ensure_ascii=False, indent=2) + "\n"
        if not encoded.strip():
            raise ValueError("parsed output is empty")
        PARSED_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = PARSED_PATH.with_suffix(".json.tmp")
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(PARSED_PATH)
        report["success"] = True
        write_report(report)

        print("Parsed hero page")
        print(f"- hero: {name}")
        print(f"- nodes: {len(nodes)}")
        print(f"- output: {PARSED_REL}")
        print(f"- report: {REPORT_REL}")
        return 0
    except (OSError, ValueError) as exc:
        message = str(exc)
        if message and message not in report["errors"]:
            report["errors"].append(message)
        write_report(report)
        print(f"Parse failed: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
