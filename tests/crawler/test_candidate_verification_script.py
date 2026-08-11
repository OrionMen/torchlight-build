import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class CandidateVerificationScriptTest(unittest.TestCase):
    def test_help_and_safe_default_command(self):
        script = ROOT / "scripts/verify_candidate_systems.sh"
        result = subprocess.run(
            [str(script), "--help"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--apply", result.stdout)
        content = script.read_text(encoding="utf-8")
        self.assertIn("--all", content)
        self.assertNotIn("fetch_manifest", content)
        self.assertNotIn("discover_all_sources.sh", content)


if __name__ == "__main__":
    unittest.main()
