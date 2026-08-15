"""Generate the one-page Structured Parser Framework v1 demonstration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .parser_base import ParserInput
from .parsers import StrHelmetBaseAffixParser


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "data/raw/manifests/inventory/raw_html/STR_Helmet.html"
DEFAULT_OUTPUT = ROOT / "data/generated/structured/ss13/inventory/STR_Helmet.json"
DEFAULT_REPORT = ROOT / "data/reports/local-wiki/structured-parser-framework-v1-report.json"


def generate_demo(
    *,
    input_path: Path = DEFAULT_INPUT,
    output_path: Path = DEFAULT_OUTPUT,
    report_path: Path = DEFAULT_REPORT,
) -> tuple[dict, dict]:
    parser = StrHelmetBaseAffixParser()
    result = parser.parse(
        ParserInput(
            season_id="ss13",
            system_id="inventory",
            canonical_id="STR_Helmet",
            canonical_route="/cn/STR_Helmet/",
            raw_html_path=input_path,
        )
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    levels: dict[str, int] = {}
    for record in result["records"]:
        level = record["source_locator"]["locator_level"]
        levels[level] = levels.get(level, 0) + 1
    report = {
        "framework_version": 1,
        "demo_parser": parser.parser_id,
        "input_page": "/cn/STR_Helmet/",
        "records_generated": result["record_count"],
        "locator_levels": levels,
        "structure_signature": result["structure_signature"],
        "structure_validation": result["structure_validation"],
        "v1_modified": False,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result, report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    result, _ = generate_demo(
        input_path=args.input, output_path=args.output, report_path=args.report
    )
    return 0 if result["structure_validation"]["status"] == "matched" else 2


if __name__ == "__main__":
    raise SystemExit(main())
