import json
import tempfile
import unittest
from pathlib import Path

from crawler.build_full_wiki_mirror import build
from crawler.generate_entity_index_v3 import (
    build_entity_index_v3,
    equipment_related_system_entity_v1_report,
)


ROOT = Path(__file__).resolve().parents[2]


class EquipmentRelatedSystemEntityV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index, _ = build_entity_index_v3(ROOT)
        cls.by_id = {entity["entity_id"]: entity for entity in cls.index["entities"]}
        cls.report = equipment_related_system_entity_v1_report(cls.index)

    def test_fragrance_is_searchable_system_entity(self):
        entity = self.by_id["tlidb:cn:Blending_Rituals"]
        self.assertEqual("调香秘仪", entity["entity_title_zh"])
        self.assertEqual("equipment_related_system", entity["entity_type"])
        self.assertEqual("装备相关", entity["content_category_name_zh"])
        self.assertEqual("调香秘仪", entity["content_subcategory_name_zh"])
        self.assertEqual(97, entity["record_count"])
        self.assertIn("攻击技能等级", entity["clean_summary"])
        self.assertIn("中型天赋", entity["clean_summary"])
        self.assertIn("核心天赋", entity["clean_summary"])
        self.assertIn("异香天赋", entity["clean_summary"])
        self.assertNotRegex(entity["clean_summary"], r"鼠尾草Lv\.1\s*x\d+")

    def test_tower_is_searchable_system_entity(self):
        entity = self.by_id["tlidb:cn:TOWER_Sequence"]
        self.assertEqual("高塔序列", entity["entity_title_zh"])
        self.assertEqual("equipment_related_system", entity["entity_type"])
        self.assertEqual("装备相关", entity["content_category_name_zh"])
        self.assertEqual("高塔序列", entity["content_subcategory_name_zh"])
        self.assertEqual(408, entity["record_count"])
        self.assertIn("主手武器", entity["clean_summary"])
        self.assertIn("序列", entity["clean_summary"])
        self.assertNotRegex(entity["clean_summary"], r"\b\d+\|\d+\|\d+\b")

    def test_no_equipment_entity_is_created_for_systems(self):
        for entity_id in ("tlidb:cn:Blending_Rituals", "tlidb:cn:TOWER_Sequence"):
            entity = self.by_id[entity_id]
            self.assertNotEqual("equipment", entity["content_category_id"])
            self.assertNotEqual("equipment", entity["entity_type"])
        self.assertEqual(0, self.report["equipment_entities_created"])
        self.assertTrue(self.report["fragrance"]["entity_created"])
        self.assertTrue(self.report["tower_sequence"]["entity_created"])

    def test_builder_indexes_clean_summary_under_non_hidden_system_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_root = root / "raw"
            raw = raw_root / "help/raw_html"
            raw.mkdir(parents=True)
            raw.joinpath("Blending_Rituals.html").write_text(
                "<title>调香秘仪</title><main>页面导航和材料列表</main>",
                encoding="utf-8",
            )
            asset_manifest = root / "assets.json"
            asset_manifest.write_text('{"assets": []}', encoding="utf-8")
            catalog = root / "catalog.json"
            catalog.write_text(json.dumps({"pages": [{
                "system_id": "help",
                "system_name_zh": "帮助手册",
                "id": "Blending_Rituals",
                "slug": "Blending_Rituals",
                "title": "调香秘仪",
                "source_url": "https://tlidb.com/cn/Blending_Rituals",
            }]}), encoding="utf-8")
            old_search = root / "search.json"
            old_search.write_text('{"pages": []}', encoding="utf-8")
            entity_index = root / "entities.json"
            entity_index.write_text(json.dumps({"entities": [{
                "entity_id": "tlidb:cn:Blending_Rituals",
                "canonical_route": "/cn/Blending_Rituals/",
                "entity_title_zh": "调香秘仪",
                "entity_visibility": "visible",
                "entity_type": "equipment_related_system",
                "clean_summary": "调香秘仪 +1 攻击技能等级 核心天赋",
                "content_category_id": "equipment_related",
                "content_category_name_zh": "装备相关",
                "content_subcategory_id": "equipment_related_fragrance",
                "content_subcategory_name_zh": "调香秘仪",
                "search_system_id": "equipment_related_fragrance",
                "sources": [{"source_type": "help", "role": "fragrance_affix_system"}],
            }]}), encoding="utf-8")
            output = root / "site"
            build(
                "ss13", raw_root, asset_manifest, root / "asset-files", output,
                catalog_path=catalog,
                search_index_path=old_search,
                entity_index_path=entity_index,
            )
            page = json.loads(
                output.joinpath("search-index.json").read_text(encoding="utf-8")
            )["pages"][0]
            self.assertEqual("equipment_related_fragrance", page["system_id"])
            self.assertEqual("装备相关", page["system_name_zh"])
            self.assertEqual("equipment_related", page["content_category_id"])
            self.assertEqual("equipment_related_fragrance", page["content_subcategory_id"])
            self.assertIn("攻击技能等级", page["plain_text"])
            self.assertNotIn("材料列表", page["plain_text"])


if __name__ == "__main__":
    unittest.main()
