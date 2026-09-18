"""The isolated CLI must retain UTF-8 even on legacy Windows locales."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "Skills" / "content-koubo-slim" / "scripts" / "content_koubo_slim.py"


class CliEncodingTests(unittest.TestCase):
    def test_restart_preserves_argument_error_exit_status(self):
        result = subprocess.run(
            [sys.executable, "-B", str(CLI), "--unknown-option"],
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 2, repr(result.stderr))

    def test_help_is_utf8_after_isolated_restart(self):
        for flags in ([], ["-I", "-S"]):
            with self.subTest(flags=flags):
                result = subprocess.run(
                    [sys.executable, *flags, "-X", "utf8=0", "-B", str(CLI), "--help"],
                    env={**os.environ, "PYTHONUTF8": "0", "PYTHONIOENCODING": "ascii"},
                    capture_output=True,
                    timeout=20,
                )
                self.assertEqual(result.returncode, 0, repr(result.stderr))
                self.assertIn("Content 口播 Slim runtime entry", result.stdout.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
