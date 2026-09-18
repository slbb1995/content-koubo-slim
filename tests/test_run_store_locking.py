from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "Skills" / "content-koubo-slim"


class RunStoreLockingTests(unittest.TestCase):
    def test_two_processes_serialize_and_release_the_run_store_lock(self) -> None:
        """The second process must enter only after the first releases the lock."""

        program = """
import sys
import time
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from runtime.run_store import RunStore

store = RunStore(Path(sys.argv[2]))
mode = sys.argv[3]
if mode == 'hold':
    with store._exclusive_lock():
        print('locked', flush=True)
        time.sleep(0.75)
else:
    started = time.monotonic()
    with store._exclusive_lock():
        print(f'waited={time.monotonic() - started:.3f}', flush=True)
"""
        with tempfile.TemporaryDirectory(prefix=".content-koubo-lock-", dir=ROOT) as directory:
            runs_root = Path(directory) / "runs"
            holder = subprocess.Popen(
                [sys.executable, "-X", "utf8", "-B", "-c", program, str(SKILL_ROOT), str(runs_root), "hold"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            self.assertIsNotNone(holder.stdout)
            holder_status = holder.stdout.readline().strip()
            if holder_status != "locked":
                _, holder_stderr = holder.communicate(timeout=10)
                self.fail(f"lock holder did not start: {holder_stderr}")
            waiter = subprocess.run(
                [sys.executable, "-X", "utf8", "-B", "-c", program, str(SKILL_ROOT), str(runs_root), "wait"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
                check=False,
            )
            _, holder_stderr = holder.communicate(timeout=10)

        self.assertEqual(holder.returncode, 0, holder_stderr)
        self.assertEqual(waiter.returncode, 0, waiter.stderr)
        self.assertRegex(waiter.stdout.strip(), r"^waited=0\.[4-9][0-9]{2}$")


if __name__ == "__main__":
    unittest.main()
