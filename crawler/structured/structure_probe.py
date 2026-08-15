"""Small DOM probes used to validate parser assumptions without hashing content."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any


@dataclass(frozen=True)
class TableRow:
    cells: tuple[str, ...]
    stable_key: str | None
    tier_value: str | None = None


@dataclass(frozen=True)
class SectionTable:
    headers: tuple[str, ...]
    rows: tuple[TableRow, ...]


class _SectionTableParser(HTMLParser):
    def __init__(self, target_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.target_id = target_id
        self.section_present = False
        self.section_classes: list[str] = []
        self.tab_target_present = False
        self._target_div_depth = 0
        self._in_target = False
        self._in_table = False
        self._in_th = False
        self._in_td = False
        self._cell_parts: list[str] = []
        self._cells: list[str] = []
        self._row_key: str | None = None
        self._row_tier: str | None = None
        self.headers: list[str] = []
        self.rows: list[TableRow] = []
        self.tables: list[SectionTable] = []
        self._table_headers: list[str] = []
        self._table_rows: list[TableRow] = []
        self.table_count = 0

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs_list)
        if attrs.get("data-bs-target") == f"#{self.target_id}":
            self.tab_target_present = True
        if tag == "div" and attrs.get("id") == self.target_id and not self._in_target:
            self._in_target = True
            self._target_div_depth = 1
            self.section_present = True
            self.section_classes = sorted((attrs.get("class") or "").split())
            return
        if not self._in_target:
            return
        if tag == "div":
            self._target_div_depth += 1
        elif tag == "table":
            self._in_table = True
            self.table_count += 1
            self._table_headers = []
            self._table_rows = []
        elif self._in_table and tag == "tr":
            self._finish_row()
            self._cells = []
            self._row_key = None
            self._row_tier = attrs.get("data-tier")
        elif self._in_table and tag in {"th", "td"}:
            self._finish_cell()
            self._in_th = tag == "th"
            self._in_td = tag == "td"
            self._cell_parts = []
        if self._in_table and attrs.get("data-modifier-id"):
            self._row_key = attrs["data-modifier-id"]

    def handle_endtag(self, tag: str) -> None:
        if not self._in_target:
            return
        if self._in_table and tag in {"th", "td"}:
            self._finish_cell()
        elif self._in_table and tag == "tr" and self._cells:
            self._finish_row()
        elif tag == "table" and self._in_table:
            self._finish_cell()
            self._finish_row()
            self.tables.append(SectionTable(tuple(self._table_headers), tuple(self._table_rows)))
            self._in_table = False
        if tag == "div":
            self._target_div_depth -= 1
            if self._target_div_depth <= 0:
                self._in_target = False

    def handle_data(self, data: str) -> None:
        if self._in_target and self._in_table and (self._in_th or self._in_td):
            self._cell_parts.append(data)

    def _finish_cell(self) -> None:
        if not (self._in_th or self._in_td):
            return
        text = " ".join("".join(self._cell_parts).split())
        if self._in_th:
            self.headers.append(text)
            self._table_headers.append(text)
        else:
            self._cells.append(text)
        self._in_th = False
        self._in_td = False
        self._cell_parts = []

    def _finish_row(self) -> None:
        self._finish_cell()
        if not self._cells:
            return
        row = TableRow(tuple(self._cells), self._row_key, self._row_tier)
        self.rows.append(row)
        self._table_rows.append(row)
        self._cells = []
        self._row_key = None
        self._row_tier = None


def probe_section_table(html: str, *, section_id: str) -> dict[str, Any]:
    parser = _SectionTableParser(section_id)
    parser.feed(html)
    descriptor = {
        "section_present": parser.section_present,
        "section_id": section_id,
        "section_classes": parser.section_classes,
        "tab_target_present": parser.tab_target_present,
        "table_count": parser.table_count,
        "headers": parser.headers if parser.table_count != 1 else list(parser.tables[0].headers),
        "table_headers": [list(table.headers) for table in parser.tables],
        "row_count": len(parser.rows),
        "stable_key_attribute": "data-modifier-id",
        "rows_with_stable_key": sum(row.stable_key is not None for row in parser.rows),
        "tier_attribute": "data-tier" if any(row.tier_value is not None for row in parser.rows) else None,
        "rows_with_tier": sum(row.tier_value is not None for row in parser.rows),
    }
    signature_payload = {
        "section_present": descriptor["section_present"],
        "section_classes": descriptor["section_classes"],
        "tab_target_present": descriptor["tab_target_present"],
        "table_count": descriptor["table_count"],
        "headers": descriptor["headers"],
        "table_headers": descriptor["table_headers"],
        "row_count": descriptor["row_count"],
        "stable_key_attribute": descriptor["stable_key_attribute"],
        "rows_with_stable_key": descriptor["rows_with_stable_key"],
        "tier_attribute": descriptor["tier_attribute"],
        "rows_with_tier": descriptor["rows_with_tier"],
    }
    signature = hashlib.sha256(
        json.dumps(signature_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "descriptor": descriptor,
        "structure_signature": signature,
        "rows": parser.rows,
        "tables": parser.tables,
    }
