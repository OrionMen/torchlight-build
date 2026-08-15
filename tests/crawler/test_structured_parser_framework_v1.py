from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from crawler.structured.parser_base import ParserInput
from crawler.structured.parser_registry import ParserRegistry
from crawler.structured.parsers.str_helmet import StrHelmetBaseAffixParser
from crawler.structured.run_str_helmet_demo import DEFAULT_INPUT, generate_demo
from crawler.structured.schema import resolve_record_landing, validate_record


def fixture(*, modifier_text: str = "+10 最大生命", section: bool = True) -> str:
    pane_id = "力量头部基础词缀" if section else "已改变的区域"
    return f"""
    <html><body><button data-bs-target="#{pane_id}">base</button>
    <div id="{pane_id}" class="tab-pane fade"><table><thead><tr>
    <th>Tier</th><th>Modifier</th><th>Level</th><th>Weight</th>
    </tr></thead><tbody><tr><td>2</td><td>
    <span data-modifier-id="1507000">{modifier_text}</span>
    </td><td>1</td><td>1</td></tr></tbody></table></div></body></html>
    """


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class StructuredParserFrameworkV1Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def parse(self, html: str, name: str = "case") -> dict:
        directory = self.temp_path / name
        directory.mkdir(parents=True, exist_ok=True)
        raw = directory / "STR_Helmet.html"
        raw.write_text(html, encoding="utf-8")
        return StrHelmetBaseAffixParser().parse(
            ParserInput(
                season_id="ss13",
                system_id="inventory",
                canonical_id="STR_Helmet",
                canonical_route="/cn/STR_Helmet/",
                raw_html_path=raw,
            )
        )

    def test_offline_raw_parse_and_schema(self) -> None:
        result = self.parse(fixture())
        self.assertEqual(1, result["record_count"])
        self.assertEqual("matched", result["structure_validation"]["status"])
        validate_record(result["records"][0])

    def test_record_identity_and_signature_ignore_text_and_numeric_changes(self) -> None:
        before = self.parse(fixture(modifier_text="+10 最大生命"), "before")
        after = self.parse(fixture(modifier_text="+999 完全不同的描述"), "after")
        self.assertEqual(before["records"][0]["record_id"], after["records"][0]["record_id"])
        self.assertEqual(before["structure_signature"], after["structure_signature"])
        self.assertNotEqual(before["records"][0]["text"], after["records"][0]["text"])

    def test_source_locator_and_landing_contract(self) -> None:
        record = self.parse(fixture())["records"][0]
        self.assertEqual("modifier:1507000", record["source_locator"]["stable_key"])
        self.assertEqual("record", record["source_locator"]["locator_level"])
        self.assertEqual("high", record["source_locator"]["locator_confidence"])
        self.assertEqual(
            {
                "route": "/cn/STR_Helmet/",
                "section": "base_affix",
                "locator_level": "record",
                "anchor": "#力量头部基础词缀",
                "record_key": "modifier:1507000",
            },
            resolve_record_landing(record),
        )

    def test_critical_dom_change_returns_structure_mismatch(self) -> None:
        result = self.parse(fixture(section=False))
        self.assertEqual(0, result["record_count"])
        self.assertEqual("structure_mismatch", result["structure_validation"]["status"])
        self.assertIn("section_present", result["structure_validation"]["mismatches"])

    def test_registry_is_explicit(self) -> None:
        registry = ParserRegistry()
        parser = registry.register(StrHelmetBaseAffixParser())
        self.assertIs(parser, registry.get(parser.parser_id))
        self.assertEqual(("inventory.str_helmet.base_affix",), registry.list_parser_ids())

    def test_real_demo_and_v1_outputs_unchanged(self) -> None:
        root = Path(__file__).resolve().parents[2]
        v1_paths = [
            root / "data/generated/entity-index-v3.json",
            root / "local_wiki/ss13/site/search-index.json",
        ]
        before = {path: sha256(path) for path in v1_paths if path.exists()}
        result, report = generate_demo(
            input_path=DEFAULT_INPUT,
            output_path=self.temp_path / "STR_Helmet.json",
            report_path=self.temp_path / "report.json",
        )
        self.assertEqual(22, result["record_count"])
        self.assertFalse(report["v1_modified"])
        self.assertEqual({path: sha256(path) for path in before}, before)
        self.assertEqual(
            22,
            json.loads((self.temp_path / "STR_Helmet.json").read_text(encoding="utf-8"))["record_count"],
        )


if __name__ == "__main__":
    unittest.main()
