import copy
import json
import tempfile
import unittest
from pathlib import Path

from crawler.verify_candidate_systems import apply_results, build_report, render_summary, verify_html


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/candidate_system_verification"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class CandidateSystemApplyTest(unittest.TestCase):
    def test_apply_creates_backup_preserves_known_and_updates_by_classification(self):
        manifest = {
            "system_count": 5,
            "systems": [
                {"system_id": "hero", "discovery_status": "confirmed", "manifest_path": "sources/hero_manifest.json", "source_order": 0},
                {"system_id": "help", "discovery_status": "confirmed", "manifest_path": "sources/help_manifest.json", "source_order": 1},
                {"system_id": "candidate_active_skill", "name_zh": "主动技能", "index_url": "https://tlidb.com/cn/Active_Skill", "discovery_status": "candidate", "manifest_path": "sources/candidate_active_skill_manifest.json", "source_order": 2},
                {"system_id": "candidate_guide", "name_zh": "说明", "index_url": "https://tlidb.com/cn/Guide", "discovery_status": "candidate", "manifest_path": "sources/candidate_guide_manifest.json", "source_order": 3},
                {"system_id": "candidate_unclear", "name_zh": "模糊", "index_url": "https://tlidb.com/cn/Unclear", "discovery_status": "candidate", "manifest_path": "sources/candidate_unclear_manifest.json", "source_order": 4},
            ],
        }
        original_known = copy.deepcopy(manifest["systems"][:2])
        results = [
            verify_html(manifest["systems"][2], fixture("confirmed_directory.html")),
            verify_html(manifest["systems"][3], fixture("content_page.html")),
            verify_html(manifest["systems"][4], fixture("ambiguous_directory.html")),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "system_manifest.json"
            backup_path = root / "system_manifest.before.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            apply_results(manifest_path, manifest, results, backup_path, False, "2026-01-01T00:00:00+00:00")
            applied = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(backup_path.is_file())
            first_applied_bytes = manifest_path.read_bytes()
            apply_results(manifest_path, applied, results, backup_path, False, "later")
            self.assertEqual(first_applied_bytes, backup_path.read_bytes())

        self.assertEqual(applied["systems"][:2], original_known)
        self.assertEqual([item["source_order"] for item in applied["systems"]], [0, 1, 2, 3, 4])
        self.assertEqual(applied["systems"][2]["system_id"], "active_skill")
        self.assertEqual(applied["systems"][2]["discovery_status"], "confirmed")
        self.assertIsNone(applied["systems"][3]["manifest_path"])
        self.assertEqual(applied["systems"][3]["discovery_status"], "content_page")
        self.assertEqual(applied["systems"][4]["system_id"], "candidate_unclear")
        self.assertEqual(applied["systems"][4]["discovery_status"], "candidate")

    def test_report_and_chinese_summary(self):
        candidate = {
            "system_id": "candidate_active_skill",
            "name_zh": "主动技能",
            "index_url": "https://tlidb.com/cn/Active_Skill",
            "discovery_status": "candidate",
        }
        result = verify_html(candidate, fixture("confirmed_directory.html"))
        report = build_report([result], 1, False, None)
        summary = render_summary(report)
        self.assertEqual(report["detail_pages_requested"], 0)
        self.assertEqual(report["confirmed_directory_count"], 1)
        self.assertIn("已确认目录", summary)
        self.assertIn("主动技能", summary)


if __name__ == "__main__":
    unittest.main()
