from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

from crawler.merge_tooltips import main, merge_occurrences


def occurrence(oid, title, text, source_type="hero"):
    return {
        "occurrence_id": oid, "tooltip_title_zh": title, "tooltip_text_zh": text,
        "source_entity_id": "Anger", "source_type": source_type,
        "source": {"hash_match": True},
    }


class TooltipMergeTests(unittest.TestCase):
    def merge(self, rows):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return merge_occurrences(season="ss13", occurrences=rows, output_dir=Path(temporary.name))

    def test_identical_definition_deduplicates_and_keeps_references(self):
        definitions, conflicts, report = self.merge([
            occurrence("one", "怒气", "相同正文"), occurrence("two", "怒气", "相同正文")
        ])
        self.assertEqual(definitions["definition_count"], 1)
        self.assertEqual(definitions["definitions"][0]["occurrence_ids"], ["one", "two"])
        self.assertEqual(report["duplicate_definition_occurrences"], 1)
        self.assertEqual(conflicts["conflict_count"], 0)

    def test_conflicts_cover_title_text_and_duplicate_id(self):
        _, conflicts, report = self.merge([
            occurrence("dup", "怒气", "正文 A"),
            occurrence("dup", "怒气", "正文 B"),
            occurrence("three", "别名", "正文 A"),
        ])
        kinds = {item["conflict_type"] for item in conflicts["conflicts"]}
        self.assertIn("same_title_different_text", kinds)
        self.assertIn("same_text_different_title", kinds)
        self.assertIn("duplicate_occurrence_id", kinds)
        self.assertEqual(report["duplicate_occurrence_id_count"], 1)

    def test_definition_id_is_stable_and_no_fuzzy_merge(self):
        first, _, _ = self.merge([occurrence("one", "怒气", "提高伤害")])
        second, _, _ = self.merge([occurrence("two", "怒气", "提高伤害")])
        self.assertEqual(first["definitions"][0]["definition_id"], second["definitions"][0]["definition_id"])
        separate, _, _ = self.merge([
            occurrence("a", "怒气", "提高伤害"), occurrence("b", "怒气", "增加伤害")
        ])
        self.assertEqual(separate["definition_count"], 2)

    def test_duplicate_occurrence_id_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            rows = [occurrence("duplicate", "怒气", "正文"), occurrence("duplicate", "怒气", "正文")]
            (source / "occurrences.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
            )
            result = main(["--season", "ss13", "--input", str(source), "--output", str(root / "merged")])
            self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
