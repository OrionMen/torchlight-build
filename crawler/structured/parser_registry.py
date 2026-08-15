"""Explicit parser registry; v1 builders do not import or execute it."""

from __future__ import annotations

from .parser_base import StructuredParser


class ParserRegistry:
    def __init__(self) -> None:
        self._parsers: dict[str, StructuredParser] = {}

    def register(self, parser: StructuredParser) -> StructuredParser:
        if parser.parser_id in self._parsers:
            raise ValueError(f"parser already registered: {parser.parser_id}")
        self._parsers[parser.parser_id] = parser
        return parser

    def get(self, parser_id: str) -> StructuredParser:
        try:
            return self._parsers[parser_id]
        except KeyError as exc:
            raise KeyError(f"unknown structured parser: {parser_id}") from exc

    def list_parser_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._parsers))
