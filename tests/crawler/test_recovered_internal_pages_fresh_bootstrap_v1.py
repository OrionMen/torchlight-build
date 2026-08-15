from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from crawler import discover_recovered_internal_pages as recovered


ROOT = Path(__file__).resolve().parents[2]


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(root: Path, *, reverse: bool = False) -> tuple[Path, Path]:
    sources = root / "sources"
    raw = root / "raw"
    entries = [
        {"id": "Index", "slug": "Index", "url": "https://tlidb.com/cn/Index"},
        {"id": "Existing", "slug": "Existing", "url": "https://tlidb.com/cn/Existing"},
    ]
    if reverse:
        entries.reverse()
    manifest = sources / "sample_manifest.json"
    _write_json(manifest, {"entries": entries})
    systems = sources / "system_manifest.json"
    _write_json(systems, {"systems": [{
        "system_id": "sample", "discovery_status": "confirmed",
        "manifest_path": str(manifest),
    }]})
    html = """
      <a href="Existing#section">existing</a>
      <a href="New_Page#first">new relative</a>
      <a href="https://www.tlidb.com/cn/New_Page?utm_source=x#second">new absolute</a>
      <a href="/cn/New_Page?lang=cn">new root</a>
      <a href="https://example.com/cn/External">external</a>
      <a href="/assets/icon.webp">asset</a>
      <a href="/cn/cache">cache</a>
      <a href="/api/page">api</a>
      <a href="#only-anchor">anchor</a>
      <a href="?only=query">query</a>
    """
    source_html = raw / "sample/raw_html/Index.html"
    source_html.parent.mkdir(parents=True, exist_ok=True)
    source_html.write_text(html, encoding="utf-8")
    existing_html = raw / "sample/raw_html/Existing.html"
    existing_html.write_text("<html></html>", encoding="utf-8")

    recovered_root = raw / "recovered_internal_pages"
    _write_json(recovered_root / "meta/New_Page.meta.json", {
        "id": "New_Page", "slug": "New_Page", "source_url": "https://tlidb.com/cn/New_Page",
        "http_status": 200,
    })
    recovered_html = recovered_root / "raw_html/New_Page.html"
    recovered_html.parent.mkdir(parents=True, exist_ok=True)
    recovered_html.write_text('<a href="Existing">existing again</a>', encoding="utf-8")
    return systems, raw


