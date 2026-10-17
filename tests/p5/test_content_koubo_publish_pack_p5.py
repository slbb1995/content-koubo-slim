from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


FACTORY_ROOT = Path(__file__).resolve().parents[2]
SLIM_ROOT = FACTORY_ROOT / "Skills" / "content-koubo-slim"
PACK_ROOT = FACTORY_ROOT / "Skills" / "content-koubo-publish-pack"
if str(SLIM_ROOT) not in sys.path:
    sys.path.insert(0, str(SLIM_ROOT))
if str(SLIM_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(SLIM_ROOT / "scripts"))

from content_koubo_slim import (
    prepare_package_stage,
    record_draft_result,
    record_package_result,
    respond_draft,
    respond_package,
)
from runtime.error_model import SlimRuntimeError
from runtime.run_store import RunStore
from runtime.state_machine import TRANSITIONS
from runtime.vault_save import save_markdown_pair
from tests.p4.test_content_koubo_writer_p4 import context_ready_run, writer_result


def approved_draft_run(root: Path) -> tuple[Path, str, str]:
    registry, task_record, task_key = context_ready_run(root)
    record_draft_result(
        runs_root=root / "runs",
        task_record=task_record,
        base_draft_version=0,
        writer_result=writer_result("ganhuo"),
    )
    respond_draft(
        runs_root=root / "runs",
        task_record=task_record,
        decision="确认正文",
    )
    return registry, task_record, task_key


def package_result(*, revised: bool = False) -> dict:
    publish_titles = [
        "家庭保障为什么不能先抄清单",
        "有限预算先解决哪类风险",
        "做保障前先问清这一个问题",
    ]
    if revised:
        publish_titles[1] = "有限预算先排哪一种家庭风险"
    return {
        "cover_titles": ["保障别先抄清单", "家庭风险先排顺序"],
        "publish_titles": publish_titles,
        "recommended_cover_title": "家庭风险先排顺序",
        "recommended_publish_title": publish_titles[1],
        "publish_copy": (
            "准备家庭保障时，先判断哪类风险最可能打乱生活，再核对现有收入、"
            "储蓄和责任边界。顺序清楚以后，有限预算才知道先解决什么，也能避免照抄别人的清单。"
        ),
        "tags": ["#家庭保障", "#风险判断", "#预算顺序", "#保障需求", "#责任边界"],
    }


def platform_package_result(*, revised: bool = False) -> dict:
    old = package_result(revised=revised)
    return {
        "contract_version": "content-koubo-publish-pack-result-v2",
        "platforms": {platform: {"title": old["publish_titles"][index],
            "publish_copy": old["publish_copy"], "tags": old["tags"]}
            for index, platform in enumerate(("douyin", "xiaohongshu", "wechat_channels"))},
        "cover_texts": old["cover_titles"],
        "recommended_cover_text": old["recommended_cover_title"],
    }


def vault_from_registry(registry_path: Path) -> Path:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    return Path(registry["clients"]["client-alpha"]["vault_root"])


