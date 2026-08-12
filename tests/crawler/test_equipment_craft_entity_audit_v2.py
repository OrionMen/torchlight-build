import json
import tempfile
import unittest
from pathlib import Path

from crawler.audit_equipment_craft_entities_v2 import audit_entities, build_audit


ROOT = Path(__file__).resolve().parents[2]


class EquipmentCraftEntityAuditV2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = build_audit(ROOT)

    def test_inventory_entity_count_and_unique_ids(self):
        self.assertEqual(38, self.report["summary"]["inventory_entities"])
        ids = [item["entity_id"] for item in self.report["entities"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_all_inventory_entities_have_embedded_craft_association(self):
        self.assertEqual(38, self.report["summary"]["matched_craft_entities"])
        self.assertEqual(0, self.report["summary"]["standalone_craft_manifest_matches"])
        self.assertTrue(all(item["craft_sources"] for item in self.report["entities"]))
        self.assertTrue(all(
            source["association"] == "same_canonical_page_dom_section"
            for item in self.report["entities"] for source in item["craft_sources"]
        ))

    def test_base_and_craft_affixes_exist(self):
        self.assertTrue(all(item["base_affixes"] for item in self.report["entities"]))
        self.assertTrue(all(item["craft_affixes"] for item in self.report["entities"]))

    def test_spirit_ring_is_present_after_entity_v2(self):
        missing = {item["id"]: item["reason"] for item in self.report["missing_inventory_entities"]}
        self.assertNotIn("Spirit_Ring", missing)
        self.assertEqual(38, self.report["summary"]["current_equipment_entity_v1"])

    def test_unmatched_craft_data_is_recorded(self):
        with tempfile.TemporaryDirectory() as temporary:
            raw_root = Path(temporary)
            raw_root.joinpath("Example.html").write_text(
                '<div id="示例基础词缀" class="tab-pane"><table><tr><td>基础</td></tr></table></div>',
                encoding="utf-8",
            )
            report = audit_entities(
                {"Example": {"id": "Example", "url": "https://tlidb.com/cn/Example"}},
                set(),
                {"tlidb:cn:Example": {"entity_title_zh": "示例", "entity_type": "equipment"}},
                raw_root,
                ("Example",),
            )
            self.assertEqual(1, report["summary"]["unmatched"])
            self.assertEqual("craft_section_missing", report["unmatched_craft_data"][0]["reason"])

    def test_report_is_json_serializable(self):
        json.dumps(self.report, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
