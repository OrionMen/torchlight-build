from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from crawler.extract_tooltips import extract_html_occurrences, extract_manifest


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/tooltips"


def extract_fixture(name: str, source_type: str = "hero"):
    body = (FIXTURES / name).read_text(encoding="utf-8")
    return extract_html_occurrences(
        body, season="ss13", locale="cn", source_type=source_type,
        entity_id="Anger", page_url="https://tlidb.com/cn/Anger",
        manifest_order=0, html_file="Anger.html",
        raw_sha256=hashlib.sha256(body.encode()).hexdigest(), meta_sha256=None,
    )


class TooltipExtractionTests(unittest.TestCase):
    def test_extracts_real_data_attribute_form_and_preserves_chinese(self):
        rows, warnings = extract_fixture("hero_tooltip_data_attribute.html")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["term_zh"], "怒气")
        self.assertEqual(rows[0]["tooltip_title_zh"], "怒气")
        self.assertEqual(rows[0]["tooltip_lines_zh"], [
            "狂人专属的能量，初始上限为 100 点",
            "如果怒气达到最大上限，狂人可以进入暴气状态",
        ])
        self.assertEqual(rows[0]["extract_method"], "bootstrap_data_bs_title_html")
        self.assertEqual(warnings, [])

    def test_occurrence_id_is_stable_and_normal_links_are_ignored(self):
        first, _ = extract_fixture("hero_tooltip_data_attribute.html")
        second, _ = extract_fixture("hero_tooltip_data_attribute.html")
        self.assertEqual(first[0]["occurrence_id"], second[0]["occurrence_id"])
        self.assertEqual(len(first), 1)

    def test_duplicate_occurrences_are_preserved_and_whitespace_normalized(self):
        rows, _ = extract_fixture("duplicate_tooltips.html")
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["occurrence_id"], rows[1]["occurrence_id"])
        self.assertEqual(rows[0]["tooltip_text_zh"], "相同 正文")
        self.assertEqual(rows[0]["tooltip_text_zh"], rows[1]["tooltip_text_zh"])

    def test_missing_text_warns(self):
        rows, warnings = extract_fixture("missing_tooltip_text.html")
        self.assertIsNone(rows[0]["tooltip_text_zh"])
        self.assertEqual(len(warnings), 1)

    def test_missing_html_does_not_stop_batch_and_source_type_is_reusable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            meta = root / "meta"
            output = root / "out"
            raw.mkdir()
            meta.mkdir()
            body = (FIXTURES / "hero_tooltip_data_attribute.html").read_bytes()
            (raw / "Anger.html").write_bytes(body)
            (meta / "Anger.meta.json").write_text(json.dumps({"sha256": hashlib.sha256(body).hexdigest()}))
            manifest = {
                "source": {"locale": "cn"}, "entity_type": "help",
                "entries": [
                    {"id": "Anger", "slug": "Anger", "url": "https://tlidb.com/cn/Anger", "source_order": 0},
                    {"id": "Missing", "slug": "Missing", "url": "https://tlidb.com/cn/Missing", "source_order": 1},
                ],
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            rows, report = extract_manifest(
                season="s1", manifest_path=manifest_path, raw_dir=raw, meta_dir=meta, output_dir=output
            )
            self.assertEqual(rows[0]["source_type"], "help")
            self.assertEqual(report["html_found"], 1)
            self.assertEqual(report["html_missing"], 1)
            self.assertEqual(report["pages_failed"], 0)


if __name__ == "__main__":
    unittest.main()
