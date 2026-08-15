from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urlencode

from crawler.build_full_wiki_mirror import build, local_assets
from crawler.structured.report_search_integration import build_report
from crawler.structured.run_equipment_parser import DEFAULT_RAW_ROOT, generate_equipment_structured_data


ROOT = Path(__file__).resolve().parents[2]
INDEX_PATH = ROOT / "data/generated/structured/ss13/structured-search-index.json"
V1_SEARCH_PATH = ROOT / "local_wiki/ss13/site/search-index.json"
EQUIPMENT_PAGE_PATH = ROOT / "local_wiki/ss13/site/cn/STR_Helmet/index.html"
DEPLOYED_LANDING_PATH = ROOT / "local_wiki/ss13/site/_local/mirror.js"


class StructuredSearchIntegrationV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        cls.records = cls.index["records"]
        assets = local_assets()
        cls.search_script = assets["_local/search/app.js"]
        cls.landing_script = assets["_local/mirror.js"]
        cls.styles = assets["_local/search/styles.css"]

    def test_real_base_and_craft_affix_keywords_are_searchable(self) -> None:
        base = [record for record in self.records if record["record_type"] == "equipment_base_affix" and "最大生命" in record["text"]]
        craft = [record for record in self.records if record["record_type"] == "equipment_craft_affix" and "攻击速度" in record["text"]]
        self.assertTrue(base)
        self.assertTrue(craft)

    def test_same_entity_keeps_multiple_record_matches(self) -> None:
        matches = [record for record in self.records if "攻击速度" in record["text"]]
        counts = Counter(record["entity_id"] for record in matches)
        self.assertGreater(max(counts.values()), 1)
        self.assertIn("groupStructured", self.search_script)
        self.assertIn("records:[]", self.search_script)
        self.assertIn("group.records.slice(0,STRUCTURED_LIMIT)", self.search_script)
        self.assertIn("还有 ${remaining} 条匹配", self.search_script)

    def test_structured_match_suppresses_only_matching_v1_entity(self) -> None:
        self.assertIn("structuredEntities.has(hit.x.entity_id)", self.search_script)
        self.assertIn("!structuredEntities.has(hit.x.entity_id)", self.search_script)
        self.assertIn("collapseEntityHits", self.search_script)

    def test_no_structured_match_keeps_v1_page_search(self) -> None:
        self.assertIn("const hits=pages.map", self.search_script)
        self.assertIn("const displayHits=collapseEntityHits(hits.filter", self.search_script)
        self.assertIn("structuredHits(k)", self.search_script)

    def test_content_tree_filter_requires_equipment_and_craft_path(self) -> None:
        ordinary = [record for record in self.records if record.get("entity_type") == "equipment"]
        self.assertTrue(all(record["content_category_id"] == "equipment" for record in ordinary))
        self.assertTrue(all(record["content_subcategory_id"] == "equipment_craft" for record in ordinary))
        self.assertIn("matchesStructuredTree", self.search_script)
        self.assertIn("x.content_category_id===selectedCategory", self.search_script)
        self.assertIn("x.content_subcategory_id===selectedSubcategory", self.search_script)

    def test_record_href_uses_stable_identity_not_text_or_row_index(self) -> None:
        self.assertIn("structured_record:x.record_id", self.search_script)
        self.assertIn("structured_key:x.source_locator.stable_key", self.search_script)
        self.assertIn("structured_section:x.source_locator.dom_id||x.source_locator.section_key", self.search_script)
        self.assertIn("if(x.tier)data.structured_tier=x.tier", self.search_script)
        self.assertIn("String(x.route).replace(/^[/]+/,'')", self.search_script)
        href_function = self.search_script.split("const structuredHref=", 1)[1].split(";\n", 1)[0]
        self.assertNotIn("x.text", href_function)
        self.assertNotIn("row_index", href_function)

    def test_landing_activates_tab_and_resolves_modifier_key(self) -> None:
        self.assertIn("params.get('structured_record')", self.landing_script)
        self.assertIn("params.get('structured_key')", self.landing_script)
        self.assertIn("params.get('structured_section')", self.landing_script)
        self.assertIn("bootstrap.Tab.getOrCreateInstance(trigger).show()", self.landing_script)
        self.assertIn("trigger.addEventListener('shown.bs.tab',applyTierAndLocate,{once:true})", self.landing_script)
        self.assertIn("data-modifier-id", self.landing_script)
        self.assertIn("stableKey.slice('modifier:'.length)", self.landing_script)
        self.assertIn("root.querySelectorAll('[data-modifier-id]')", self.landing_script)
        self.assertNotIn("document.querySelector(`[data-modifier-id", self.landing_script)
        self.assertIn("const target=", self.landing_script)
        self.assertIn("scrollIntoView", self.landing_script)
        self.assertIn("row.style.backgroundColor='#fef08a'", self.landing_script)
        self.assertIn("row.style.outline='3px solid #f59e0b'", self.landing_script)
        self.assertIn("tierValues={t0_plus:'0+',t0:'0',t1:'1',t2:'2'}", self.landing_script)
        self.assertIn("tierValues[tier]||'all'", self.landing_script)
        self.assertIn("4500", self.landing_script)

    def test_real_base_and_craft_records_share_url_parameter_contract(self) -> None:
        expected = {
            "equipment_base_affix": ("modifier:1507000", "力量头部基础词缀"),
            "equipment_craft_affix": ("modifier:104700080", "力量头部打造"),
        }
        for record_type, (stable_key, section) in expected.items():
            with self.subTest(record_type=record_type):
                record = next(
                    item for item in self.records
                    if item["entity_id"] == "tlidb:cn:STR_Helmet"
                    and item["record_type"] == record_type
                    and item["source_locator"]["stable_key"] == stable_key
                )
                query = urlencode({
                    "structured_record": record["record_id"],
                    "structured_key": record["source_locator"]["stable_key"],
                    "structured_section": record["source_locator"]["dom_id"],
                })
                parsed = parse_qs(query)
                self.assertEqual([record["record_id"]], parsed["structured_record"])
                self.assertEqual([stable_key], parsed["structured_key"])
                self.assertEqual([section], parsed["structured_section"])

    def test_real_base_and_craft_targets_exist_in_their_own_tab_panes(self) -> None:
        html = EQUIPMENT_PAGE_PATH.read_text(encoding="utf-8")
        expected = {
            "力量头部基础词缀": "1507000",
            "力量头部打造": "104700080",
        }
        for section, modifier_id in expected.items():
            with self.subTest(section=section):
                self.assertIn(f'data-bs-target="#{section}"', html)
                pane_start = html.index(f'id="{section}" class="tab-pane')
                next_pane = html.find('<div id="', pane_start + 1)
                pane_html = html[pane_start:next_pane if next_pane >= 0 else None]
                self.assertIn(f'data-modifier-id="{modifier_id}"', pane_html)

    def test_landing_fallbacks_record_to_section_and_missing_section_to_page(self) -> None:
        self.assertIn("landing=target||", self.landing_script)
        self.assertIn("if(located)return", self.landing_script)
        self.assertIn("else waitForViewAndLocate();return", self.landing_script)

    def test_deployed_landing_script_matches_builder_asset(self) -> None:
        self.assertTrue(DEPLOYED_LANDING_PATH.is_file())
        self.assertIn("structured_record", DEPLOYED_LANDING_PATH.read_text(encoding="utf-8"))

    def test_missing_or_invalid_structured_index_falls_back_to_v1(self) -> None:
        self.assertIn("const loadStructured=()", self.search_script)
        self.assertIn(".catch(()=>[])", self.search_script)
        self.assertIn("fetch('../../search-index.json')", self.search_script)
        with tempfile.TemporaryDirectory() as temporary:
            invalid = Path(temporary) / "invalid.json"
            invalid.write_text("not json", encoding="utf-8")
            report = build_report(invalid)
        self.assertTrue(report["errors"])
        self.assertEqual(0, report["structured_documents"])

    def test_structured_result_has_minimal_record_presentation(self) -> None:
        required = {"entity_title", "record_type", "section_name", "text", "route", "source_locator"}
        self.assertTrue(all(required <= set(record) for record in self.records))
        self.assertIn("structured-record-type", self.search_script)
        self.assertIn("structured-entity", self.styles)

    def test_report_and_v1_schema_contract(self) -> None:
        report = build_report(INDEX_PATH)
        self.assertEqual(28780, report["structured_documents"])
        self.assertEqual(["equipment", "equipment_related_system", "fate", "hero", "legendary_equipment", "memory_system", "pact_spirit", "skill", "talent", "talent_system", "vorax_equipment"], report["supported_entity_types"])
        self.assertEqual(28048, report["landing"]["record_level"])
        self.assertEqual([], report["errors"])
        v1 = json.loads(V1_SEARCH_PATH.read_text(encoding="utf-8"))
        self.assertEqual(8, v1["schema_version"])

    def test_generator_can_build_overlay_without_touching_v1_index(self) -> None:
        before = V1_SEARCH_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, search, report = generate_equipment_structured_data(
                raw_root=DEFAULT_RAW_ROOT,
                output_root=root / "structured",
                report_path=root / "report.json",
            )
        self.assertEqual(10442, search["record_count"])
        self.assertEqual(0, report["structure_mismatches"])
        self.assertEqual(before, V1_SEARCH_PATH.read_bytes())

    def test_builder_copies_overlay_without_changing_v1_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_root = root / "raw"
            raw_root.mkdir()
            asset_manifest = root / "assets.json"
            asset_manifest.write_text('{"assets": []}', encoding="utf-8")
            catalog = root / "catalog.json"
            catalog.write_text('{"pages": []}', encoding="utf-8")
            old_search = root / "search-index.json"
            old_search.write_text('{"schema_version": 8, "pages": []}', encoding="utf-8")
            output = root / "site"
            build(
                "ss13",
                raw_root,
                asset_manifest,
                root / "asset-files",
                output,
                catalog_path=catalog,
                search_index_path=old_search,
                structured_search_index_path=INDEX_PATH,
            )
            copied = json.loads((output / "structured-search-index.json").read_text(encoding="utf-8"))
            generated_v1 = json.loads((output / "search-index.json").read_text(encoding="utf-8"))
        self.assertEqual(28780, copied["record_count"])
        self.assertEqual(8, generated_v1["schema_version"])


if __name__ == "__main__":
    unittest.main()