def output_root(vault: Path) -> Path:
    manifest = json.loads(
        (vault / "workflow-config" / "content-koubo-client-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    return vault / manifest["asset_roots"]["output"]


class RealP5PathTests(unittest.TestCase):
    def test_real_blackbox_revision_confirmation_saves_two_files_and_stops(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry, task_record, task_key = approved_draft_run(root)
            store = RunStore(root / "runs")
            run_dir = store.run_directory(task_key)
            approved_body_bytes = (run_dir / "artifacts" / "draft_v1.md").read_bytes()

            prepared = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SLIM_ROOT / "scripts" / "content_koubo_slim.py"),
                    "prepare-package",
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
            self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
            package_input = json.loads(prepared.stdout)["package_input"]
            self.assertEqual(package_input["base_package_version"], 0)
            self.assertEqual(
                package_input["approved_draft"]["body"].encode("utf-8") + b"\n",
                approved_body_bytes,
            )
            self.assertNotIn("content_context", package_input)

            first_result_path = root / "package-v1.json"
            first_result_path.write_text(
                json.dumps(platform_package_result(), ensure_ascii=False), encoding="utf-8"
            )
            first_record = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SLIM_ROOT / "scripts" / "content_koubo_slim.py"),
                    "record-package",
                    "--runs-root",
                    str(root / "runs"),
                    "--task-record",
                    task_record,
                    "--base-package-version",
                    "0",
                    "--package-result",
                    str(first_result_path),
                ],
                check=False,
                text=True,
                capture_output=True,
                env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(first_record.returncode, 0, first_record.stdout)
            first_package_bytes = (run_dir / "artifacts" / "package_v1.json").read_bytes()

            feedback = "小红书发布标题太抽象，改得更具体"
            revision = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SLIM_ROOT / "scripts" / "content_koubo_slim.py"),
                    "respond-package",
                    "--registry",
                    str(registry),
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
            revision_input = json.loads(revision.stdout)["package_input"]
            self.assertEqual(revision_input["base_package_version"], 1)
            self.assertEqual(revision_input["revision_request"], feedback)
            self.assertEqual(revision_input["previous_package"], platform_package_result())

            second_result_path = root / "package-v2.json"
            second_result_path.write_text(
                json.dumps(platform_package_result(revised=True), ensure_ascii=False), encoding="utf-8"
            )
            second_record = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SLIM_ROOT / "scripts" / "content_koubo_slim.py"),
                    "record-package",
                    "--runs-root",
                    str(root / "runs"),
                    "--task-record",
                    task_record,
                    "--base-package-version",
                    "1",
                    "--package-result",
                    str(second_result_path),
                    "--feedback",
                    feedback,
                ],
                check=False,
                text=True,
                capture_output=True,
                env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(second_record.returncode, 0, second_record.stdout)
            self.assertEqual(
                (run_dir / "artifacts" / "package_v1.json").read_bytes(),
                first_package_bytes,
            )
            self.assertEqual(
                (run_dir / "artifacts" / "draft_v1.md").read_bytes(), approved_body_bytes
            )

            confirmed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SLIM_ROOT / "scripts" / "content_koubo_slim.py"),
                    "respond-package",
                    "--registry",
                    str(registry),
                    "--runs-root",
                    str(root / "runs"),
                    "--task-record",
                    task_record,
                    "--decision",
                    "确认并保存",
                ],
                check=False,
                text=True,
                capture_output=True,
                env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(confirmed.returncode, 0, confirmed.stdout + confirmed.stderr)
            response = json.loads(confirmed.stdout)
            self.assertEqual(response["publish_status"], "not_requested")
            self.assertEqual(store.get_task(task_key)["state"], "saved")
            self.assertEqual(
                (run_dir / "artifacts" / "draft_v1.md").read_bytes(), approved_body_bytes
            )

            vault = vault_from_registry(registry)
            output_files = sorted(output_root(vault).rglob("*.md"))
            self.assertEqual(len(output_files), 2)
            oral_path = next(path for path in output_files if path.name.endswith("-口播稿.md"))
            package_path = next(
                path for path in output_files if path.name.endswith("-配套文案-第2版.md")
            )
            self.assertEqual(oral_path.read_bytes(), approved_body_bytes)
            package_text = package_path.read_text(encoding="utf-8")
            self.assertIn("封面文字（可选）：" + platform_package_result(revised=True)["recommended_cover_text"], package_text)
            self.assertIn("标题：有限预算先排哪一种家庭风险", package_text)
            self.assertNotIn(package_input["approved_draft"]["body"], package_text)
            artifact_names = {path.name for path in (run_dir / "artifacts").iterdir()}
            self.assertFalse(any("review" in name or "p6" in name for name in artifact_names))


class PublishPackBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry, self.task_record, self.task_key = approved_draft_run(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_invalid_output_cannot_create_package_or_change_confirmed_body(self) -> None:
        store = RunStore(self.root / "runs")
        run_dir = store.run_directory(self.task_key)
        body_before = (run_dir / "artifacts" / "draft_v1.md").read_bytes()
        invalid = package_result()
        invalid["body"] = "越权修改正文"
        with self.assertRaises(SlimRuntimeError) as caught:
            record_package_result(
                runs_root=self.root / "runs",
                task_record=self.task_record,
                base_package_version=0,
                package_result=invalid,
            )
        self.assertEqual(caught.exception.error_code, "SLIM_PACKAGE_OUTPUT_INVALID")
        self.assertEqual(store.get_task(self.task_key)["state"], "draft_approved")
        self.assertFalse(any((run_dir / "artifacts").glob("package_v*.json")))
        self.assertEqual((run_dir / "artifacts" / "draft_v1.md").read_bytes(), body_before)

    def test_registry_rebind_blocks_before_either_vault_is_written(self) -> None:
        record_package_result(
            runs_root=self.root / "runs",
            task_record=self.task_record,
            base_package_version=0,
            package_result=package_result(),
        )
        original_vault = vault_from_registry(self.registry)
        rebound_vault = self.root / "rebound-vault"
        shutil.copytree(original_vault, rebound_vault)
        rebound_registry = self.root / "rebound-registry.json"
        rebound_registry.write_text(
            json.dumps(
                {
                    "registry_version": "2.0",
                    "clients": {
                        "client-alpha": {
                            "vault_root": str(rebound_vault),
                            "manifest_relative_path": "workflow-config/content-koubo-client-manifest.json",
                        }
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        with self.assertRaises(SlimRuntimeError) as caught:
            respond_package(
                registry_path=rebound_registry,
                runs_root=self.root / "runs",
                task_record=self.task_record,
                decision="确认并保存",
            )
        self.assertEqual(caught.exception.error_code, "SLIM_TASK_IDENTITY_CHANGED")
        self.assertEqual(RunStore(self.root / "runs").get_task(self.task_key)["state"], "blocked")
        self.assertEqual(list(output_root(original_vault).rglob("*.md")), [])
        self.assertEqual(list(output_root(rebound_vault).rglob("*.md")), [])

    def test_save_readback_failure_rolls_back_both_new_files(self) -> None:
        output_root = self.root / "save-root"
        output_root.mkdir()
        with mock.patch.object(Path, "read_bytes", return_value=b"mismatch"):
            with self.assertRaises(SlimRuntimeError) as caught:
                save_markdown_pair(
                    output_root=output_root,
                    output_template="finished/{profile_or_brand}/weekly",
                    client_id="client-alpha",
                    selected_publish_title="家庭保障先排风险顺序",
                    oral_body="已确认正文",
                    package_markdown="封面标题：风险顺序\n\n发布标题：先排风险",
                )
        self.assertEqual(caught.exception.error_code, "SLIM_SAVE_FAILED")
        self.assertEqual(list(output_root.rglob("*.md")), [])

    def test_existing_target_is_not_overwritten_or_reported_saved(self) -> None:
        output_root = self.root / "existing-root"
        output_root.mkdir()
        first = save_markdown_pair(
            output_root=output_root,
            output_template="finished/{profile_or_brand}/weekly",
            client_id="client-alpha",
            selected_publish_title="家庭保障先排风险顺序",
            oral_body="已确认正文",
            package_markdown="封面标题：风险顺序\n\n发布标题：先排风险",
        )
        oral_before = first["oral_path"].read_bytes()
        package_before = first["package_path"].read_bytes()
        with self.assertRaises(SlimRuntimeError):
            save_markdown_pair(
                output_root=output_root,
                output_template="finished/{profile_or_brand}/weekly",
                client_id="client-alpha",
                selected_publish_title="家庭保障先排风险顺序",
                oral_body="不同正文",
                package_markdown="不同配套",
            )
        self.assertEqual(first["oral_path"].read_bytes(), oral_before)
        self.assertEqual(first["package_path"].read_bytes(), package_before)

    def test_save_retry_reuses_the_confirmed_package_without_regeneration(self) -> None:
        record_package_result(
            runs_root=self.root / "runs",
            task_record=self.task_record,
            base_package_version=0,
            package_result=package_result(),
        )
        vault = vault_from_registry(self.registry)
        target_dir = output_root(vault) / "finished" / "client-alpha" / "weekly"
        target_dir.mkdir(parents=True)
        blocked_target = target_dir / "有限预算先解决哪类风险-口播稿.md"
        blocked_target.write_text("预先存在\n", encoding="utf-8")
        with self.assertRaises(SlimRuntimeError) as caught:
            respond_package(
                registry_path=self.registry,
                runs_root=self.root / "runs",
                task_record=self.task_record,
                decision="确认并保存",
            )
        self.assertEqual(caught.exception.error_code, "SLIM_SAVE_FAILED")
        store = RunStore(self.root / "runs")
        self.assertEqual(store.get_task(self.task_key)["state"], "blocked")
        package_before = (
            store.run_directory(self.task_key) / "artifacts" / "package_v1.json"
        ).read_bytes()
        blocked_target.unlink()
        response, package_input = respond_package(
            registry_path=self.registry,
            runs_root=self.root / "runs",
            task_record=self.task_record,
            decision="确认并保存",
        )
        self.assertIsNone(package_input)
        self.assertEqual(response["publish_status"], "not_requested")
        self.assertEqual(store.get_task(self.task_key)["state"], "saved")
        self.assertEqual(
            (store.run_directory(self.task_key) / "artifacts" / "package_v1.json").read_bytes(),
            package_before,
        )
        self.assertEqual(len(list(output_root(vault).rglob("*.md"))), 2)

    def test_package_revision_requires_feedback_and_confirmation_rejects_feedback(self) -> None:
        record_package_result(
            runs_root=self.root / "runs",
            task_record=self.task_record,
            base_package_version=0,
            package_result=package_result(),
        )
        with self.assertRaises(SlimRuntimeError):
            respond_package(
                registry_path=self.registry,
                runs_root=self.root / "runs",
                task_record=self.task_record,
                decision="需要修改",
            )
        with self.assertRaises(SlimRuntimeError):
            respond_package(
                registry_path=self.registry,
                runs_root=self.root / "runs",
                task_record=self.task_record,
                decision="确认并保存",
                feedback="同时修改",
            )


class StructureAndReceiptTests(unittest.TestCase):
    def test_publish_pack_and_content_koubo_slim_skills_validate(self) -> None:
        validator = Path(
            str(FACTORY_ROOT / "tools/quick_validate_skill.py")
        )
        for skill_root in (PACK_ROOT, SLIM_ROOT):
            completed = subprocess.run(
                [sys.executable, "-B", str(validator), str(skill_root)],
                cwd=FACTORY_ROOT,
                check=False,
                text=True,
                capture_output=True,
                env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_p5_complexity_budget_remains_intact_during_p6(self) -> None:
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
        self.assertIn("vault_save.py", runtime_modules)
        self.assertTrue(
            {"publish.py", "package_store.py", "reviewer.py"}.isdisjoint(runtime_modules)
        )
        self.assertEqual(
            {path.name for path in (SLIM_ROOT / "schemas").glob("*.json")},
            {"client-registry.schema.json", "content-koubo-client-manifest.schema.json",
             "knowledge-base-registry.schema.json", "content-profile-index.schema.json", "content-source-manifest.schema.json"},
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
        for legacy in ("viral-headline-creator", "content-distribution-pack", "content-save"):
            self.assertNotIn(legacy, runtime_text)
        self.assertNotIn("subprocess", (SLIM_ROOT / "runtime" / "vault_save.py").read_text())
        self.assertTrue((FACTORY_ROOT / "PHASE-P7.md").is_file())

    def test_historical_skill_creator_receipt_remains_verifiable(self) -> None:
        receipt = json.loads(
            (
                FACTORY_ROOT
                / "designs"
                / "content-v2-slim"
                / "content-publish-pack-skill-creator-receipt.json"
            ).read_text(encoding="utf-8")
        )
        design = (
            FACTORY_ROOT
            / "designs"
            / "content-v2-slim"
            / "content-publish-pack-design-card.md"
        )
        self.assertEqual(receipt["skill_name"], "content-publish-pack")
        self.assertEqual(
            receipt["design_card_sha256"], hashlib.sha256(design.read_bytes()).hexdigest()
        )
        self.assertRegex(receipt["final_validation"]["skill_sha256"], r"^[0-9a-f]{64}$")

    def test_project_state_keeps_p5_and_p6_gate_history(self) -> None:
        state = json.loads((FACTORY_ROOT / "project-state.json").read_text(encoding="utf-8"))
        self.assertTrue({"P5", "P6"}.issubset(state["phase"]["passed_gates"]))
        self.assertIn(state["phase"]["current"], {"P6", "P7"})


if __name__ == "__main__":
    unittest.main()
