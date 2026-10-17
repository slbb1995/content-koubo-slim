from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


FACTORY_ROOT = Path(__file__).resolve().parents[2]
SLIM_ROOT = FACTORY_ROOT / "Skills" / "content-koubo-slim"
if str(SLIM_ROOT) not in sys.path:
    sys.path.insert(0, str(SLIM_ROOT))
if str(SLIM_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(SLIM_ROOT / "scripts"))

from content_koubo_slim import (
    build_parser,
    record_direction_result,
    record_draft_result,
)
from runtime.run_store import RunStore
from runtime.state_machine import TRANSITIONS
from tests.p2.test_content_koubo_analyzer_p2 import (
    analyzer_result,
    current_task_key,
    only_task_record,
    prepare,
)
from tests.p3.test_content_koubo_context_p3 import (
    approved_p2_run,
    context_result,
    prepare_context_stage,
    record_context_result,
)
from tests.p4.test_content_koubo_writer_p4 import context_ready_run, writer_result


class P6IntegrationObservations(unittest.TestCase):
    def test_three_speaker_modes_cover_the_three_source_combinations(self) -> None:
        cases = (
            ("personal_ip", None, True, True),
            ("company_brand", ["客户服务判断"], True, False),
            ("neutral", [], False, False),
        )
        for mode, needs, expect_03, expect_05 in cases:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                registry, _, task_record, task_key = approved_p2_run(
                    root,
                    speaker_mode=mode,
                    business_needs=needs,
                )
                prepared, _ = prepare_context_stage(
                    registry_path=registry,
                    runs_root=root / "runs",
                    task_record=task_record,
                )
                result = context_result(prepared)
                self.assertTrue(result["selected_04_content_assets"])
                self.assertEqual(bool(result["selected_03_business_assets"]), expect_03)
                self.assertEqual(result["profile_context"] is not None, expect_05)
                record_context_result(
                    registry_path=registry,
                    runs_root=root / "runs",
                    task_record=task_record,
                    context_result=result,
                )
                run_dir = RunStore(root / "runs").run_directory(task_key)
                self.assertEqual(
                    len(list((run_dir / "artifacts").glob("content_context_v*.json"))), 1
                )

    def test_fundamental_audience_and_promise_change_keeps_one_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry, _, _, analyzer_input = prepare(
                root, reference_count=1, speaker_mode="personal_ip"
            )
            store = RunStore(root / "runs")
            task_key = current_task_key(root / "runs")
            task_record = only_task_record(root / "runs")
            record_direction_result(
                store=store,
                task_key=task_key,
                analyzer_result=analyzer_result(analyzer_input),
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SLIM_ROOT / "scripts" / "content_koubo_slim.py"),
                    "respond-direction",
                    "--registry",
                    str(registry),
                    "--runs-root",
                    str(root / "runs"),
                    "--task-record",
                    task_record,
                    "--decision",
                    "需要修改",
                    "--feedback",
                    "受众改成刚入行销售，核心承诺改成教成交话术",
                    "--task-identity-changed",
                ],
                check=False,
                text=True,
                capture_output=True,
                env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
            response = json.loads(completed.stdout)
            self.assertEqual(response["status"], "blocked")
            self.assertIn("新 Run", response["next_action"])
            self.assertEqual(store.get_task(task_key)["state"], "direction_pending")
            self.assertEqual(
                len([path for path in (root / "runs").glob("run-*") if path.is_dir()]), 1
            )
            self.assertFalse(
                (
                    store.run_directory(task_key)
                    / "artifacts"
                    / "analyzer_input_v2.json"
                ).exists()
            )

    def test_body_confirmation_response_has_no_internal_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, task_record, _ = context_ready_run(root)
            record_draft_result(
                runs_root=root / "runs",
                task_record=task_record,
                base_draft_version=0,
                writer_result=writer_result("ganhuo"),
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SLIM_ROOT / "scripts" / "content_koubo_slim.py"),
                    "respond-draft",
                    "--runs-root",
                    str(root / "runs"),
                    "--task-record",
                    task_record,
                    "--decision",
                    "确认正文",
                ],
                check=False,
                text=True,
                capture_output=True,
                env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            response = json.loads(completed.stdout)
            self.assertNotIn("writer_input", response)
            self.assertNotIn("draft_sha256", completed.stdout)
            self.assertNotIn("approval_version", completed.stdout)

    def test_stable_operation_surface_and_antibloat_limits(self) -> None:
        parser = build_parser()
        subparsers = next(
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        operations = set(subparsers.choices)
        stable = {
            "start",
            "respond-direction",
            "respond-draft",
            "respond-package",
            "status",
        }
        self.assertEqual(operations & stable, stable)
        self.assertLessEqual(len(operations & stable), 6)
        self.assertEqual(
            operations - stable,
            {
                "configure", "configure-feishu", "batch-status", "preflight", "discover-methods",
                "record-direction",
                "prepare-context",
                "record-context",
                "prepare-draft",
                "record-draft",
                "prepare-package",
                "record-package",
            },
        )
        self.assertEqual(
            set(TRANSITIONS),
            {
                "started",
                "direction_pending",
                "direction_approved",
                "context_pending",
                "context_ready",
                "draft_pending",
                "draft_approved",
                "package_pending",
                "package_approved",
                "blocked",
                "saved",
                "abandoned",
            },
        )
        runtime_text = "\n".join(
            path.read_text(encoding="utf-8") for path in SLIM_ROOT.rglob("*.py")
        )
        for legacy in (
            "content-writer-ganhuo",
            "content-writer-huati",
            "content-writer-zhuanhua",
            "viral-headline-creator",
            "content-distribution-pack",
            "content-save",
        ):
            self.assertNotIn(legacy, runtime_text)
        self.assertNotIn("analyzer_program.py", runtime_text)
        self.assertNotIn("reviewer", runtime_text.casefold())

    def test_project_state_records_p6_gate_before_p7_execution(self) -> None:
        state = json.loads((FACTORY_ROOT / "project-state.json").read_text(encoding="utf-8"))
        self.assertIn("P6", state["phase"]["passed_gates"])
        self.assertIn(state["phase"]["current"], {"P6", "P7"})


if __name__ == "__main__":
    unittest.main()
