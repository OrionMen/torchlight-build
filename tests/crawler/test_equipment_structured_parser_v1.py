from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from crawler.structured.parser_base import ParserInput
from crawler.structured.parsers.equipment_parser import (
    EQUIPMENT_DEFINITIONS,
    EquipmentDefinition,
    EquipmentParser,
)
from crawler.structured.run_equipment_parser import (
    DEFAULT_RAW_ROOT,
    generate_equipment_structured_data,
)
from crawler.structured.schema import resolve_record_landing


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _table(key: str, text: str, *, craft: bool) -> str:
    headers = (
        "<th>Tier</th><th>Modifier</th><th>Lv</th><th>Weight</th><th>Library</th>"
        if craft
        else "<th>Tier</th><th>Modifier</th><th>Level</th><th>Weight</th>"
    )
    extra = "<td>初阶词缀</td>" if craft else ""
    row_attr = ' data-tier="1"' if craft else ""
    return (
        f"<table><thead><tr>{headers}</tr></thead><tbody><tr{row_attr}><td>1</td>"
        f"<td><span data-modifier-id=\"{key}\">{text}</span></td>"
        f"<td>1</td><td>1</td>{extra}</tr></tbody></table>"
    )


def _fixture(base_text: str = "+10 最大生命", craft_text: str = "+20 护甲") -> str:
    return f"""
    <button data-bs-target="#力量头部基础词缀">base</button>
    <button data-bs-target="#力量头部打造">craft</button>
    <div id="力量头部基础词缀" class="tab-pane fade">
      {_table("1507000", base_text, craft=False)}
    </div>
    <div id="力量头部打造" class="tab-pane fade">
      {_table("104700001", craft_text, craft=True)}
      {_table("104700002", "+30 火焰抗性", craft=True)}
    </div>
    """


class EquipmentStructuredParserV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.temp_path = Path(cls.temp.name)
        root = Path(__file__).resolve().parents[2]
        cls.v1_paths = [
            root / "data/generated/entity-index-v3.json",
            root / "local_wiki/ss13/site/search-index.json",
        ]
        cls.v1_before = {path: _sha256(path) for path in cls.v1_paths if path.exists()}
        cls.results, cls.search, cls.report = generate_equipment_structured_data(
            raw_root=DEFAULT_RAW_ROOT,
            output_root=cls.temp_path / "structured",
            report_path=cls.temp_path / "report.json",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def parse_fixture(self, html: str) -> dict:
        raw = self.temp_path / "fixture.html"
        raw.write_text(html, encoding="utf-8")
        definition = EquipmentDefinition("STR_Helmet", "力量头部")
        return EquipmentParser(definition).parse(
            ParserInput("ss13", "inventory", definition.canonical_id, definition.route, raw)
        )

    def test_all_38_confirmed_equipment_entities_are_processed(self) -> None:
        self.assertEqual(38, len(EQUIPMENT_DEFINITIONS))
        self.assertEqual(38, len(self.results))
        self.assertEqual(38, self.report["parsed_entities"])
        self.assertEqual(0, self.report["structure_mismatches"])

    def test_base_and_craft_affixes_are_split(self) -> None:
        helmet = next(result for result in self.results if result["entity_id"] == "tlidb:cn:STR_Helmet")
        self.assertEqual(22, len(helmet["sections"]["base_affixes"]))
        self.assertEqual(285, len(helmet["sections"]["craft_affixes"]))
        self.assertTrue(
            all(record["record_type"] == "equipment_base_affix" for record in helmet["sections"]["base_affixes"])
        )
        self.assertTrue(
            all(record["record_type"] == "equipment_craft_affix" for record in helmet["sections"]["craft_affixes"])
        )

    def test_record_id_is_stable_when_values_and_description_change(self) -> None:
        before = self.parse_fixture(_fixture("+10 最大生命", "+20 护甲"))
        after = self.parse_fixture(_fixture("+999 完全变化", "+888 新描述"))
        before_ids = [record["record_id"] for section in before["sections"].values() for record in section]
        after_ids = [record["record_id"] for section in after["sections"].values() for record in section]
        self.assertEqual(before_ids, after_ids)

    def test_source_locator_and_landing_are_record_level(self) -> None:
        helmet = next(result for result in self.results if result["entity_id"] == "tlidb:cn:STR_Helmet")
        record = helmet["sections"]["base_affixes"][0]
        self.assertEqual("record", record["source_locator"]["locator_level"])
        self.assertEqual("modifier:1507000", record["source_locator"]["stable_key"])
        landing = resolve_record_landing(record)
        self.assertEqual("/cn/STR_Helmet/", landing["route"])
        self.assertEqual("base_affixes", landing["section"])
        self.assertEqual("modifier:1507000", landing["record_key"])

    def test_structure_mismatch_does_not_emit_empty_success(self) -> None:
        result = self.parse_fixture("<html><body>changed layout</body></html>")
        self.assertEqual("structure_mismatch", result["structure_validation"]["status"])
        self.assertEqual([], result["sections"]["base_affixes"])
        self.assertEqual([], result["sections"]["craft_affixes"])

    def test_equipment_module_index_is_self_contained(self) -> None:
        self.assertEqual(10442, self.search["record_count"])
        self.assertEqual(self.report["structured_search_records"], self.search["record_count"])
        self.assertTrue((self.temp_path / "structured/equipment-structured-index.json").is_file())
        self.assertFalse((self.temp_path / "structured/structured-search-index.json").exists())
        required = {
            "record_id", "entity_id", "entity_title", "record_type", "text",
            "route", "source_locator", "landing",
        }
        self.assertTrue(all(required <= set(record) for record in self.search["records"]))

    def test_all_current_records_have_stable_identity_and_record_locator(self) -> None:
        self.assertEqual(751, self.report["base_affix_records"])
        self.assertEqual(9691, self.report["craft_affix_records"])
        self.assertEqual(10442, self.report["record_level_locators"])
        self.assertEqual(0, self.report["section_level_locators"])
        self.assertEqual(0, self.report["unstable_identity_records"])

    def test_v1_entity_and_search_hashes_are_unchanged(self) -> None:
        self.assertEqual({path: _sha256(path) for path in self.v1_before}, self.v1_before)


if __name__ == "__main__":
    unittest.main()
