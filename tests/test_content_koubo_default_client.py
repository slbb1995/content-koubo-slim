from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "Skills" / "content-koubo-slim"
sys.path.insert(0, str(SKILL_ROOT))

from runtime.client_registry import (  # noqa: E402
    default_registry_path,
    default_runs_root,
    select_client_id,
)
from runtime.error_model import SlimRuntimeError  # noqa: E402
from scripts.content_koubo_slim import build_parser, prepare_direction_stage  # noqa: E402


class DefaultClientTests(unittest.TestCase):
    def temporary_root(self):
        parent = Path("/private/tmp") if Path("/private/tmp").is_dir() else None
        return tempfile.TemporaryDirectory(prefix="content-koubo-default-client-", dir=parent)

    def test_default_paths_follow_current_codex_home(self) -> None:
        with self.temporary_root() as directory:
            host = Path(directory) / "host"
            with mock.patch.dict(os.environ, {"CODEX_HOME": str(host)}):
                self.assertEqual(
                    default_registry_path(),
                    host / ".content-koubo-slim" / "client-registry.json",
                )
                self.assertEqual(
                    default_runs_root(),
                    host / ".content-koubo-slim" / "runs",
                )
                args = build_parser().parse_args(
                    [
                        "start",
                        "--topic-original",
                        "测试选题",
                        "--reference",
                        str(Path(directory) / "reference.md"),
                    ]
                )
                self.assertIsNone(args.registry)
                self.assertEqual(args.runs_root, str(default_runs_root()))
                self.assertIsNone(args.client_id)

    def test_only_configured_client_is_selected(self) -> None:
        registry = {
            "registry_version": "2.0",
            "clients": {
                "client-one": {
                    "vault_root": "/private/tmp/client-one",
                    "manifest_relative_path": "config/manifest.json",
                }
            },
        }
        self.assertEqual(select_client_id(registry), "client-one")
        self.assertEqual(select_client_id(registry, "client-one"), "client-one")

    def test_multiple_clients_require_an_explicit_choice(self) -> None:
        registry = {
            "registry_version": "2.0",
            "clients": {
                "client-one": {},
                "client-two": {},
            },
        }
        with self.assertRaises(SlimRuntimeError) as context:
            select_client_id(registry)
        self.assertIn("多个客户", context.exception.user_response()["next_action"])

    def test_start_uses_the_only_client_without_a_client_argument(self) -> None:
        with self.temporary_root() as directory:
            root = Path(directory)
            vault = root / "内容资料库"
            vault.mkdir()
            for name in ("knowledge", "method", "profile", "output", "config"):
                (vault / name).mkdir()
            manifest = {
                "contract_version": "2.0",
                "client_id": "client-one",
                "asset_roots": {
                    "knowledge": "knowledge",
                    "method": "method",
                    "profile": "profile",
                    "output": "output",
                },
                "default_speaker_mode": "neutral",
                "allowed_speaker_modes": [
                    "personal_ip",
                    "company_brand",
                    "neutral",
                ],
                "profile_policy": {
                    "required_when": ["personal_ip"],
                    "selector": {"status": "active", "is_primary": True},
                },
                "default_platform": "short_video",
                "output_template": "content/{profile_or_brand}/weekly",
            }
            (vault / "config" / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )
            registry = root / "client-registry.json"
            registry.write_text(
                json.dumps(
                    {
                        "registry_version": "2.0",
                        "clients": {
                            "client-one": {
                                "vault_root": str(vault),
                                "manifest_relative_path": "config/manifest.json",
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            reference = root / "reference.md"
            reference.write_text("# 参考\n\n先确认问题，再给方案。\n", encoding="utf-8")

            response, task_record = prepare_direction_stage(
                registry_path=registry,
                runs_root=root / "runs",
                client_id=None,
                speaker_mode=None,
                topic_original="如何先确认需求",
                reference_paths=[reference],
                user_thoughts=None,
                must_keep=[],
                must_avoid=[],
            )
            self.assertEqual(response["status"], "working")
            self.assertTrue(response["run_created_now"])
            self.assertRegex(task_record, r"^task-keys/[0-9a-f]{64}\.json$")


if __name__ == "__main__":
    unittest.main()
