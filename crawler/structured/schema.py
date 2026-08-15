"""Schema helpers shared by structured sidecar parsers."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


SCHEMA_VERSION = 1
LOCATOR_LEVELS = {"page", "section", "record"}
LOCATOR_CONFIDENCE = {"low", "medium", "high"}
REQUIRED_RECORD_FIELDS = {
    "record_id",
    "season_id",
    "entity_id",
    "entity_type",
    "record_type",
    "section_id",
    "section_name",
    "text",
    "route",
    "source_system",
    "source_page_id",
    "source_locator",
    "source_record_index",
    "parser_id",
    "parser_version",
}
REQUIRED_LOCATOR_FIELDS = {
    "section_key",
    "dom_id",
    "tab_target",
    "row_index",
    "stable_key",
    "locator_confidence",
    "locator_level",
}


def make_record_id(
    *,
    parser_id: str,
    entity_id: str,
    record_type: str,
    section_key: str,
    stable_key: str,
) -> str:
    """Return an identity independent from season, prose, and numeric values."""

    identity = {
        "entity_id": entity_id,
        "parser_id": parser_id,
        "record_type": record_type,
        "section_key": section_key,
        "stable_key": stable_key,
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]
    return f"tlidb:record:{digest}"


def validate_source_locator(locator: Mapping[str, Any]) -> None:
    missing = REQUIRED_LOCATOR_FIELDS - set(locator)
    if missing:
        raise ValueError(f"source_locator missing fields: {sorted(missing)}")
    if locator["locator_level"] not in LOCATOR_LEVELS:
        raise ValueError(f"invalid locator_level: {locator['locator_level']}")
    if locator["locator_confidence"] not in LOCATOR_CONFIDENCE:
        raise ValueError(
            f"invalid locator_confidence: {locator['locator_confidence']}"
        )
    if not isinstance(locator["row_index"], int) or locator["row_index"] < 0:
        raise ValueError("source_locator.row_index must be a non-negative integer")


def validate_record(record: Mapping[str, Any]) -> None:
    missing = REQUIRED_RECORD_FIELDS - set(record)
    if missing:
        raise ValueError(f"structured record missing fields: {sorted(missing)}")
    for field in REQUIRED_RECORD_FIELDS - {"source_locator", "source_record_index"}:
        if not isinstance(record[field], str) or not record[field]:
            raise ValueError(f"structured record field {field!r} must be non-empty")
    if not isinstance(record["source_record_index"], int):
        raise ValueError("source_record_index must be an integer")
    validate_source_locator(record["source_locator"])


def resolve_record_landing(record: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve the most precise landing contract currently supported by a record."""

    validate_record(record)
    locator = record["source_locator"]
    anchor = locator.get("dom_id") or str(locator.get("tab_target") or "").lstrip("#")
    landing = {
        "route": record["route"],
        "section": record["section_id"],
        "locator_level": locator["locator_level"],
        "anchor": f"#{anchor}" if anchor else None,
        "record_key": locator["stable_key"],
    }
    if "tier" in record:
        landing["tier"] = record.get("tier")
        landing["source_tier_value"] = locator.get("tier_value")
    if locator.get("view_state"):
        landing["view_state"] = dict(locator["view_state"])
    return landing
