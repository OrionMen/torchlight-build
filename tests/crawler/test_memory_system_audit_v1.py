import re
import unittest
from pathlib import Path

from crawler.audit_memory_system_v1 import build_report


ROOT = Path(__file__).resolve().parents[2]


class MemorySystemAuditV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = build_report(ROOT)

    def test_all_affix_regions_are_detected(self):
        hero = self.report["hero_memory"]
        revival = self.report["revival"]
        for section in (
            hero["base_attributes"], hero["fixed_affixes"], hero["random_affixes"],
            revival["normal_affixes"], revival["moon_affixes"],
        ):
            self.assertTrue(section["detected"])
            self.assertGreater(section["row_count"], 0)

    def test_audit_uses_dedicated_rows_without_ui_metadata(self):
        sections = [
            self.report["hero_memory"]["base_attributes"],
            self.report["hero_memory"]["fixed_affixes"],
            self.report["hero_memory"]["random_affixes"],
            self.report["revival"]["normal_affixes"],
            self.report["revival"]["moon_affixes"],
        ]
        examples = " ".join(text for section in sections for text in section["examples"])
        self.assertFalse(re.search(r"data-modifier-id|\.webp|Tier:|Weight:|<script", examples, re.I))
        self.assertGreater(self.report["hero_memory"]["noise_evidence"]["item_tabs"], 0)
        self.assertGreater(
            self.report["hero_memory"]["noise_evidence"]["internal_modifier_id_attributes"], 0
        )

    def test_revival_is_supplemental_not_independent_entity(self):
        self.assertTrue(self.report["hero_memory"]["entity_candidate"])
        self.assertFalse(self.report["revival"]["independent_entity"])
        self.assertEqual("hero_memory_affix_source", self.report["revival"]["recommended_role"])
        self.assertIn("do not create a separate Revival entity", self.report["recommendation"])


if __name__ == "__main__":
    unittest.main()
