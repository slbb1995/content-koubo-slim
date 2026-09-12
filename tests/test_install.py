from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "content_slim_install", ROOT / "install.py"
)
assert SPEC is not None and SPEC.loader is not None
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)


class InstallTests(unittest.TestCase):
    def test_install_is_create_only_and_hash_verified(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="content-install-", dir="/private/tmp"
        ) as directory:
            destination = Path(directory) / "skills"
            self.assertEqual(INSTALLER.install(destination), 0)
            present, missing = INSTALLER.installed_state(destination)
            self.assertEqual(set(present), set(INSTALLER.COMPONENTS))
            self.assertEqual(missing, [])
            manifest = INSTALLER.release_manifest()
            self.assertEqual(
                INSTALLER.verify_installed(destination, manifest), []
            )
            self.assertEqual(INSTALLER.install(destination), 3)

    def test_copy_failure_rolls_back_new_components(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="content-install-", dir="/private/tmp"
        ) as directory:
            destination = Path(directory) / "skills"
            calls = 0

            def fail_second(source, target, *args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated copy failure")
                target.mkdir()
                return target

            with mock.patch.object(
                INSTALLER.shutil, "copytree", side_effect=fail_second
            ):
                self.assertEqual(INSTALLER.install(destination), 4)
            for name in INSTALLER.COMPONENTS:
                self.assertFalse((destination / name).exists())

    def test_symlink_destination_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="content-install-", dir="/private/tmp"
        ) as directory:
            root = Path(directory)
            real_destination = root / "real-skills"
            real_destination.mkdir()
            linked_destination = root / "linked-skills"
            os.symlink(real_destination, linked_destination)
            self.assertEqual(INSTALLER.install(linked_destination), 5)
            for name in INSTALLER.COMPONENTS:
                self.assertFalse((real_destination / name).exists())


if __name__ == "__main__":
    unittest.main()
