from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from crawler.build_full_wiki_mirror import local_assets


ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "local_wiki/ss13/site"


class SkillPopupLocalRuntimeV2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = local_assets()["_local/mirror.js"]
        cls.deployed_runtime = (SITE / "_local/mirror.js").read_text(encoding="utf-8")
        cls.active_html = (SITE / "cn/Active_Skill/index.html").read_text(encoding="utf-8")
        cls.detail_html = (SITE / "cn/Summon_Fire_Magus/index.html").read_text(
            encoding="utf-8"
        )

    def test_contract_is_structural_instead_of_route_registry(self) -> None:
        for token in (
            "skillHoverPrefix='/cache/cn/Torchlight_ItemBase_hover/'",
            "document.querySelectorAll('a[href][data-hover]')",
            "currentPageIsSkill",
            "isCategorySkillReference",
            "isDetailSkillReference",
            "item.querySelector('[data-skilltagid]')",
            "isSkillReference(reference)",
        ):
            self.assertIn(token, self.runtime)
        self.assertNotIn("skillCatalogs", self.runtime)
        self.assertNotIn("jQuery.ajax=function", self.runtime)

    def test_local_resolution_uses_rewritten_href_and_same_origin(self) -> None:
        for token in (
            "reference.getAttribute('href')",
            "new URL(reference.getAttribute('href'),location.href)",
            "localUrl.origin!==location.origin",
            "fetch(localUrl.href,{credentials:'same-origin'})",
        ):
            self.assertIn(token, self.runtime)
        self.assertNotIn("tlidb.com", self.runtime.split("const params=", 1)[0])

    def test_payload_is_current_skill_card_not_historical_card(self) -> None:
        self.assertIn(".card.ui_item.popupItem:not(.previousItem)", self.runtime)
        self.assertIn("pane.classList.contains('active')", self.runtime)
        self.assertIn("hasSkillCardContract(card)", self.runtime)
        target = (SITE / "cn/Blazing_Spin/index.html").read_text(encoding="utf-8")
        self.assertIn('class="card ui_item popupItem"', target)
        self.assertIn('class="card ui_item popupItem previousItem"', target)

    def test_category_detail_history_and_alts_share_the_contract(self) -> None:
        category = re.search(
            r'<a data-hover="(/cache/cn/Torchlight_ItemBase_hover/[^"]+)" '
            r'href="(/local_wiki/ss13/site/cn/Rocket_Jump/)">火箭跳</a>',
            self.active_html,
        )
        current = re.search(
            r'<a data-hover="(/cache/cn/Torchlight_ItemBase_hover/[^"]+)" '
            r'href="(/local_wiki/ss13/site/cn/Blazing_Dance/)">烈焰挥舞</a>',
            self.detail_html,
        )
        previous = re.search(
            r'previousItem.*?<a data-hover="(/cache/cn/Torchlight_ItemBase_hover/[^"]+)" '
            r'href="(/local_wiki/ss13/site/cn/Blazing_Spin/)">烈焰飞旋</a>',
            self.detail_html,
            re.S,
        )
        alt = re.search(
            r'<div class="card-header">Alts</div>.*?<a data-hover="'
            r'(/cache/cn/Torchlight_ItemBase_hover/[^"]+)" href="'
            r'(/local_wiki/ss13/site/cn/Summon_Fire_Magus:_Fire_Ward_\(Magnificent\)/)">',
            self.detail_html,
            re.S,
        )
        for match in (category, current, previous, alt):
            self.assertIsNotNone(match)

    def test_future_season_contract_has_no_known_page_or_season_registry(self) -> None:
        synthetic_reference = (
            '<a data-hover="/cache/cn/Torchlight_ItemBase_hover/future-hash" '
            'href="/local_wiki/ss14/site/cn/Future_Season_Skill/">未来技能</a>'
        )
        synthetic_target = (
            '<div class="card ui_item popupItem"><span class="tag">法术</span>'
            '<div data-src="detailMods">未来效果</div></div>'
            '<div class="card ui_item popupItem previousItem">历史效果</div>'
        )
        self.assertIn("data-hover=", synthetic_reference)
        self.assertIn("/cache/cn/Torchlight_ItemBase_hover/", synthetic_reference)
        self.assertIn('class="card ui_item popupItem"', synthetic_target)
        popup_contract = self.runtime.split("const params=", 1)[0]
        for forbidden in ("Future_Season_Skill", "ss13", "ss14", "Active_Skill"):
            self.assertNotIn(forbidden, popup_contract)

    def test_failures_are_graceful_and_unrelated_hover_is_untouched(self) -> None:
        for token in (
            "skillPopupFallback='无本地预览'",
            "if(!response.ok)throw new Error",
            ".catch(()=>null)",
            "payload||skillPopupFallback",
            "if(!isSkillReference(reference))return",
        ):
            self.assertIn(token, self.runtime)
        self.assertIn("tip._localSkillPopupToken", self.runtime)
        self.assertIn("skillPopupInflight", self.runtime)
        self.assertIn("if(!hasSkillCardContract(card))return null", self.runtime)
        self.assertIn("if(localUrl.origin!==location.origin)return Promise.resolve(null)", self.runtime)
        self.assertIn("if(!isSkillReference(reference))return", self.runtime)
        self.assertIn("header.textContent.trim()==='Alts'", self.runtime)

    def test_active_passive_and_support_catalogs_remain_covered(self) -> None:
        expected = {
            "Active_Skill": "Rocket_Jump",
            "Passive_Skill": "Fearless",
            "Support_Skill": "Multiple_Projectiles",
        }
        for catalog, detail in expected.items():
            with self.subTest(catalog=catalog):
                html = (SITE / f"cn/{catalog}/index.html").read_text(encoding="utf-8")
                self.assertIn("data-hover=", html)
                self.assertIn("data-skilltagid=", html)
                self.assertIn(f"/cn/{detail}/", html)

    def test_generated_runtime_contains_source_of_truth_fix(self) -> None:
        self.assertEqual(self.runtime, self.deployed_runtime)
        self.assertIn("installSkillPopupResolver", self.deployed_runtime)

    def test_structured_search_and_landing_contracts_are_unchanged(self) -> None:
        search = json.loads((SITE / "search-index.json").read_text(encoding="utf-8"))
        structured = json.loads(
            (ROOT / "data/generated/structured/ss13/structured-search-index.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(8, search["schema_version"])
        self.assertEqual(
            1885,
            sum(
                record.get("record_type") in {"skill_effect", "skill_growth_modifier"}
                for record in structured["records"]
            ),
        )
        for token in (
            "structured_skill_pane",
            "skillGrowthTarget",
            "shown.bs.tab",
            "scrollIntoView",
        ):
            self.assertIn(token, self.runtime)


if __name__ == "__main__":
    unittest.main()
