from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from crawler import discover_wiki_i18n


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/rebuild_wiki.sh"


def write_html(root: Path, name: str, resource: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'<html lang="cn"><body data-i18n="nav|hero"><script>fetch("{resource}")</script></body></html>',
        encoding="utf-8",
    )
    return path


class I18nFreshBootstrapV1Test(unittest.TestCase):
    def test_missing_site_uses_raw_only_and_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "data/raw/manifests/test14"
            write_html(raw, "hero/raw_html/Hero.html", "/i18n/cn.json")
            site = root / "local_wiki/test14/site"
            output = root / "reports/i18n.json"
            result = discover_wiki_i18n.main([
                "--season", "test14", "--raw-root", str(raw),
                "--site", str(site), "--output", str(output),
            ])
            self.assertEqual(0, result)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("raw_only", report["input_mode"])
            self.assertIs(report["site_available"], False)
            self.assertEqual(1, report["resource_count"])
            self.assertEqual("https://tlidb.com/i18n/cn.json", report["resources"][0]["resource_url"])

    def test_existing_site_remains_optional_enrichment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw/test14"
            site = root / "local_wiki/test14/site"
            write_html(raw, "hero.html", "/i18n/cn.json")
            write_html(site, "index.html", "/i18n/en.json")
            output = root / "report.json"
            self.assertEqual(0, discover_wiki_i18n.main([
                "--season", "test14", "--raw-root", str(raw),
                "--site", str(site), "--output", str(output),
            ]))
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("raw_plus_site", report["input_mode"])
            self.assertEqual(2, report["resource_count"])

    def test_custom_season_does_not_read_ss13(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "data/raw/manifests/test14"
            write_html(raw, "page.html", "/i18n/cn.json")
            output = root / "data/reports/local-wiki/test14/i18n.json"
            self.assertEqual(0, discover_wiki_i18n.main([
                "--season", "test14", "--raw-root", str(raw),
                "--site", str(root / "local_wiki/test14/site"),
                "--output", str(output),
            ]))
            text = output.read_text(encoding="utf-8")
            self.assertNotIn("ss13", text)
            self.assertIn("test14", text)

    def test_invalid_raw_input_fails_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = root / "raw-file"
            invalid.write_text("not a directory", encoding="utf-8")
            output = root / "report.json"
            self.assertEqual(1, discover_wiki_i18n.main([
                "--season", "test14", "--raw-root", str(invalid),
                "--site", str(root / "missing-site"), "--output", str(output),
            ]))
            self.assertFalse(output.exists())

    def test_orchestrator_keeps_i18n_before_single_full_mirror(self) -> None:
        output = subprocess.run(
            [str(SCRIPT), "--season", "test14", "--dry-run"], cwd=ROOT,
            check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        ).stdout
        discovery = output.index("crawler.discover_wiki_i18n")
        mirror = output.index("crawler.build_full_wiki_mirror")
        self.assertLess(discovery, mirror)
        self.assertEqual(1, output.count("crawler.build_full_wiki_mirror"))
        self.assertNotIn("/ss13", output)


if __name__ == "__main__":
    unittest.main()
