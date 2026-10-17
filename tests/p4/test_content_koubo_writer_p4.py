from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


FACTORY_ROOT = Path(__file__).resolve().parents[2]
SLIM_ROOT = FACTORY_ROOT / "Skills" / "content-koubo-slim"
WRITER_ROOT = FACTORY_ROOT / "Skills" / "content-koubo-writer"
if str(SLIM_ROOT) not in sys.path:
    sys.path.insert(0, str(SLIM_ROOT))
if str(SLIM_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(SLIM_ROOT / "scripts"))

import content_koubo_slim
from content_koubo_slim import (
    prepare_context_stage,
    prepare_draft_stage,
    record_context_result,
    record_direction_result,
    record_draft_result,
    respond_direction,
    respond_draft,
)
from runtime.error_model import SlimRuntimeError
from runtime.run_store import RunStore
from runtime.state_machine import TRANSITIONS
from tests.p2.test_content_koubo_analyzer_p2 import (
    analyzer_result,
    current_task_key,
    only_task_record,
    prepare,
)
from tests.p3.test_content_koubo_context_p3 import context_result, write_p3_assets


def context_ready_run(
    root: Path, *, writer_mode: str = "ganhuo"
) -> tuple[Path, str, str]:
    registry, vault, _, analyzer_input = prepare(
        root, reference_count=2, speaker_mode="personal_ip"
    )
    write_p3_assets(vault)
    result = analyzer_result(analyzer_input)
    goal = {"ganhuo": "explain", "huati": "discuss", "zhuanhua": "convert"}[
        writer_mode
    ]
    reason = {
        "ganhuo": "核心目标是让普通人学会一套判断方法",
        "huati": "核心目标是把一个常见两难和背后的取舍说清楚",
        "zhuanhua": "核心目标是先解决问题，再自然承接一个后续动作",
    }[writer_mode]
    result["content_goal"] = goal
    result["writer_mode"] = writer_mode
    result["writer_mode_reason"] = reason
    result["customer_readable_direction"]["writer_recommendation"] = {
        "mode": writer_mode,
        "reason": reason,
    }
    store = RunStore(root / "runs")
    task_key = current_task_key(root / "runs")
    task_record = only_task_record(root / "runs")
    record_direction_result(store=store, task_key=task_key, analyzer_result=result)
    respond_direction(
        store=store,
        task_key=task_key,
        method_root=vault / "authorized-methods",
        decision="认可整版方向",
    )
    context_input, _ = prepare_context_stage(
        registry_path=registry,
        runs_root=root / "runs",
        task_record=task_record,
    )
    record_context_result(
        registry_path=registry,
        runs_root=root / "runs",
        task_record=task_record,
        context_result=context_result(context_input),
    )
    return registry, task_record, task_key


def writer_result(mode: str, *, revised: bool = False) -> dict:
    if mode == "ganhuo":
        paragraphs = [
            "普通家庭准备保障时，先别急着抄一张完整清单。先问自己：哪一种风险一旦发生，最容易打乱现在的生活？",
            "把最担心的情况写下来，再看家庭现有收入、储蓄和责任能不能承担。先问清需求，再核对具体责任和适用条件。",
        ]
    elif mode == "huati":
        paragraphs = [
            "有些人做保障功课时，会在灵活和确定之间反复犹豫。钱留在手里更方便，但也更容易被眼前的事情占用。",
            "这道题没有统一答案。更有用的是先承认自己的真实习惯，再决定愿意为长期安排放弃多少眼前的灵活。",
        ]
    else:
        paragraphs = [
            "做保障选择前，先把最可能影响家庭生活的风险按轻重排一遍。顺序清楚以后，才知道有限预算应该先解决什么。",
            "如果资料里还没有具体产品和责任，就先停在需求判断，不替自己补一个看似完整的方案。",
        ]
    if revised:
        paragraphs[1] = "先问清需求：这件事真发生时，家庭现有收入和储蓄能不能承担？答案会直接改变下一步先核对什么。"
    return {"paragraphs": [{"text": item} for item in paragraphs]}


