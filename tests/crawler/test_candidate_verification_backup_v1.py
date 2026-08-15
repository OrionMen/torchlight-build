from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from crawler import verify_candidate_systems as verifier


def manifest() -> dict:
    return {
        "schema_version": 1,
        "systems": [
            {
                "system_id": "hero",
                "discovery_status": "confirmed",
                "manifest_path": "hero_manifest.json",
            }
        ],
    }


class CandidateVerificationBackupV1Test(unittest.TestCase):
    def test_season_manifest_backup_uses_same_namespace(self) -> None:
        source = Path("sources/seasons/ss13/system_manifest.json")
        self.assertEqual(
            Path("sources/seasons/ss13/system_manifest.before_candidate_verification.json"),
            verifier.backup_path_for_manifest(source),
        )

    def test_season_backups_are_isolated(self) -> None:
        ss13 = verifier.backup_path_for_manifest(Path("sources/seasons/ss13/system_manifest.json"))
        test14 = verifier.backup_path_for_manifest(Path("sources/seasons/test14/system_manifest.json"))
        self.assertNotEqual(ss13.parent, test14.parent)
        self.assertEqual("ss13", ss13.parent.name)
        self.assertEqual("test14", test14.parent.name)

    def test_legacy_manifest_remains_compatible(self) -> None:
        source = Path("sources/system_manifest.json")
        self.assertEqual(
            Path("sources/system_manifest.before_candidate_verification.json"),
            verifier.backup_path_for_manifest(source),
        )

    def test_existing_backup_is_atomically_refreshed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "system_manifest.json"
            backup = verifier.backup_path_for_manifest(source)
            original = json.dumps(manifest()).encode()
            source.write_bytes(original)
            backup.write_text("stale backup", encoding="utf-8")
            verifier.apply_results(source, manifest(), [], backup, False, "now")
            self.assertEqual(original, backup.read_bytes())

    def test_backup_is_exact_pre_apply_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "system_manifest.json"
            original = b'{"schema_version": 1, "systems": []}'
            source.write_bytes(original)
            backup = verifier.backup_path_for_manifest(source)
            verifier.apply_results(source, {"schema_version": 1, "systems": []}, [], backup, False, "now")
            self.assertEqual(original, backup.read_bytes())

    def test_second_apply_succeeds_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "system_manifest.json"
            source.write_text(json.dumps(manifest()), encoding="utf-8")
            backup = verifier.backup_path_for_manifest(source)
            verifier.apply_results(source, manifest(), [], backup, False, "first")
            verifier.apply_results(source, manifest(), [], backup, False, "second")
            self.assertTrue(backup.is_file())
            self.assertEqual(manifest(), json.loads(source.read_text(encoding="utf-8")))

    def test_failed_manifest_replace_preserves_original(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "system_manifest.json"
            source.write_text(json.dumps(manifest()), encoding="utf-8")
            original = source.read_bytes()
            backup = verifier.backup_path_for_manifest(source)
            real_replace = verifier.atomic_replace_bytes

            def fail_only_manifest(path: Path, content: bytes) -> None:
                if path == source:
                    raise OSError("injected manifest replacement failure")
                real_replace(path, content)

            with mock.patch.object(verifier, "atomic_replace_bytes", side_effect=fail_only_manifest):
                with self.assertRaises(OSError):
                    verifier.apply_results(source, manifest(), [], backup, False, "now")
            self.assertEqual(original, source.read_bytes())
            self.assertEqual(original, backup.read_bytes())

    def test_non_apply_cli_does_not_create_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "system_manifest.json"
            source.write_text(json.dumps(manifest()), encoding="utf-8")
            status = verifier.main([
                "--system-manifest", str(source), "--all",
                "--report", str(root / "report.json"),
                "--summary", str(root / "summary.md"),
                "--preview-dir", str(root / "previews"),
            ])
            self.assertEqual(0, status)
            self.assertFalse(verifier.backup_path_for_manifest(source).exists())

    def test_apply_cli_can_rerun_with_existing_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "seasons/test14/system_manifest.json"
            source.parent.mkdir(parents=True)
            source.write_text(json.dumps(manifest()), encoding="utf-8")
            args = [
                "--system-manifest", str(source), "--all", "--apply",
                "--report", str(root / "report.json"),
                "--summary", str(root / "summary.md"),
                "--preview-dir", str(root / "previews"),
            ]
            self.assertEqual(0, verifier.main(args))
            self.assertEqual(0, verifier.main(args))
            backup = verifier.backup_path_for_manifest(source)
            self.assertEqual(source.parent, backup.parent)
            self.assertTrue(backup.is_file())

    def test_implementation_contains_no_external_repo_path(self) -> None:
        source = Path(verifier.__file__).read_text(encoding="utf-8")
        self.assertNotIn("torchlight-build-fresh", source)
        self.assertNotIn("Documents/torchlight-build/", source)


if __name__ == "__main__":
    unittest.main()
