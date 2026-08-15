"""Base contract for offline, structure-aware v2 parsers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema import SCHEMA_VERSION, validate_record


@dataclass(frozen=True)
class ParserInput:
    season_id: str
    system_id: str
    canonical_id: str
    canonical_route: str
    raw_html_path: Path


class StructuredParser(ABC):
    parser_id: str
    parser_version: str

    @abstractmethod
    def probe(self, html: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def validate_structure(self, probe: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def parse_records(
        self, parser_input: ParserInput, probe: dict[str, Any]
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def parse(self, parser_input: ParserInput) -> dict[str, Any]:
        html = parser_input.raw_html_path.read_text(encoding="utf-8")
        probe = self.probe(html)
        validation = self.validate_structure(probe)
        records: list[dict[str, Any]] = []
        if validation["status"] == "matched":
            records = self.parse_records(parser_input, probe)
            for record in records:
                validate_record(record)
        return {
            "schema_version": SCHEMA_VERSION,
            "source_season": parser_input.season_id,
            "parser_id": self.parser_id,
            "parser_version": self.parser_version,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "record_count": len(records),
            "structure_signature": probe["structure_signature"],
            "structure_validation": validation,
            "source_page": {
                "system_id": parser_input.system_id,
                "canonical_id": parser_input.canonical_id,
                "canonical_route": parser_input.canonical_route,
                "raw_html_path": str(parser_input.raw_html_path),
            },
            "records": records,
        }
