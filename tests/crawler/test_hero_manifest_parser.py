import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from crawler.parse_hero import parse_hero_html
from crawler.parse_hero_manifest import find_effect_issues, parse_manifest_batch


FIXTURE = """
<!doctype html><html><body>
<div class="card-body">
  <img class="size128" src="/portrait.webp" alt="英雄头像"><br>
  <a href="Character">测试人物</a><br>
  这是忠实保留的中文简介。<br>
  <a href="Skill"><img src="/skill.webp">推荐技能</a>
</div>
<div class="card">
  <h5 class="card-header">测试特性 - 英雄特性 /2</h5>
  <div class="d-flex border-top rounded">
    <div class="flex-shrink-0"><img src="/node1.webp" alt="节点一"></div>
    <div class="flex-grow-1 mx-2 my-1">
      <div class="fw-bold">节点一</div><hr>
      <div>
        <div class="tierLevel">等级 1</div>
        <div><span>中文效果甲</span><br><span>中文效果乙</span></div>
      </div>
    </div>
  </div>
  <div class="d-flex border-top rounded">
    <div class="flex-shrink-0"><img src="/node2.webp" alt="节点二"></div>
    <div class="flex-grow-1 mx-2 my-1">
      <div class="fw-bold">节点二</div><hr>
      <div><div><span>原文包含句号。仍在同一 DOM 块中，不强制拆句。</span></div></div>
    </div>
  </div>
</div>
</body></html>
"""


def parsed_fixture():
    return parse_hero_html(
        FIXTURE,
        entity_id="Test_Hero",
        name_zh="测试人物|测试特性",
        page_url="https://tlidb.com/cn/Test_Hero",
        raw_sha256="abc123",
    )


class HeroParserTest(unittest.TestCase):
    def test_effect_ids_and_node_order_are_stable(self):
        first = parsed_fixture()
        second = parsed_fixture()
        first_ids = [
            effect["effect_id"]
            for node in first["nodes"]
            for level in node["levels"]
            for effect in level["effects"]
        ]
        second_ids = [
            effect["effect_id"]
            for node in second["nodes"]
            for level in node["levels"]
            for effect in level["effects"]
        ]
        self.assertEqual(first_ids, second_ids)
        self.assertEqual([node["name"] for node in first["nodes"]], ["节点一", "节点二"])

    def test_unspecified_level_and_no_punctuation_split(self):
        document = parsed_fixture()
        level = document["nodes"][1]["levels"][0]
        self.assertIsNone(level["level"])
        self.assertEqual(len(level["effects"]), 1)
        self.assertIn("level.unspecified.effect.0", level["effects"][0]["effect_id"])
        self.assertEqual(level["effects"][0]["text"], "原文包含句号。仍在同一 DOM 块中，不强制拆句。")

    def test_chinese_text_and_source_location_are_preserved(self):
        document = parsed_fixture()
        effect = document["nodes"][0]["levels"][0]["effects"][1]
        self.assertEqual(effect["text"], "中文效果乙")
        self.assertEqual(
            effect["source"],
            {
                "url": "https://tlidb.com/cn/Test_Hero",
                "node_index": 0,
                "node_name": "节点一",
                "trait_level": 1,
                "effect_index": 1,
                "raw_html_sha256": "abc123",
            },
        )

    def test_duplicate_and_empty_effect_detection(self):
        document = parsed_fixture()
        duplicate_document = copy.deepcopy(document)
        duplicate_document["nodes"][1]["levels"][0]["effects"][0]["text"] = ""
        duplicates, empty = find_effect_issues([document, duplicate_document])
        self.assertTrue(duplicates)
        self.assertTrue(empty)

    def test_batch_failure_does_not_stop_other_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_dir = root / "raw"
            structured_dir = root / "structured"
            report_dir = root / "reports"
            (raw_dir / "raw_html").mkdir(parents=True)
            (raw_dir / "meta").mkdir(parents=True)
            body = FIXTURE.encode("utf-8")
            digest = hashlib.sha256(body).hexdigest()
            (raw_dir / "raw_html/Good.html").write_bytes(body)
            (raw_dir / "meta/Good.meta.json").write_text(
                json.dumps(
                    {
                        "id": "Good",
                        "source_url": "https://tlidb.com/cn/Good",
                        "encoding": "utf-8",
                        "sha256": digest,
                    }
                ),
                encoding="utf-8",
            )
            manifest = {
                "entries": [
                    {"id": "Good", "slug": "Good", "name_zh": "正常", "url": "https://tlidb.com/cn/Good"},
                    {"id": "Missing", "slug": "Missing", "name_zh": "缺失", "url": "https://tlidb.com/cn/Missing"},
                ]
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            report, _consistency, status = parse_manifest_batch(
                manifest_path, raw_dir, structured_dir, report_dir
            )
            self.assertEqual(status, 1)
            self.assertEqual(report["parse_success_count"], 1)
            self.assertEqual(report["parse_failure_count"], 1)
            self.assertTrue((structured_dir / "Good.json").is_file())


if __name__ == "__main__":
    unittest.main()
