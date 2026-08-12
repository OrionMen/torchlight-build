import unittest
from pathlib import Path

from crawler.audit_fragrance_tower_equipment_v1 import (
    build_audit,
    inspect_system_html,
)


ROOT = Path(__file__).resolve().parents[2]


class FragranceTowerEquipmentAuditV1Test(unittest.TestCase):
    def test_fragrance_rows_and_materials_are_not_equipment_entities(self):
        evidence = inspect_system_html(
            '''
            <div id="调香秘仪" class="tab-pane active">
              <div class="col"><span data-modifier-id="m1">效果甲</span>
                <a href="Sage_Lv._1">鼠尾草Lv.1</a><span data-id="r1"></span>
              </div>
              <div class="col"><span data-modifier-id="m2">效果乙</span>
                <a href="Silver_Mound_Lv._2">苦艾草Lv.2</a><span data-id="r2"></span>
              </div>
            </div>
            ''',
            "调香秘仪",
            "div",
        )
        self.assertTrue(evidence["section_found"])
        self.assertEqual(2, evidence["record_count"])
        self.assertEqual(0, evidence["current_item_card_count"])
        self.assertEqual(
            ["Sage_Lv._1", "Silver_Mound_Lv._2"],
            [item["slug"] for item in evidence["material_links"]],
        )

    def test_tower_rows_are_modifier_data_not_entity_pages(self):
        evidence = inspect_system_html(
            '''
            <div id="高塔序列" class="tab-pane active"><table>
              <tr><td><span data-modifier-id="t1">额外伤害</span></td>
                  <td><div data-chip="1|2|6">爪</div></td></tr>
              <tr><td><span data-modifier-id="t2">护甲穿透</span></td></tr>
            </table></div>
            ''',
            "高塔序列",
            "tr",
        )
        self.assertTrue(evidence["section_found"])
        self.assertEqual(2, evidence["record_count"])
        self.assertEqual(0, evidence["canonical_record_page_count"])
        self.assertEqual(0, evidence["current_item_card_count"])

    def test_real_audit_excludes_categories_and_has_search_recommendation(self):
        report = build_audit(ROOT)
        fragrance = report["fragrance_ritual"]
        tower = report["tower_sequence"]
        self.assertEqual(97, fragrance["embedded_recipe_count"])
        self.assertEqual(9, len(fragrance["material_pages"]))
        self.assertEqual(0, fragrance["entity_count"])
        self.assertEqual(408, tower["embedded_sequence_count"])
        self.assertEqual(0, tower["entity_count"])
        self.assertTrue(all(
            page["classification"] == "category_page"
            for page in fragrance["category_pages"] + tower["category_pages"]
        ))
        recommendation = report["search_recommendation"]
        self.assertIn(
            "装备名称",
            recommendation["include_for_future_confirmed_equipment_entities"],
        )
        self.assertIn("材料列表", recommendation["exclude"])


if __name__ == "__main__":
    unittest.main()
