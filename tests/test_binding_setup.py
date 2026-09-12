from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "Skills" / "content-slim"
sys.path.insert(0, str(SKILL_ROOT))

from runtime.binding_setup import (  # noqa: E402
    BindingSetupError,
    configure_zsk_binding,
)
import runtime.binding_setup as binding_setup  # noqa: E402
from runtime.client_manifest import load_manifest  # noqa: E402
from runtime.client_registry import load_registry, resolve_client  # noqa: E402


VALID_METHOD = """---
asset_id: MET-1234567890abcdef
type: oral_method_asset
status: active
audience_scope: both
keywords:
  - "读者决策表达"
use_when:
  - "需要把问题判断和行动连成短链"
source_id: "SRC-1234567890abcdef12345678"
---

# 顾虑到判断

正文不在绑定预检中读取。
"""

VALID_PROFILE = """---
status: active
is_primary: true
profile_id: PRF-1234567890abcdef
profile_schema: zsk-profile-primary-v1
source_id: "SRC-1234567890abcdef12345678"
---

# 验收主体 Profile

正文不在绑定预检中读取。
"""


class BindingSetupTests(unittest.TestCase):
    def make_vault(self, root: Path) -> Path:
        vault = root / "客户知识库"
        vault.mkdir()
        for name in (
            "03-业务知识库",
            "04-内容方法库",
            "05-IP-Profile",
            "06-Agent与Workflow",
            "07-生产与反馈",
        ):
            (vault / name).mkdir()
        (vault / "04-内容方法库" / "方法.md").write_text(
            VALID_METHOD, encoding="utf-8"
        )
        (vault / "05-IP-Profile" / "主Profile.md").write_text(
            VALID_PROFILE, encoding="utf-8"
        )
        return vault

    def paths(self, root: Path) -> tuple[Path, Path]:
        host = root / "host" / ".content-v2-slim"
        return host / "client-registry.json", host / "runs"

    def test_preview_writes_nothing_then_confirmation_creates_and_reuses(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="content-binding-", dir="/private/tmp"
        ) as directory:
            root = Path(directory)
            vault = self.make_vault(root)
            registry, runs = self.paths(root)

            preview = configure_zsk_binding(
                registry_path=registry,
                runs_root=runs,
                vault_root=vault,
                speaker_mode="personal_ip",
            )
            self.assertEqual(preview["status"], "waiting")
            self.assertFalse(registry.exists())
            self.assertFalse(runs.exists())
            self.assertFalse(
                (
                    vault
                    / "06-Agent与Workflow"
                    / "content-v2-client-manifest.json"
                ).exists()
            )

            created = configure_zsk_binding(
                registry_path=registry,
                runs_root=runs,
                vault_root=vault,
                speaker_mode="personal_ip",
                confirmed_vault_root=str(vault),
            )
            self.assertEqual(created["status"], "completed")
            client_id = created["binding"]["client_id"]
            loaded_registry = load_registry(registry)
            location = resolve_client(loaded_registry, client_id)
            manifest = load_manifest(
                location.manifest_path, expected_client_id=client_id
            )
            self.assertEqual(manifest.default_speaker_mode, "personal_ip")
            self.assertTrue(runs.is_dir())

            reused = configure_zsk_binding(
                registry_path=registry,
                runs_root=runs,
                vault_root=vault,
                speaker_mode="personal_ip",
            )
            self.assertEqual(reused["status"], "completed")
            self.assertEqual(reused["binding"]["registry_action"], "reuse")
            self.assertEqual(reused["binding"]["manifest_action"], "reuse")
            self.assertEqual(reused["binding"]["runs_action"], "reuse")

    def test_confirmation_mismatch_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="content-binding-", dir="/private/tmp"
        ) as directory:
            root = Path(directory)
            vault = self.make_vault(root)
            registry, runs = self.paths(root)
            with self.assertRaisesRegex(
                BindingSetupError, "确认路径"
            ):
                configure_zsk_binding(
                    registry_path=registry,
                    runs_root=runs,
                    vault_root=vault,
                    confirmed_vault_root=str(root / "别的知识库"),
                )
            self.assertFalse(registry.exists())
            self.assertFalse(runs.exists())

    def test_existing_conflict_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="content-binding-", dir="/private/tmp"
        ) as directory:
            root = Path(directory)
            vault = self.make_vault(root)
            registry, runs = self.paths(root)
            registry.parent.mkdir(parents=True)
            original = {
                "registry_version": "2.0",
                "clients": {
                    "other-client": {
                        "vault_root": str(root / "other"),
                        "manifest_relative_path": "config/manifest.json",
                    }
                },
            }
            registry.write_text(
                json.dumps(original), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                BindingSetupError, "不一致"
            ):
                configure_zsk_binding(
                    registry_path=registry,
                    runs_root=runs,
                    vault_root=vault,
                    confirmed_vault_root=str(vault),
                )
            self.assertEqual(
                json.loads(registry.read_text(encoding="utf-8")), original
            )

    def test_invalid_method_contract_stops_before_writes(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="content-binding-", dir="/private/tmp"
        ) as directory:
            root = Path(directory)
            vault = self.make_vault(root)
            registry, runs = self.paths(root)
            (vault / "04-内容方法库" / "方法.md").write_text(
                "---\nsource_id: SRC-ONLY\n---\n\n# 旧格式\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                BindingSetupError, "asset_id"
            ):
                configure_zsk_binding(
                    registry_path=registry,
                    runs_root=runs,
                    vault_root=vault,
                    confirmed_vault_root=str(vault),
                )
            self.assertFalse(registry.exists())
            self.assertFalse(runs.exists())

    def test_personal_mode_requires_exactly_one_primary(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="content-binding-", dir="/private/tmp"
        ) as directory:
            root = Path(directory)
            vault = self.make_vault(root)
            registry, runs = self.paths(root)
            os.unlink(vault / "05-IP-Profile" / "主Profile.md")
            with self.assertRaisesRegex(
                BindingSetupError, "必须且只能"
            ):
                configure_zsk_binding(
                    registry_path=registry,
                    runs_root=runs,
                    vault_root=vault,
                    speaker_mode="personal_ip",
                    confirmed_vault_root=str(vault),
                )
            self.assertFalse(registry.exists())
            self.assertFalse(runs.exists())

    def test_second_write_failure_rolls_back_first_write(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="content-binding-", dir="/private/tmp"
        ) as directory:
            root = Path(directory)
            vault = self.make_vault(root)
            registry, runs = self.paths(root)
            manifest = (
                vault
                / "06-Agent与Workflow"
                / "content-v2-client-manifest.json"
            )
            real_write = binding_setup._write_json_exclusive
            calls = 0

            def fail_second(path, value, created_files):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise BindingSetupError(
                        "write_failed", "simulated second write failure"
                    )
                return real_write(path, value, created_files)

            with mock.patch.object(
                binding_setup,
                "_write_json_exclusive",
                side_effect=fail_second,
            ):
                with self.assertRaisesRegex(
                    BindingSetupError, "simulated"
                ):
                    configure_zsk_binding(
                        registry_path=registry,
                        runs_root=runs,
                        vault_root=vault,
                        confirmed_vault_root=str(vault),
                    )
            self.assertFalse(manifest.exists())
            self.assertFalse(registry.exists())
            self.assertFalse(runs.exists())

    def test_symlink_vault_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="content-binding-", dir="/private/tmp"
        ) as directory:
            root = Path(directory)
            vault = self.make_vault(root)
            linked_vault = root / "linked-vault"
            os.symlink(vault, linked_vault)
            registry, runs = self.paths(root)
            with self.assertRaisesRegex(BindingSetupError, "软链接"):
                configure_zsk_binding(
                    registry_path=registry,
                    runs_root=runs,
                    vault_root=linked_vault,
                    confirmed_vault_root=str(linked_vault),
                )
            self.assertFalse(registry.exists())
            self.assertFalse(runs.exists())


if __name__ == "__main__":
    unittest.main()
