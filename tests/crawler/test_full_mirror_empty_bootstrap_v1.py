import json
import tempfile
import unittest
from pathlib import Path

from crawler.build_full_wiki_mirror import build, local_assets


class FullMirrorEmptyBootstrapV1Test(unittest.TestCase):
    def make_inputs(self, root: Path, with_structured: bool) -> dict[str, Path]:
        raw_root = root / "raw"
        raw_page = raw_root / "active_skill/raw_html/Test_Skill.html"
        raw_page.parent.mkdir(parents=True)
        raw_page.write_text(
            "<!doctype html><html><head><title>测试技能</title></head>"
            "<body><main><h1>测试技能</h1><div class='tab-pane active show'>"
            "当前技能正文</div></main></body></html>",
            encoding="utf-8",
        )
        child_manifest = root / "active_skill_manifest.json"
        child_manifest.write_text(json.dumps({
            "schema_version": 1,
            "system_id": "active_skill",
            "entries": [{
                "id": "Test_Skill",
                "slug": "Test_Skill",
                "name_zh": "测试技能",
                "url": "https://tlidb.com/cn/Test_Skill",
            }],
        }), encoding="utf-8")
        system_manifest = root / "system_manifest.json"
        system_manifest.write_text(json.dumps({
            "schema_version": 1,
            "systems": [{
                "system_id": "active_skill",
                "name_zh": "主动技能",
                "discovery_status": "confirmed",
                "manifest_path": str(child_manifest),
            }],
        }), encoding="utf-8")
        asset_manifest = root / "asset-manifest.json"
        asset_manifest.write_text('{"assets": []}', encoding="utf-8")
        asset_root = root / "asset-files"
        asset_root.mkdir()
        entity_index = root / "entity-index-v3.json"
        entity_index.write_text(json.dumps({
            "schema_version": 3,
            "entities": [{
                "entity_id": "tlidb:cn:Test_Skill",
                "title": "测试技能",
                "canonical_route": "/cn/Test_Skill/",
                "content_category_id": "skill",
                "content_category_name_zh": "技能",
                "content_subcategory_id": "skill_active",
                "content_subcategory_name_zh": "主动技能",
                "sources": [{"system_id": "active_skill", "role": "primary"}],
                "confidence": "primary",
                "entity_title_zh": "测试技能",
                "entity_visibility": "visible",
                "entity_type": None,
                "clean_summary": "测试技能 当前技能正文",
            }],
        }), encoding="utf-8")
        category_mapping = root / "game-category.json"
        category_mapping.write_text(json.dumps({
            "categories": [{
                "id": "skill", "name_zh": "技能", "search_visibility": "primary",
                "systems": ["active_skill"],
            }],
        }), encoding="utf-8")
        content_tree = root / "content-tree.json"
        content_tree.write_text(json.dumps({
            "search_categories": [{
                "id": "skill", "name_zh": "技能", "search_visibility": "primary",
                "children": [{
                    "id": "skill_active", "name_zh": "主动技能",
                    "systems": ["active_skill"],
                }],
            }],
            "hidden_systems": [],
        }), encoding="utf-8")
        structured = root / "structured-search-index.json"
        if with_structured:
            structured.write_text(json.dumps({
                "schema_version": 1,
                "records": [{
                    "record_id": "skill:test",
                    "entity_id": "tlidb:cn:Test_Skill",
                    "entity_title": "测试技能",
                    "record_type": "skill_effect",
                    "text": "当前技能正文",
                    "search_text": "当前技能正文",
                    "route": "/cn/Test_Skill/",
                    "source_locator": {"stable_key": "skill:test"},
                }],
            }), encoding="utf-8")
        return {
            "raw_root": raw_root,
            "asset_manifest": asset_manifest,
            "asset_root": asset_root,
            "system_manifest": system_manifest,
            "entity_index": entity_index,
            "category_mapping": category_mapping,
            "content_tree": content_tree,
            "structured": structured,
        }

    def run_build(self, root: Path, with_structured: bool):
        paths = self.make_inputs(root, with_structured)
        output = root / "local_wiki/ss13/site"
        self.assertFalse(output.exists())
        report = build(
            "ss13", paths["raw_root"], paths["asset_manifest"], paths["asset_root"],
            output,
            system_manifest_path=paths["system_manifest"],
            supplemental_manifest_path=root / "missing-supplemental.json",
            game_category_mapping_path=paths["category_mapping"],
            entity_index_path=paths["entity_index"],
            game_content_tree_path=paths["content_tree"],
            structured_search_index_path=paths["structured"],
            search_entity_report_path=root / "reports/entity.json",
            content_tree_report_path=root / "reports/tree.json",
            search_entity_v2_report_path=root / "reports/entity-v2.json",
        )
        return output, report

    def test_empty_site_bootstraps_catalog_search_runtime_and_structured_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            output, report = self.run_build(Path(temporary), with_structured=True)
            self.assertEqual([], report["errors"])
            self.assertTrue(output.is_dir())
            catalog = json.loads((output / "catalog.json").read_text(encoding="utf-8"))
            search = json.loads((output / "search-index.json").read_text(encoding="utf-8"))
            self.assertEqual(1, catalog["page_count"])
            self.assertEqual(8, search["schema_version"])
            self.assertEqual("skill", search["pages"][0]["content_category_id"])
            self.assertTrue((output / "cn/Test_Skill/index.html").is_file())
            self.assertTrue((output / "structured-search-index.json").is_file())
            self.assertEqual(
                "skill:test",
                json.loads((output / "structured-search-index.json").read_text())["records"][0]["record_id"],
            )
            self.assert_runtime_contract(output)

    def test_missing_structured_index_keeps_v1_search_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            output, report = self.run_build(Path(temporary), with_structured=False)
            self.assertEqual([], report["errors"])
            self.assertFalse((output / "structured-search-index.json").exists())
            self.assertTrue((output / "search-index.json").is_file())
            self.assertTrue(any("v1 search fallback" in warning for warning in report["warnings"]))
            self.assert_runtime_contract(output)

    def test_existing_site_catalog_and_search_remain_optional_incremental_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = self.make_inputs(root, with_structured=False)
            output = root / "local_wiki/ss13/site"
            output.mkdir(parents=True)
            (output / "catalog.json").write_text(json.dumps({
                "pages": [{
                    "system_id": "active_skill", "system_name_zh": "主动技能",
                    "source_type": "official_system", "id": "Test_Skill",
                    "slug": "Test_Skill", "title": "测试技能",
                    "source_url": "https://tlidb.com/cn/Test_Skill",
                }],
            }), encoding="utf-8")
            (output / "search-index.json").write_text(json.dumps({
                "schema_version": 8,
                "pages": [{
                    "system_id": "active_skill", "id": "Test_Skill",
                    "title": "兼容标题", "plain_text": "旧技能文本",
                }],
            }), encoding="utf-8")
            report = build(
                "ss13", paths["raw_root"], paths["asset_manifest"], paths["asset_root"],
                output,
                game_category_mapping_path=paths["category_mapping"],
                entity_index_path=paths["entity_index"],
                game_content_tree_path=paths["content_tree"],
                structured_search_index_path=paths["structured"],
            )
            self.assertEqual([], report["errors"])
            search = json.loads((output / "search-index.json").read_text(encoding="utf-8"))
            self.assertEqual("兼容标题", search["pages"][0]["title"])
            self.assertIn("当前技能正文", search["pages"][0]["plain_text"])

    def assert_runtime_contract(self, output: Path):
        search_js = (output / "_local/search/app.js").read_text(encoding="utf-8")
        mirror_js = (output / "_local/mirror.js").read_text(encoding="utf-8")
        self.assertEqual(local_assets()["_local/search/app.js"], search_js)
        self.assertEqual(local_assets()["_local/mirror.js"], mirror_js)
        for token in (
            "structured_record", "structured_tier", "structured_state",
            "structured_skill_pane", "isLegacyInventoryFallback", "isLegacyDivinitySlate",
        ):
            self.assertIn(token, search_js)
        for token in (
            "structured_record", "structured_tier", "structured_skill_pane",
            "data-modifier-id", "skillHoverPrefix", "loadLocalSkillPopup",
        ):
            self.assertIn(token, mirror_js)


if __name__ == "__main__":
    unittest.main()
