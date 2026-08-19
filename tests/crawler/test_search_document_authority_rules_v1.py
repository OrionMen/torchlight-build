from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crawler.build_full_wiki_mirror import (
    TextInspector,
    build,
    load_structured_record_ownership,
    select_search_plain_text,
    structured_owned_section_ids,
)


ROOT = Path(__file__).resolve().parents[2]
STRUCTURED_INDEX = ROOT / "data/generated/structured/ss13/structured-search-index.json"


class SearchDocumentAuthorityRulesV1Test(unittest.TestCase):
    @staticmethod
    def extracted(raw: str, excluded=()) -> str:
        inspector = TextInspector(excluded_section_ids=excluded)
        inspector.feed(raw)
        return " ".join(" ".join(inspector.text).split())

    def test_synthetic_entity_clean_summary_has_authority_over_raw_and_cache(self) -> None:
        raw = (
            '<h1>SyntheticAlpha</h1><p>ordinary body</p>'
            '<div id="support" class="tab-pane fade">hidden contamination token</div>'
        )
        extracted = self.extracted(raw)
        entity = {"entity_type": "synthetic", "clean_summary": "canonical searchable phrase"}
        plain = select_search_plain_text(entity, extracted, "stale contamination token", False)
        self.assertEqual("canonical searchable phrase", plain)
        self.assertNotIn("hidden contamination token", plain)
        self.assertNotIn("stale contamination token", plain)

    def test_synthetic_structured_owner_excludes_fully_owned_external_section(self) -> None:
        raw = (
            '<h1>AuxiliaryAlpha</h1><p>ordinary page phrase</p>'
            '<div id="SharedFacts"><span data-modifier-id="9001">duplicate token</span></div>'
        )
        ownership = {"modifier:9001": {("tlidb:cn:SyntheticOwner", "/cn/SyntheticOwner/")}}
        excluded = structured_owned_section_ids(raw, "/cn/AuxiliaryAlpha/", ownership)
        self.assertEqual({"SharedFacts"}, excluded)
        plain = self.extracted(raw, excluded)
        self.assertIn("ordinary page phrase", plain)
        self.assertNotIn("duplicate token", plain)

    def test_section_is_not_excluded_without_complete_or_external_ownership(self) -> None:
        raw = (
            '<div id="CraftFacts"><span data-modifier-id="9001">owned phrase</span>'
            '<span data-modifier-id="9002">legitimate craft phrase</span></div>'
        )
        partial = {"modifier:9001": {("tlidb:cn:Owner", "/cn/Owner/")}}
        self.assertEqual(set(), structured_owned_section_ids(raw, "/cn/CraftPage/", partial))
        same_route = {
            "modifier:9001": {("tlidb:cn:CraftPage", "/cn/CraftPage/")},
            "modifier:9002": {("tlidb:cn:CraftPage", "/cn/CraftPage/")},
        }
        self.assertEqual(set(), structured_owned_section_ids(raw, "/cn/CraftPage/", same_route))
        self.assertIn("legitimate craft phrase", self.extracted(raw))

    def test_page_without_authoritative_entity_keeps_normal_fallback(self) -> None:
        self.assertEqual(
            "ordinary raw searchable phrase",
            select_search_plain_text(None, "ordinary raw searchable phrase", "", False),
        )

    def test_real_hero_regression_uses_clean_entity_summary(self) -> None:
        pages = json.loads(
            (ROOT / "local_wiki/ss13/site/search-index.json").read_text(encoding="utf-8")
        )["pages"]
        heroes = [page for page in pages if page.get("entity_type") == "hero"]
        self.assertEqual(27, len(heroes))
        for hero in heroes:
            with self.subTest(entity_id=hero["entity_id"]):
                self.assertIn("痛楚加剧", hero["plain_text"])
                self.assertNotIn("加剧", hero["clean_summary"])
                plain = select_search_plain_text(
                    hero, hero["plain_text"], hero["plain_text"], False
                )
                self.assertEqual(hero["clean_summary"], plain)
                self.assertIn(hero["entity_title"], plain)
                self.assertNotIn("痛楚加剧", plain)

    def test_real_memory_auxiliary_sections_are_owned_by_structured_records(self) -> None:
        ownership = load_structured_record_ownership(STRUCTURED_INDEX)
        for page_id in (
            "Memory_of_Discipline", "Memory_of_Origin", "Memory_of_Progress",
        ):
            with self.subTest(page_id=page_id):
                raw = (ROOT / f"data/raw/manifests/ss13/craft/raw_html/{page_id}.html").read_text(
                    encoding="utf-8"
                )
                excluded = structured_owned_section_ids(raw, f"/cn/{page_id}/", ownership)
                self.assertIn("固有词缀", excluded)
                plain = self.extracted(raw, excluded)
                self.assertNotIn("加剧", plain)
        memory_records = [
            record for record in json.loads(STRUCTURED_INDEX.read_text(encoding="utf-8"))["records"]
            if record.get("entity_id") == "tlidb:cn:Hero_Memories"
            and "加剧" in record.get("text", "")
        ]
        self.assertTrue(memory_records)
        self.assertTrue(all(record["content_category_id"] == "memory" for record in memory_records))

    def test_fixture_build_preserves_schema_and_structured_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_root = root / "raw"
            page_dir = raw_root / "craft/raw_html"
            page_dir.mkdir(parents=True)
            page_dir.joinpath("AuxiliaryAlpha.html").write_text(
                '<title>AuxiliaryAlpha</title><p>ordinary fallback phrase</p>'
                '<div id="SharedFacts"><span data-modifier-id="9001">duplicate token</span></div>',
                encoding="utf-8",
            )
            asset_manifest = root / "assets.json"
            asset_manifest.write_text('{"assets": []}', encoding="utf-8")
            catalog = root / "catalog.json"
            catalog.write_text(json.dumps({"pages": [{
                "system_id": "craft", "system_name_zh": "打造", "id": "AuxiliaryAlpha",
                "slug": "AuxiliaryAlpha", "title": "AuxiliaryAlpha",
                "source_url": "https://tlidb.com/cn/AuxiliaryAlpha",
            }]}), encoding="utf-8")
            old_search = root / "old-search.json"
            old_search.write_text(json.dumps({"schema_version": 8, "pages": [{
                "system_id": "craft", "id": "AuxiliaryAlpha", "title": "AuxiliaryAlpha",
                "plain_text": "stale duplicate token",
            }]}), encoding="utf-8")
            structured = root / "structured-search-index.json"
            structured_data = {"schema_version": 1, "records": [{
                "record_id": "tlidb:record:synthetic", "entity_id": "tlidb:cn:SyntheticOwner",
                "entity_title": "SyntheticOwner", "record_type": "synthetic_fact",
                "section_name": "SharedFacts", "text": "duplicate token",
                "route": "/cn/SyntheticOwner/", "source_locator": {
                    "stable_key": "modifier:9001", "locator_level": "record"
                },
            }]}
            structured.write_text(json.dumps(structured_data), encoding="utf-8")
            output = root / "site"
            build(
                "synthetic-season", raw_root, asset_manifest, root / "asset-files", output,
                catalog_path=catalog, search_index_path=old_search,
                structured_search_index_path=structured,
            )
            index = json.loads((output / "search-index.json").read_text(encoding="utf-8"))
            self.assertEqual(8, index["schema_version"])
            self.assertIn("ordinary fallback phrase", index["pages"][0]["plain_text"])
            self.assertNotIn("duplicate token", index["pages"][0]["plain_text"])
            self.assertNotIn("stale", index["pages"][0]["plain_text"])
            self.assertEqual(
                structured_data,
                json.loads((output / "structured-search-index.json").read_text(encoding="utf-8")),
            )


if __name__ == "__main__":
    unittest.main()
