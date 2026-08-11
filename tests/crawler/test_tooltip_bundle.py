from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from crawler.build_tooltip_bundle import build_bundle


class TooltipBundleTests(unittest.TestCase):
    def setup_files(self, root: Path):
        merged = root / "merged"
        source = root / "hero"
        merged.mkdir()
        source.mkdir()
        (merged / "definitions.json").write_text(json.dumps({"definition_count": 1}), encoding="utf-8")
        (merged / "conflicts.json").write_text(json.dumps({"conflict_count": 0}), encoding="utf-8")
        (merged / "merge-report.json").write_text(json.dumps({"input_occurrence_count": 1}), encoding="utf-8")
        row = {"occurrence_id": "one", "source_type": "hero"}
        (source / "occurrences.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        (source / "report.json").write_text(json.dumps({"tooltip_occurrence_count": 1}), encoding="utf-8")
        return merged, source

    def test_bundle_structure_metadata_and_readme(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            merged, source = self.setup_files(root)
            output = root / "bundle.zip"
            meta = build_bundle(season="ss13", merged_dir=merged, occurrence_dirs=[source], output=output)
            self.assertEqual(meta["definition_count"], 1)
            self.assertEqual(meta["occurrence_count"], 1)
            with ZipFile(output) as archive:
                names = set(archive.namelist())
                self.assertTrue({
                    "bundle_meta.json", "definitions.json", "occurrences/hero.jsonl",
                    "conflicts.json", "reports/merge-report.json", "README.md",
                }.issubset(names))
                self.assertIn("不是正式 Concept", archive.read("README.md").decode("utf-8"))

    def test_missing_required_file_raises(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.mkdir(exist_ok=True)
            with self.assertRaises(ValueError):
                build_bundle(season="ss13", merged_dir=root, occurrence_dirs=[], output=root / "x.zip")


if __name__ == "__main__":
    unittest.main()
