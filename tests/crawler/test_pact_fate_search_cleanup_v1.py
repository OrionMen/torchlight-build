import json
import unittest
from pathlib import Path

from crawler.build_full_wiki_mirror import ENTITY_CLEAN_SUMMARY_TYPES


ROOT = Path(__file__).resolve().parents[2]


class PactFateSearchCleanupV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = json.loads(
            (ROOT / "data/generated/entity-index-v3.json").read_text(encoding="utf-8")
        )
        cls.pact = [e for e in data["entities"] if e.get("entity_type") == "pact_spirit"]
        cls.fate = [e for e in data["entities"] if e.get("entity_type") == "fate"]
        cls.by_id = {e["entity_id"]: e for e in cls.pact + cls.fate}

    def test_entity_counts_are_unchanged(self):
        self.assertEqual(175, len(self.pact))
        self.assertEqual(191, len(self.fate))

    def test_search_plain_text_uses_clean_summary_for_both_types(self):
        self.assertIn("pact_spirit", ENTITY_CLEAN_SUMMARY_TYPES)
        self.assertIn("fate", ENTITY_CLEAN_SUMMARY_TYPES)

    def test_pact_summary_excludes_table_and_ui_noise(self):
        for entity in self.pact:
            summary = entity["clean_summary"]
            self.assertNotIn("lv name", summary.casefold())
            self.assertNotIn("update cookie preferences", summary.casefold())

    def test_fate_summary_excludes_internal_and_history_noise(self):
        for entity in self.fate:
            summary = entity["clean_summary"]
            self.assertNotIn("info id", summary.casefold())
            self.assertNotIn("show description", summary.casefold())
            self.assertNotIn("SS12赛季", summary)

    def test_pact_core_effect_is_preserved(self):
        summary = self.by_id["tlidb:cn:Red_Umbrella"]["clean_summary"]
        for expected in ("赤伞", "增加攻击伤害", "狂暴", "瘫痪"):
            self.assertIn(expected, summary)

    def test_fate_core_effect_is_preserved(self):
        summary = self.by_id["tlidb:cn:Micro_Fate:_Fire_Resistance"]["clean_summary"]
        for expected in ("小型宿命：火焰抗性", "火焰抗性", "安装后替换一个小型天赋点"):
            self.assertIn(expected, summary)


if __name__ == "__main__":
    unittest.main()