class RealP4PathTests(unittest.TestCase):
    def test_real_blackbox_revision_confirmation_stops_before_p5(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, task_record, task_key = context_ready_run(root)
            prepare_result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SLIM_ROOT / "scripts" / "content_koubo_slim.py"),
                    "prepare-draft",
                    "--runs-root",
                    str(root / "runs"),
                    "--task-record",
                    task_record,
                ],
                check=False,
                text=True,
                capture_output=True,
                env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(prepare_result.returncode, 0, prepare_result.stdout)
            first_input = json.loads(prepare_result.stdout)["writer_input"]
            self.assertEqual(first_input["base_draft_version"], 0)
            self.assertEqual(first_input["mode_reference"], "references/modes/ganhuo.md")
            first_result = root / "writer-v1.json"
            first_result.write_text(
                json.dumps(writer_result("ganhuo"), ensure_ascii=False), encoding="utf-8"
            )
            record_first = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SLIM_ROOT / "scripts" / "content_koubo_slim.py"),
                    "record-draft",
                    "--runs-root",
                    str(root / "runs"),
                    "--task-record",
                    task_record,
                    "--base-draft-version",
                    "0",
                    "--writer-result",
                    str(first_result),
                ],
                check=False,
                text=True,
                capture_output=True,
                env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(record_first.returncode, 0, record_first.stdout)
            first_response = json.loads(record_first.stdout)
            self.assertEqual(first_response["draft"]["draft_version"], 1)
            store = RunStore(root / "runs")
            run_dir = store.run_directory(task_key)
            first_json = (run_dir / "artifacts" / "draft_v1.json").read_bytes()
            first_markdown = (run_dir / "artifacts" / "draft_v1.md").read_bytes()

            feedback = "第二段太绕，改成一个听完就能照着问的判断问题"
            revision = subprocess.run(
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
                    "需要修改",
                    "--feedback",
                    feedback,
                ],
                check=False,
                text=True,
                capture_output=True,
                env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(revision.returncode, 0, revision.stdout)
            revision_input = json.loads(revision.stdout)["writer_input"]
            self.assertEqual(revision_input["base_draft_version"], 1)
            self.assertEqual(revision_input["previous_draft"]["draft_version"], 1)
            self.assertEqual(revision_input["revision_request"], feedback)
            second_result = root / "writer-v2.json"
            second_result.write_text(
                json.dumps(writer_result("ganhuo", revised=True), ensure_ascii=False),
                encoding="utf-8",
            )
            record_second = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SLIM_ROOT / "scripts" / "content_koubo_slim.py"),
                    "record-draft",
                    "--runs-root",
                    str(root / "runs"),
                    "--task-record",
                    task_record,
                    "--base-draft-version",
                    "1",
                    "--writer-result",
                    str(second_result),
                    "--feedback",
                    feedback,
                ],
                check=False,
                text=True,
                capture_output=True,
                env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(record_second.returncode, 0, record_second.stdout)
            self.assertEqual((run_dir / "artifacts" / "draft_v1.json").read_bytes(), first_json)
            self.assertEqual((run_dir / "artifacts" / "draft_v1.md").read_bytes(), first_markdown)
            self.assertTrue((run_dir / "artifacts" / "draft_v2.json").is_file())
            self.assertTrue((run_dir / "artifacts" / "draft_v2.md").is_file())

            confirmed = subprocess.run(
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
            self.assertEqual(confirmed.returncode, 0, confirmed.stdout)
            self.assertNotIn("writer_input", json.loads(confirmed.stdout))
            self.assertNotIn("draft_sha256", confirmed.stdout)
            self.assertEqual(store.get_task(task_key)["state"], "draft_approved")
            approval = json.loads(
                (run_dir / "artifacts" / "approved_draft.json").read_text(encoding="utf-8")
            )
            self.assertEqual(approval["draft_version"], 2)
            names = {path.name for path in (run_dir / "artifacts").iterdir()}
            self.assertFalse(
                any(
                    token in name
                    for name in names
                    for token in ("package", "title", "tag", "publish", "save")
                )
            )

    def test_all_three_modes_load_only_the_frozen_mode_reference(self) -> None:
        for mode in ("ganhuo", "huati", "zhuanhua"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                _, task_record, _ = context_ready_run(root, writer_mode=mode)
                prepared, _ = prepare_draft_stage(
                    runs_root=root / "runs", task_record=task_record
                )
                self.assertEqual(prepared["content_context"]["writer_mode"], mode)
                self.assertEqual(prepared["mode_reference"], f"references/modes/{mode}.md")
                self.assertEqual(
                    [name for name in ("ganhuo", "huati", "zhuanhua") if name in prepared["mode_reference"]],
                    [mode],
                )
                record_draft_result(
                    runs_root=root / "runs",
                    task_record=task_record,
                    base_draft_version=0,
                    writer_result=writer_result(mode),
                )


class WriterBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        _, self.task_record, self.task_key = context_ready_run(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_prepare_draft_does_not_read_vault_or_call_legacy_writers(self) -> None:
        forbidden = (
            "read_method_asset",
            "read_primary_profile",
            "search_knowledge_assets",
            "search_method_assets",
        )
        patches = [
            mock.patch.object(
                content_koubo_slim, name, side_effect=AssertionError(f"P4 called {name}")
            )
            for name in forbidden
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        prepared, _ = prepare_draft_stage(
            runs_root=self.root / "runs", task_record=self.task_record
        )
        self.assertEqual(prepared["base_draft_version"], 0)
        runtime_text = "\n".join(
            path.read_text(encoding="utf-8") for path in SLIM_ROOT.rglob("*.py")
        )
        for legacy in (
            "content-writer-ganhuo",
            "content-writer-huati",
            "content-writer-zhuanhua",
        ):
            self.assertNotIn(legacy, runtime_text)

    def test_invalid_writer_output_keeps_context_ready_without_draft(self) -> None:
        with self.assertRaises(SlimRuntimeError) as caught:
            record_draft_result(
                runs_root=self.root / "runs",
                task_record=self.task_record,
                base_draft_version=0,
                writer_result={"paragraphs": [{"text": "正文"}], "title": "越界标题"},
            )
        self.assertEqual(caught.exception.error_code, "SLIM_WRITER_OUTPUT_INVALID")
        store = RunStore(self.root / "runs")
        self.assertEqual(store.get_task(self.task_key)["state"], "context_ready")
        self.assertFalse(any((store.run_directory(self.task_key) / "artifacts").glob("draft_v*")))

    def test_revision_requires_feedback_and_confirmation_rejects_feedback(self) -> None:
        record_draft_result(
            runs_root=self.root / "runs",
            task_record=self.task_record,
            base_draft_version=0,
            writer_result=writer_result("ganhuo"),
        )
        with self.assertRaises(SlimRuntimeError):
            respond_draft(
                runs_root=self.root / "runs",
                task_record=self.task_record,
                decision="需要修改",
            )
        with self.assertRaises(SlimRuntimeError):
            respond_draft(
                runs_root=self.root / "runs",
                task_record=self.task_record,
                decision="确认正文",
                feedback="同时修改",
            )

    def test_confirmation_detects_json_markdown_mismatch_and_stays_pending(self) -> None:
        record_draft_result(
            runs_root=self.root / "runs",
            task_record=self.task_record,
            base_draft_version=0,
            writer_result=writer_result("ganhuo"),
        )
        store = RunStore(self.root / "runs")
        markdown = store.run_directory(self.task_key) / "artifacts" / "draft_v1.md"
        markdown.write_text("被改过的正文\n", encoding="utf-8")
        with self.assertRaises(SlimRuntimeError) as caught:
            respond_draft(
                runs_root=self.root / "runs",
                task_record=self.task_record,
                decision="确认正文",
            )
        self.assertEqual(caught.exception.error_code, "SLIM_DRAFT_RESPONSE_INVALID")
        self.assertEqual(store.get_task(self.task_key)["state"], "draft_pending")
        self.assertFalse(
            (store.run_directory(self.task_key) / "artifacts" / "approved_draft.json").exists()
        )


class StructureAndReceiptTests(unittest.TestCase):
    def test_writer_skill_and_references_validate(self) -> None:
        validator = FACTORY_ROOT / "tools/quick_validate_skill.py"
        completed = subprocess.run(
            [sys.executable, "-B", str(validator), str(WRITER_ROOT)],
            cwd=FACTORY_ROOT,
            check=False,
            text=True,
            capture_output=True,
            env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(
            {path.name for path in (WRITER_ROOT / "references" / "modes").glob("*.md")},
            {"ganhuo.md", "huati.md", "zhuanhua.md"},
        )

    def test_p4_complexity_budget_remains_intact_during_p6(self) -> None:
        selection = json.loads(
            (FACTORY_ROOT / "packages" / "content-mainline.json").read_text(encoding="utf-8")
        )
        directories = {
            path.name
            for path in (FACTORY_ROOT / selection["source_root"]).iterdir()
            if path.is_dir()
        }
        self.assertEqual(
            directories - set(selection["skills"]),
            {
                "content-koubo-slim",
                "content-koubo-analyzer",
                "content-koubo-context-retriever",
                "content-koubo-writer",
                "content-koubo-publish-pack",
            },
        )
        runtime_modules = {path.name for path in (SLIM_ROOT / "runtime").glob("*.py")}
        self.assertNotIn("writer.py", runtime_modules)
        self.assertNotIn("draft_store.py", runtime_modules)
        self.assertIn("vault_save.py", runtime_modules)
        self.assertEqual(
            set(TRANSITIONS),
            {
                "started", "direction_pending", "direction_approved", "context_pending",
                "context_ready", "draft_pending", "draft_approved", "package_pending",
                "package_approved", "blocked", "saved", "abandoned",
            },
        )

    def test_historical_skill_creator_receipt_remains_verifiable(self) -> None:
        receipt_path = (
            FACTORY_ROOT
            / "designs"
            / "content-v2-slim"
            / "content-writer-skill-creator-receipt.json"
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        design = FACTORY_ROOT / "designs" / "content-v2-slim" / "content-writer-design-card.md"
        self.assertEqual(receipt["skill_name"], "content-writer")
        self.assertEqual(
            receipt["design_card_sha256"], hashlib.sha256(design.read_bytes()).hexdigest()
        )
        self.assertRegex(receipt["final_validation"]["skill_sha256"], r"^[0-9a-f]{64}$")

    def test_project_state_keeps_p4_through_p6_gate_history(self) -> None:
        state = json.loads((FACTORY_ROOT / "project-state.json").read_text(encoding="utf-8"))
        self.assertTrue({"P4", "P5", "P6"}.issubset(state["phase"]["passed_gates"]))
        self.assertIn(state["phase"]["current"], {"P6", "P7"})


if __name__ == "__main__":
    unittest.main()
