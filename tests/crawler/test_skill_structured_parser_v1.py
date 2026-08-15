from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from crawler.build_full_wiki_mirror import local_assets
from crawler.structured.parser_base import ParserInput
from crawler.structured.parsers.skill_parser import SkillParser
from crawler.structured.schema import make_record_id


ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "data/generated/structured/ss13/structured-search-index.json"
REPORT = ROOT / "data/reports/local-wiki/skill-structured-parser-v1-report.json"
RAW_ROOT = ROOT / "data/raw/manifests"


class SkillStructuredParserV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = json.loads(INDEX.read_text(encoding="utf-8"))
        cls.report = json.loads(REPORT.read_text(encoding="utf-8"))
        cls.records = [
            record for record in cls.index["records"]
            if record.get("record_type") in {"skill_effect", "skill_growth_modifier"}
        ]
        cls.effects = [record for record in cls.records if record["record_type"] == "skill_effect"]
        cls.growth = [
            record for record in cls.records if record["record_type"] == "skill_growth_modifier"
        ]
        assets = local_assets()
        cls.search_js = assets["_local/search/app.js"]
        cls.landing_js = assets["_local/mirror.js"]

    def test_all_entities_templates_and_records_are_emitted(self) -> None:
        self.assertEqual(721, self.report["skill_entities"])
        self.assertEqual(721, self.report["structure_matched"])
        self.assertEqual(0, self.report["structure_mismatches"])
        self.assertEqual(721, len(self.effects))
        self.assertEqual(1164, len(self.growth))
        self.assertEqual(1885, len(self.records))
        self.assertEqual({
            "skill_modifier_growth": 321,
            "skill_standalone_card": 244,
            "skill_tabbed_cache_history": 83,
            "skill_tabbed_variants": 73,
        }, self.report["template_groups"])

    def test_seven_classifications_are_inherited_from_entities(self) -> None:
        expected = {
            "skill_active": 204,
            "skill_support": 122,
            "skill_passive": 55,
            "skill_activation_medium": 28,
            "skill_magnificent_support": 140,
            "skill_noble_support": 154,
            "skill_modularization": 18,
        }
        self.assertEqual(expected, self.report["subcategory_counts"])
        self.assertTrue(all(record["content_category_id"] == "skill" for record in self.records))
        self.assertEqual(set(expected), {record["content_subcategory_id"] for record in self.records})
        self.assertEqual(0, self.report["classification_errors"])

    def test_native_identity_is_high_confidence_unique_and_stable(self) -> None:
        identity = self.report["identity"]
        self.assertEqual({"records": 721, "with_id": 721, "unique": 721}, identity["skill_id_coverage"])
        modifier = identity["modifier_id_coverage"]
        self.assertEqual(1164, modifier["with_id"])
        self.assertEqual(1164, modifier["unique_stable_identity_keys"])
        self.assertGreater(modifier["tier_disambiguated_occurrences"], 0)
        self.assertEqual(1885, identity["high_confidence"])
        self.assertEqual(0, identity["unresolved"])
        self.assertEqual(1885, len({record["record_id"] for record in self.records}))

        effect = self.effects[0]
        self.assertEqual(effect["record_id"], make_record_id(
            parser_id=SkillParser.parser_id,
            entity_id=effect["entity_id"],
            record_type="skill_effect",
            section_key="skill_effect",
            stable_key=effect["source_locator"]["stable_key"],
        ))
        growth = self.growth[0]
        self.assertEqual(growth["record_id"], make_record_id(
            parser_id=SkillParser.parser_id,
            entity_id=growth["entity_id"],
            record_type="skill_growth_modifier",
            section_key="skill_growth",
            stable_key=growth["source_locator"]["stable_key"],
        ))

    def test_numeric_text_change_does_not_change_record_identity(self) -> None:
        source = RAW_ROOT / "activation_medium_skill/raw_html/Activation_Medium%3A_Perpetual_Motion.html"
        original = source.read_text(encoding="utf-8")
        changed = original.replace("-25", "-24", 1)
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.html"
            second = Path(directory) / "second.html"
            first.write_text(original, encoding="utf-8")
            second.write_text(changed, encoding="utf-8")
            parser_input = lambda path: ParserInput(
                "ss13", "activation_medium_skill", "Activation_Medium:_Perpetual_Motion",
                "/cn/Activation_Medium:_Perpetual_Motion/", path,
            )
            before = SkillParser().parse(parser_input(first))
            after = SkillParser().parse(parser_input(second))
        self.assertEqual(
            [record["record_id"] for record in before["records"]],
            [record["record_id"] for record in after["records"]],
        )

    def test_level_rows_and_historical_content_never_become_records(self) -> None:
        level = self.report["level_model"]
        self.assertEqual(264, level["pages_with_level_table"])
        self.assertEqual(10560, level["level_rows"])
        self.assertEqual(0, level["records_emitted_from_level_rows"])
        history = self.report["historical_exclusion"]
        self.assertEqual(0, history["historical_records"])
        self.assertEqual(0, history["inactive_records"])
        self.assertEqual(0, history["cache_records"])

    def test_search_text_is_whitelisted_and_noise_free(self) -> None:
        noise = self.report["noise_validation"]
        self.assertEqual(0, noise["violating_records"])
        self.assertTrue(all(count == 0 for count in noise["forbidden_search_text"].values()))
        self.assertEqual(0, noise["level_row_records"])
        self.assertEqual(0, noise["whole_page_plain_text_records"])
        self.assertTrue(all(record["search_text"] for record in self.records))

    def test_locators_are_honest_and_scoped(self) -> None:
        self.assertTrue(all(
            record["source_locator"]["locator_level"] == "section" for record in self.effects
        ))
        self.assertTrue(all(
            record["source_locator"]["locator_level"] == "record" for record in self.growth
        ))
        self.assertTrue(all(
            record["source_locator"]["view_state"].get("skill_effect") for record in self.effects
        ))
        self.assertTrue(all(
            record["source_locator"]["view_state"].get("skill_growth") for record in self.growth
        ))
        self.assertTrue(all(record["landing"]["route"] == record["route"] for record in self.records))

    def test_existing_structured_records_and_v1_schema_are_preserved(self) -> None:
        merge = self.report["structured_search"]
        self.assertEqual(26895, merge["previous_total"])
        self.assertEqual(1885, merge["added"])
        self.assertEqual(28780, merge["new_total"])
        self.assertEqual(26895, merge["existing_record_ids_preserved"])
        self.assertEqual(28780, self.index["record_count"])
        v1 = json.loads((ROOT / "local_wiki/ss13/site/search-index.json").read_text(encoding="utf-8"))
        self.assertEqual(8, v1["schema_version"])

    def test_structured_match_suppresses_page_result_but_fallback_remains(self) -> None:
        self.assertIn("structuredEntities.has(hit.x.entity_id)", self.search_js)
        self.assertIn("!structuredRoutes.has(normalizeRoute(hit.x.route))", self.search_js)
        self.assertTrue(self.report["page_suppression"]["structured_match_suppresses_v1"])
        self.assertTrue(self.report["page_suppression"]["v1_fallback_without_structured_match"])
        self.assertIn("技能效果", {record["section_name"] for record in self.records})
        self.assertIn("成长词缀", {record["section_name"] for record in self.records})

    def test_search_and_landing_runtime_contract(self) -> None:
        params = (
            "structured_skill_pane", "structured_skill_effect", "structured_skill_growth",
            "structured_skill_modifier", "structured_skill_modifier_tier",
        )
        for token in params:
            self.assertIn(token, self.search_js)
            self.assertIn(token, self.landing_js)
        for token in (
            ".card.ui_item.popupItem:not(.previousItem)",
            "root.querySelectorAll('[data-modifier-id]')",
            "node.closest('.previousItem')",
            ".tab-pane:not(.active):not(.show)",
            "node.getAttribute('data-modifier-id')===skillModifier",
            "trigger.addEventListener('shown.bs.tab'",
            "tableRoot=pane||currentRoot()",
            "filter.value=''",
            "scrollIntoView",
            "row.style.backgroundColor='#fef08a'",
            "landing=target||root",
        ):
            self.assertIn(token, self.landing_js)

    def test_structure_mismatch_emits_no_partial_records(self) -> None:
        source = RAW_ROOT / "active_skill/raw_html/Vendetta.html"
        html = source.read_text(encoding="utf-8")
        broken = re.sub(r"(<div>id:)\s*[^<]+", r"\1", html, count=1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.html"
            path.write_text(broken, encoding="utf-8")
            result = SkillParser().parse(ParserInput(
                "ss13", "active_skill", "Vendetta", "/cn/Vendetta/", path,
            ))
        self.assertEqual("structure_mismatch", result["structure_validation"]["status"])
        self.assertEqual([], result["records"])

    def test_case_studies_cover_simple_complex_growth_history_and_filter(self) -> None:
        cases = self.report["case_studies"]
        for slug in (
            "Vendetta", "Serpent_Beam", "Leap_Attack", "Fearless", "Multiple_Projectiles",
            "Activation_Medium:_Perpetual_Motion", "Module:_Goblin_Priest",
            "filter_page", "tabbed_variant",
        ):
            self.assertIn(slug, cases)
            self.assertEqual(1, cases[slug]["skill_effect"])
            self.assertEqual(0, cases[slug]["historical_records"])
        self.assertEqual(12, cases["Activation_Medium:_Perpetual_Motion"]["skill_growth_modifier"])


if __name__ == "__main__":
    unittest.main()