class RecoveredInternalPagesFreshBootstrapV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.production_discovery = recovered.discover_recovered_pages(
            ROOT / "sources/system_manifest.json", ROOT / "data/raw/manifests"
        )
        cls.production_manifest = recovered.build_manifest(cls.production_discovery)
        cls.reference = json.loads(
            (ROOT / "sources/recovered_internal_pages_manifest.json").read_text(encoding="utf-8")
        )
        cls.production_report = recovered.build_bootstrap_report(
            cls.production_discovery, cls.production_manifest,
            reference_manifest=cls.reference,
        )

    def test_bootstrap_needs_no_local_or_generated_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            systems, raw = _fixture(root)
            output = root / "output/recovered.json"
            manifest, discovery = recovered.generate_manifest(systems, raw, output)
            self.assertFalse((root / "local_wiki").exists())
            for name in ("catalog.json", "search-index.json", "entity-index-v3.json", "structured-search-index.json"):
                self.assertFalse(any(root.rglob(name)))
            self.assertFalse((root / "data/reports").exists())
            self.assertEqual(1, manifest["entry_count"])
            self.assertEqual("New_Page", manifest["entries"][0]["slug"])
            self.assertEqual(1, discovery["recovered_candidates"])

    def test_manifest_exclusion_canonical_dedup_and_noise_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            systems, raw = _fixture(Path(directory))
            discovery = recovered.discover_recovered_pages(systems, raw)
            manifest = recovered.build_manifest(discovery)
            self.assertEqual(["New_Page"], [entry["slug"] for entry in manifest["entries"]])
            self.assertGreaterEqual(discovery["already_manifested"], 1)
            entry = manifest["entries"][0]
            self.assertEqual("/cn/New_Page", entry["path"])
            self.assertEqual("https://tlidb.com/cn/New_Page", entry["url"])
            self.assertEqual(3, len(entry["source_examples"]))
            self.assertTrue(all(source["system_id"] == "sample" for source in entry["source_examples"]))

    def test_relative_absolute_fragment_and_query_canonicalization(self) -> None:
        base = "https://tlidb.com/cn/Index"
        identities = [
            recovered.canonical_internal_page("New_Page#x", base),
            recovered.canonical_internal_page("/cn/New_Page?x=1", base),
            recovered.canonical_internal_page("https://www.tlidb.com/cn/New_Page#y", base),
        ]
        self.assertEqual({"/cn/New_Page/"}, {item["route"] for item in identities if item})
        for value in ("#x", "?x=1", "https://example.com/cn/X", "/asset/x.png", "/cn/cache", "/api/X"):
            self.assertIsNone(recovered.canonical_internal_page(value, base))

    def test_provenance_and_output_are_order_independent(self) -> None:
        manifests = []
        for reverse in (False, True):
            temporary = tempfile.TemporaryDirectory()
            self.addCleanup(temporary.cleanup)
            systems, raw = _fixture(Path(temporary.name), reverse=reverse)
            manifests.append(recovered.build_manifest(recovered.discover_recovered_pages(systems, raw)))
        self.assertEqual(recovered.canonical_bytes(manifests[0]), recovered.canonical_bytes(manifests[1]))
        self.assertEqual(recovered.canonical_hash(manifests[0]), recovered.canonical_hash(manifests[1]))

    def test_repeated_atomic_generation_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            systems, raw = _fixture(root)
            output = root / "manifest.json"
            first, _ = recovered.generate_manifest(systems, raw, output)
            first_bytes = output.read_bytes()
            second, _ = recovered.generate_manifest(systems, raw, output)
            self.assertEqual(first, second)
            self.assertEqual(first_bytes, output.read_bytes())

    def test_atomic_failure_preserves_previous_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            systems, raw = _fixture(root)
            output = root / "manifest.json"
            output.write_text("known-good", encoding="utf-8")
            with mock.patch.object(recovered.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    recovered.generate_manifest(systems, raw, output)
            self.assertEqual("known-good", output.read_text(encoding="utf-8"))
            self.assertFalse(list(root.glob(".manifest.json.*.tmp")))

    def test_invalid_inputs_and_convergence_guard_fail_hard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bad = root / "bad.json"
            bad.write_text("not-json", encoding="utf-8")
            with self.assertRaises(recovered.RecoveredDiscoveryError):
                recovered.discover_recovered_pages(bad, root / "raw")
        with self.assertRaises(recovered.RecoveredDiscoveryError):
            recovered.build_manifest({"candidates": []}, max_rounds=0)
        with self.assertRaises(recovered.RecoveredDiscoveryError):
            recovered.build_manifest({"candidates": []}, max_rounds=33)
        self.assertEqual(8, recovered.MAX_CONVERGENCE_ROUNDS)

    def test_current_required_recovered_routes_are_fully_preserved(self) -> None:
        self.assertEqual(1682, self.production_report["reference_recovered_count"])
        self.assertEqual(1680, self.production_report["reference_required_count"])
        self.assertEqual(1680, self.production_report["fresh_recovered_count"])
        self.assertEqual([], self.production_report["missing_routes"])
        self.assertEqual([], self.production_report["extra_routes"])
        self.assertTrue(self.production_report["recovered_internal_pages_bootstrap_ready"])

    def test_recovered_fate_routes_have_real_provenance_and_are_now_formal(self) -> None:
        by_id = {
            item["page_id"]: item
            for item in self.production_discovery["recovered_raw_now_manifested"]
        }
        for page_id in (
            "Micro_Fate:_Deterioration_Duration",
            "Micro_Fate:_Trauma_Damage_Mitigation",
        ):
            self.assertIn(page_id, by_id)
            self.assertTrue(by_id[page_id]["discovered_from"])
            self.assertTrue(any(source["page_id"] == "Destiny" for source in by_id[page_id]["discovered_from"]))
            self.assertIn("formal manifest", by_id[page_id]["reason"])

    def test_production_code_has_no_specific_fate_allowlist(self) -> None:
        source = (ROOT / "crawler/discover_recovered_internal_pages.py").read_text(encoding="utf-8")
        self.assertNotIn("Micro_Fate:_Deterioration_Duration", source)
        self.assertNotIn("Micro_Fate:_Trauma_Damage_Mitigation", source)


if __name__ == "__main__":
    unittest.main()
