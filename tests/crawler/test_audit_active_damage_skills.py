import json
import tempfile
import unittest
from pathlib import Path

from crawler.audit_active_damage_skills import audit, inspect_html


def page(attribute="力量", levels=(1, 20, 40), growth=True):
    rows = "".join(f"<tr><td>{level}</td><td>ignored</td></tr>" for level in levels)
    table = ""
    if growth:
        table = f"""
        <div class="card"><h5 class="card-header">成长 /40</h5>
          <table><thead><tr><th>level</th><th>damage</th></tr></thead><tbody>{rows}</tbody></table>
        </div>"""
    return f"""
    <html><div class="card ui_item popupItem">
      <h5 class="card-title">测试技能</h5>
      <div class="d-flex"><div>主属性：</div><div class="ps-2">{attribute}</div></div>
      <div>Simple</div><div>Details Lv20 Unlock 20</div>
    </div>{table}</html>
    """


class ActiveDamageSkillAuditTest(unittest.TestCase):
    def test_real_dom_evidence_detects_tags_table_and_level20(self):
        detected = inspect_html(page("力量, 智慧"))
        self.assertEqual(detected["primary_attribute_tags"], ["力量", "智慧"])
        self.assertTrue(detected["has_explicit_level_table"])
        self.assertEqual((detected["detected_level_min"], detected["detected_level_max"]), (1, 40))
        self.assertTrue(detected["has_level_20"])
        self.assertEqual(detected["level_table_row_count"], 3)

    def test_simple_details_and_unlock_are_not_level_table(self):
        detected = inspect_html(page(growth=False))
        self.assertEqual(detected["primary_attribute_tags"], ["力量"])
        self.assertFalse(detected["has_explicit_level_table"])
        self.assertFalse(detected["has_level_20"])

    def test_audit_is_stable_and_continues_after_missing_html(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            raw.mkdir()
            (raw / "Missing20.html").write_text(page("敏捷", (1, 10, 40)), encoding="utf-8")
            (raw / "Rejected.html").write_text(page("智慧", growth=False), encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"entries": [
                {"id": "Missing20", "slug": "Missing20", "name_zh": "缺二十", "url": "u1"},
                {"id": "Rejected", "slug": "Rejected", "name_zh": "拒绝", "url": "u2"},
                {"id": "Absent", "slug": "Absent", "name_zh": "缺页", "url": "u3"},
            ]}, ensure_ascii=False), encoding="utf-8")
            first = audit(manifest, raw)
            second = audit(manifest, raw)
            self.assertEqual(first, second)
            self.assertEqual(first["primary_attribute_skill_count"], 2)
            self.assertEqual(first["eligible_skill_count"], 1)
            self.assertEqual(first["eligible_missing_level20_count"], 1)
            self.assertEqual(len(first["rejected_primary_attribute_without_level_table"]), 1)
            self.assertEqual(len(first["errors"]), 1)


if __name__ == "__main__":
    unittest.main()
