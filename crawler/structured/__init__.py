"""Offline structured-data parser framework for v2 sidecar outputs."""

from .parser_base import ParserInput, StructuredParser
from .parser_registry import ParserRegistry
from .schema import resolve_record_landing, validate_record

__all__ = [
    "ParserInput",
    "ParserRegistry",
    "StructuredParser",
    "resolve_record_landing",
    "validate_record",
]
