from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crawler.audit_equipment_related_structured_dom_v1 import build_report, inspect_html


REPO = Path(__file__).resolve().parents[2]


class EquipmentRelatedStructuredDomAuditV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = build_report(REPO)

    def test_source_and_entity_models_are_complete(self) -> None:
        self.assertTrue(all(item["raw_nonempty"] for item in self.report["source_completeness"].values()))
        for entity in self.report["entity_model"].values():
            self.assertTrue(entity["present"])
            self.assertEqual("equipment_related_system", entity["entity_type"])
            self.assertEqual("equipment_related", entity["category"])

    def test_fragrance_records_have_stable_keys_recipe_ids_and_types(self) -> None:
        structure = self.report["fragrance_structure"]
        self.assertEqual(97, structure["record_count"])
        self.assertEqual(97, structure["modifier_key_count"])
        self.assertEqual(97, structure["recipe_id_count"])
        self.assertEqual({"中型天赋": 36, "核心天赋": 55, "异香天赋": 6}, structure["talent_type_distribution"])
        self.assertEqual(1.0, self.report["stable_identity"]["fragrance"]["coverage"])

    def test_tower_rows_and_duplicate_context(self) -> None:
        structure = self.report["tower_structure"]
        self.assertEqual(408, structure["record_count"])
        self.assertEqual(["Affix", "来源"], structure["headers"])
        self.assertEqual({"中阶序列": 220, "高阶序列": 188}, structure["sequence_tier_distribution"])
        self.assertEqual(0, self.report["stable_identity"]["tower"]["duplicate_stable_keys"])
        self.assertGreater(self.report["duplicate_analysis"]["tower_effect_text"]["group_count"], 0)
        self.assertEqual(1.0, self.report["stable_identity"]["tower"]["coverage"])

    def test_datatable_and_filter_view_state_are_explicit(self) -> None:
        self.assertTrue(self.report["view_state"]["fragrance"]["filter_control"])
        self.assertTrue(self.report["tower_structure"]["datatable_present"])
        self.assertFalse(self.report["tower_structure"]["datatable_config"]["paging"])
        self.assertFalse(self.report["view_state"]["tower"]["pagination_api_required"])
        self.assertEqual(505, self.report["locator_support"]["record_level"])

    def test_framework_contract_and_noise_whitelists(self) -> None:
        self.assertTrue(self.report["framework_compatibility"]["compatible"])
        self.assertFalse(self.report["framework_compatibility"]["generic_extension_required"])
        self.assertIn("fragrance_affix", {item["record_type"] for item in self.report["candidate_record_types"]})
        self.assertIn("tower_sequence_affix", {item["record_type"] for item in self.report["candidate_record_types"]})
        self.assertEqual([], self.report["errors"])

    def test_inspector_ignores_help_and_cache_tabs(self) -> None:
        parsed = inspect_html('''
          <button class="active" data-bs-target="#调香秘仪">调香秘仪</button>
          <div id="调香秘仪" class="tab-pane fade show active">
            <input name="filter"><div class="col">
              <span data-modifier-id="m1">效果甲<br/>效果乙</span>
              <div>核心天赋 Lv.0</div><a href="Mat">材料</a> x3<span data-id="r1"></span>
            </div>
          </div>
          <div id="调香秘仪-帮助手册"><span data-modifier-id="bad">噪声</span></div>
          <button class="active" data-bs-target="#高塔序列">高塔序列</button>
          <div id="高塔序列" class="tab-pane fade show active"><table class="DataTable">
            <thead><tr><th>Affix</th><th>来源</th></tr></thead><tbody>
              <tr><td><span data-modifier-id="t1">效果</span><div data-chip="1|2|6">中阶序列 1|2|6</div></td><td>弓</td></tr>
            </tbody></table></div>
          <div id="高塔序列_cache"><span data-modifier-id="bad2">噪声</span></div>
        ''')
        self.assertEqual(["m1"], parsed["fragrance_records"][0]["modifier_ids"])
        self.assertEqual("核心天赋", parsed["fragrance_records"][0]["talent_type"])
        self.assertEqual(3, parsed["fragrance_records"][0]["materials"][0]["quantity"])
        self.assertEqual(["t1"], parsed["tower_records"][0]["modifier_ids"])
        self.assertEqual("弓", parsed["tower_records"][0]["equipment_type"])

    def test_report_is_json_serializable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps(self.report, ensure_ascii=False), encoding="utf-8")
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(1, loaded["schema_version"])


if __name__ == "__main__":
    unittest.main()
