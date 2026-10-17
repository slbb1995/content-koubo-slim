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
SKILL_ROOT = FACTORY_ROOT / "Skills" / "content-koubo-slim"
FIXTURE_ROOT = FACTORY_ROOT / "tests" / "fixtures" / "content-koubo-slim"
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from runtime.client_manifest import (
    SUPPORTED_SPEAKER_MODES,
    build_migration_candidate,
    resolve_speaker_mode,
    validate_manifest,
)
from runtime.client_registry import load_registry, resolve_client
from runtime.error_model import SlimRuntimeError
from runtime.run_store import RunStore
from runtime.state_machine import TRANSITIONS


def manifest_data(client_id: str = "client-alpha") -> dict:
    return {
        "contract_version": "2.0",
        "client_id": client_id,
        "asset_roots": {
            "knowledge": "knowledge-data",
            "method": "method-data",
            "profile": "profile-data",
            "output": "output-data",
        },
        "default_speaker_mode": "personal_ip",
        "allowed_speaker_modes": list(SUPPORTED_SPEAKER_MODES),
        "profile_policy": {
            "required_when": ["personal_ip"],
            "selector": {"status": "active", "is_primary": True},
        },
        "default_platform": "short_video",
        "output_template": "finished/{profile_or_brand}/weekly",
    }


def write_generic_client(root: Path, client_id: str = "client-alpha") -> tuple[Path, Path]:
    vault = root / "generic-vault"
    config_dir = vault / "workflow-config"
    config_dir.mkdir(parents=True)
    for asset_root in ("knowledge-data", "method-data", "profile-data", "output-data"):
        (vault / asset_root).mkdir()
    manifest_path = config_dir / "content-koubo-client-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_data(client_id), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    registry = {
        "registry_version": "2.0",
        "clients": {
            client_id: {
                "vault_root": str(vault),
                "manifest_relative_path": "workflow-config/content-koubo-client-manifest.json",
            }
        },
    }
    registry_path = root / "registry.json"
    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return registry_path, vault


def start_trusted_task(
    store: RunStore, *, task_key: str, client_id: str, speaker_mode: str
) -> tuple[dict, bool]:
    return store.start_task(
        task_key=task_key,
        task_key_generated_by="host",
        task_key_record=f"host-managed:{task_key}",
        client_id=client_id,
        speaker_mode=speaker_mode,
    )


class RegistryManifestTests(unittest.TestCase):
    def test_registry_only_contains_locator_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            registry_path, _ = write_generic_client(Path(temp))
            registry = load_registry(registry_path)
            self.assertEqual(
                set(registry["clients"]["client-alpha"]),
                {"vault_root", "manifest_relative_path"},
            )

    def test_registry_rejects_client_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            registry_path, _ = write_generic_client(Path(temp))
            data = json.loads(registry_path.read_text(encoding="utf-8"))
            data["clients"]["client-alpha"]["speaker_mode"] = "personal_ip"
            registry_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(SlimRuntimeError) as caught:
                load_registry(registry_path)
            self.assertEqual(caught.exception.error_code, "SLIM_REGISTRY_NOT_READABLE")

    def test_registry_resolves_manifest_below_vault(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            registry_path, vault = write_generic_client(Path(temp))
            location = resolve_client(load_registry(registry_path), "client-alpha")
            self.assertEqual(location.vault_root, vault.resolve())
            location.manifest_path.relative_to(vault.resolve())

    def test_registry_rejects_manifest_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            registry_path, _ = write_generic_client(Path(temp))
            data = json.loads(registry_path.read_text(encoding="utf-8"))
            data["clients"]["client-alpha"]["manifest_relative_path"] = "../outside.json"
            registry_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(SlimRuntimeError):
                load_registry(registry_path)

    def test_all_three_speaker_modes_resolve(self) -> None:
        manifest = validate_manifest(manifest_data())
        self.assertEqual(
            [resolve_speaker_mode(mode, manifest) for mode in SUPPORTED_SPEAKER_MODES],
            list(SUPPORTED_SPEAKER_MODES),
        )

    def test_only_personal_ip_requires_profile(self) -> None:
        manifest = validate_manifest(manifest_data())
        self.assertTrue(manifest.requires_profile("personal_ip"))
        self.assertFalse(manifest.requires_profile("company_brand"))
        self.assertFalse(manifest.requires_profile("neutral"))

    def test_manifest_rejects_physical_path_escape(self) -> None:
        data = manifest_data()
        data["asset_roots"]["knowledge"] = "../outside"
        with self.assertRaises(SlimRuntimeError) as caught:
            validate_manifest(data)
        self.assertEqual(caught.exception.error_code, "SLIM_MANIFEST_INVALID")

    def test_manifest_rejects_client_mismatch(self) -> None:
        with self.assertRaises(SlimRuntimeError):
            validate_manifest(manifest_data(), expected_client_id="different-client")

    def test_schema_files_are_valid_json_and_generic(self) -> None:
        schema_root = SKILL_ROOT / "schemas"
        registry_schema = json.loads(
            (schema_root / "client-registry.schema.json").read_text(encoding="utf-8")
        )
        manifest_schema = json.loads(
            (schema_root / "content-koubo-client-manifest.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(registry_schema["properties"]["registry_version"]["const"], "2.0")
        self.assertEqual(
            set(manifest_schema["properties"]["default_speaker_mode"]["enum"]),
            set(SUPPORTED_SPEAKER_MODES),
        )


class MigrationCandidateTests(unittest.TestCase):
    def test_generic_v1_fixture_projects_only_v2_fields(self) -> None:
        source = json.loads(
            (FIXTURE_ROOT / "generic-v1-client-config.json").read_text(encoding="utf-8")
        )
        candidate = build_migration_candidate(source, default_speaker_mode="personal_ip")
        self.assertEqual(set(candidate), {
            "contract_version",
            "client_id",
            "asset_roots",
            "default_speaker_mode",
            "allowed_speaker_modes",
            "profile_policy",
            "default_platform",
            "output_template",
        })
        self.assertNotIn("profile_aliases", candidate)
        self.assertNotIn("method_selection_policy", candidate)
        self.assertEqual(candidate["output_template"], "finished/{profile_or_brand}/weekly")

    def test_default_p1_test_source_has_no_real_client_path(self) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertNotIn("CONTENT_" + "V1_CONFIG_UNDER_TEST", source)


class RunStoreStateTests(unittest.TestCase):
    def test_run_store_exposes_one_cross_process_lock(self) -> None:
        self.assertTrue(hasattr(RunStore, "_exclusive_lock"))

    def test_start_transition_and_version_use_the_same_lock_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = RunStore(Path(temp) / "runs")
            with mock.patch.object(
                store, "_exclusive_lock", wraps=store._exclusive_lock
            ) as lock:
                start_trusted_task(store,
                    task_key="stable-task", client_id="client-alpha", speaker_mode="neutral"
                )
                store.transition("stable-task", "direction_pending")
                store.write_version("stable-task", "direction", {"value": "first"})
            self.assertEqual(lock.call_count, 3)

    def test_two_processes_start_one_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry_path, _ = write_generic_client(root)
            runs_root = root / "runs"
            reference = root / "reference.md"
            reference.write_text("# Sample\n\nUseful reference text.\n", encoding="utf-8")
            command = [
                sys.executable,
                "-B",
                str(SKILL_ROOT / "scripts" / "content_koubo_slim.py"),
                "start", "--analysis-version", "slim-1.0",
                "--registry",
                str(registry_path),
                "--runs-root",
                str(runs_root),
                "--client-id",
                "client-alpha",
                "--speaker-mode",
                "neutral",
                "--topic-original",
                "Original topic",
                "--reference",
                str(reference),
            ]
            processes = [
                subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                for _ in range(2)
            ]
            results = [process.communicate(timeout=10) for process in processes]
            self.assertEqual([process.returncode for process in processes], [0, 0])
            responses = [json.loads(stdout) for stdout, _ in results]
            self.assertEqual(
                sorted(item["run_created_now"] for item in responses), [False, True]
            )
            self.assertEqual(sum(path.is_dir() for path in runs_root.glob("run-*")), 1)

    def test_same_task_key_reuses_one_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "runs"
            store = RunStore(root)
            first, first_created = start_trusted_task(store,
                task_key="stable-task", client_id="client-alpha", speaker_mode="neutral"
            )
            second, second_created = start_trusted_task(store,
                task_key="stable-task", client_id="client-alpha", speaker_mode="neutral"
            )
            self.assertTrue(first_created)
            self.assertFalse(second_created)
            self.assertEqual(first["run_id"], second["run_id"])
            self.assertEqual(sum(path.is_dir() for path in root.glob("run-*")), 1)

    def test_same_task_key_cannot_switch_client(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = RunStore(Path(temp) / "runs")
            start_trusted_task(store,
                task_key="stable-task", client_id="client-alpha", speaker_mode="neutral"
            )
            with self.assertRaises(SlimRuntimeError):
                start_trusted_task(store,
                    task_key="stable-task", client_id="client-beta", speaker_mode="neutral"
                )

    def test_same_task_key_cannot_switch_speaker_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = RunStore(Path(temp) / "runs")
            start_trusted_task(store,
                task_key="stable-task", client_id="client-alpha", speaker_mode="neutral"
            )
            with self.assertRaises(SlimRuntimeError):
                start_trusted_task(store,
                    task_key="stable-task",
                    client_id="client-alpha",
                    speaker_mode="company_brand",
                )

    def test_interrupted_start_recovers_existing_unindexed_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "runs"
            store = RunStore(root)
            with mock.patch.object(store, "_replace_json", side_effect=OSError("interrupted")):
                with self.assertRaises((OSError, SlimRuntimeError)):
                    start_trusted_task(store,
                        task_key="stable-task",
                        client_id="client-alpha",
                        speaker_mode="neutral",
                    )
            first_run = next(path for path in root.glob("run-*") if path.is_dir())
            recovered, created = start_trusted_task(RunStore(root),
                task_key="stable-task", client_id="client-alpha", speaker_mode="neutral"
            )
            self.assertFalse(created)
            self.assertEqual(recovered["run_id"], first_run.name)
            self.assertEqual(sum(path.is_dir() for path in root.glob("run-*")), 1)

    def test_multiple_unindexed_candidates_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "runs"
            store = RunStore(root)
            with mock.patch.object(store, "_replace_json", side_effect=OSError("interrupted")):
                with self.assertRaises((OSError, SlimRuntimeError)):
                    start_trusted_task(store,
                        task_key="stable-task",
                        client_id="client-alpha",
                        speaker_mode="neutral",
                    )
            first_run = next(path for path in root.glob("run-*") if path.is_dir())
            second_run = root / "run-20000101T000000.000000Z-deadbeef"
            shutil.copytree(first_run, second_run)
            second_state_path = second_run / "state.json"
            second_state = json.loads(second_state_path.read_text(encoding="utf-8"))
            second_state["run_id"] = second_run.name
            second_state_path.write_text(json.dumps(second_state), encoding="utf-8")
            with self.assertRaises(SlimRuntimeError) as caught:
                start_trusted_task(RunStore(root),
                    task_key="stable-task",
                    client_id="client-alpha",
                    speaker_mode="neutral",
                )
            self.assertIn("multiple unindexed Runs", caught.exception.detail)

    def test_index_rejects_run_id_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "runs"
            root.mkdir()
            outside = Path(temp) / "outside"
            outside.mkdir()
            digest = RunStore._task_digest("stable-task")
            (outside / "state.json").write_text(
                json.dumps({"task_key_sha256": digest}), encoding="utf-8"
            )
            (root / "run-index.json").write_text(
                json.dumps({"store_version": "2.0", "tasks": {digest: "../outside"}}),
                encoding="utf-8",
            )
            with self.assertRaises(SlimRuntimeError):
                RunStore(root).get_task("stable-task")

    def test_version_chain_is_create_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = RunStore(Path(temp) / "runs")
            start_trusted_task(store,
                task_key="stable-task", client_id="client-alpha", speaker_mode="neutral"
            )
            v1 = store.write_version("stable-task", "direction", {"value": "first"})
            v2 = store.write_version("stable-task", "direction", {"value": "second"})
            self.assertEqual(v1.name, "direction_v1.json")
            self.assertEqual(v2.name, "direction_v2.json")
            self.assertEqual(json.loads(v1.read_text(encoding="utf-8"))["value"], "first")

    def test_failed_version_write_leaves_no_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "runs"
            store = RunStore(root)
            state, _ = start_trusted_task(store,
                task_key="stable-task", client_id="client-alpha", speaker_mode="neutral"
            )
            with self.assertRaises(SlimRuntimeError):
                store.write_version("stable-task", "direction", {"bad": object()})
            artifact_dir = root / state["run_id"] / "artifacts"
            self.assertEqual(list(artifact_dir.iterdir()), [])

    def test_state_machine_allows_declared_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = RunStore(Path(temp) / "runs")
            start_trusted_task(store,
                task_key="stable-task", client_id="client-alpha", speaker_mode="neutral"
            )
            self.assertEqual(store.transition("stable-task", "direction_pending")["state"], "direction_pending")
            self.assertEqual(store.transition("stable-task", "direction_approved")["state"], "direction_approved")

    def test_state_machine_rejects_skipping_human_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = RunStore(Path(temp) / "runs")
            start_trusted_task(store,
                task_key="stable-task", client_id="client-alpha", speaker_mode="neutral"
            )
            with self.assertRaises(SlimRuntimeError) as caught:
                store.transition("stable-task", "draft_pending")
            self.assertEqual(caught.exception.error_code, "SLIM_STATE_TRANSITION_INVALID")

    def test_every_blockable_state_resumes_to_itself(self) -> None:
        paths = {
            "started": [],
            "direction_pending": ["direction_pending"],
            "direction_approved": ["direction_pending", "direction_approved"],
            "context_pending": ["direction_pending", "direction_approved", "context_pending"],
            "context_ready": [
                "direction_pending",
                "direction_approved",
                "context_pending",
                "context_ready",
            ],
            "draft_pending": [
                "direction_pending",
                "direction_approved",
                "context_pending",
                "context_ready",
                "draft_pending",
            ],
            "draft_approved": [
                "direction_pending",
                "direction_approved",
                "context_pending",
                "context_ready",
                "draft_pending",
                "draft_approved",
            ],
            "package_pending": [
                "direction_pending",
                "direction_approved",
                "context_pending",
                "context_ready",
                "draft_pending",
                "draft_approved",
                "package_pending",
            ],
            "package_approved": [
                "direction_pending",
                "direction_approved",
                "context_pending",
                "context_ready",
                "draft_pending",
                "draft_approved",
                "package_pending",
                "package_approved",
            ],
        }
        blockable = {state for state, targets in TRANSITIONS.items() if "blocked" in targets}
        self.assertEqual(blockable, set(TRANSITIONS["blocked"]))
        self.assertEqual(blockable, set(paths))
        for original_state, path in paths.items():
            with self.subTest(original_state=original_state), tempfile.TemporaryDirectory() as temp:
                store = RunStore(Path(temp) / "runs")
                start_trusted_task(store,
                    task_key="stable-task", client_id="client-alpha", speaker_mode="neutral"
                )
                for target in path:
                    store.transition("stable-task", target)
                self.assertEqual(store.transition("stable-task", "blocked")["state"], "blocked")
                self.assertEqual(
                    store.transition("stable-task", original_state)["state"], original_state
                )


class EntryErrorAndEvidenceTests(unittest.TestCase):
    def test_error_model_separates_user_and_technical_fields(self) -> None:
        error = SlimRuntimeError(
            "SLIM_MANIFEST_INVALID",
            "client_manifest",
            detail="technical detail",
            workflow_stage="任务准备",
            run_exists=False,
            run_created_now=False,
            artifacts_exist=False,
            artifacts_preserved=False,
            technical_report_path="internal/report.json",
        )
        user = error.user_response()
        technical = error.technical_record()
        self.assertNotIn("error_code", user)
        self.assertNotIn("technical_report_path", user)
        self.assertNotIn("client_manifest", user.values())
        self.assertEqual(user["workflow_stage"], "任务准备")
        self.assertFalse(user["run_exists"])
        self.assertFalse(user["run_created_now"])
        self.assertFalse(user["artifacts_exist"])
        self.assertFalse(user["artifacts_preserved"])
        self.assertNotIn("已有产物已保留", user["message"])
        self.assertEqual(technical["error_code"], "SLIM_MANIFEST_INVALID")
        self.assertEqual(technical["component"], "client_manifest")
        self.assertEqual(technical["detail"], "technical detail")
        self.assertEqual(technical["technical_report_path"], "internal/report.json")

    def test_skill_has_required_human_and_ai_readable_structure(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        required_headings = [
            "## 一句话目的",
            "## 什么时候使用",
            "## 什么时候不要使用",
            "## 输入",
            "## 输出",
            "## 执行流程",
            "## 真人停点",
            "## 错误与停止",
            "## 禁止事项",
            "## 最小示例",
            "## 文件导航",
        ]
        self.assertEqual([heading for heading in required_headings if heading not in skill], [])

    def test_master_and_compass_define_dual_readability(self) -> None:
        master = (FACTORY_ROOT / "CONTENT-V2-SLIM-FULL-CYCLE-SPEC.md").read_text(
            encoding="utf-8"
        )
        compass = (FACTORY_ROOT / "SLIM-COMPASS.md").read_text(encoding="utf-8")
        for document in (master, compass):
            self.assertIn("同时服务人类理解与 AI 执行", document)
            self.assertIn("设计原因进设计卡", document)
            self.assertIn("细节进 references", document)
            self.assertIn("实现进 runtime", document)
            self.assertIn("字段进 schemas", document)

    def test_agent_ui_metadata_is_chinese_and_mentions_skill(self) -> None:
        metadata = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertRegex(metadata, r"[一-龥]")
        self.assertIn("$content-koubo-slim", metadata)

    def test_cli_start_reuses_run_and_status_is_plain_language(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry_path, _ = write_generic_client(root)
            runs_root = root / "runs"
            reference = root / "reference.md"
            reference.write_text("# Sample\n\nUseful reference text.\n", encoding="utf-8")
            command = [
                sys.executable,
                "-B",
                str(SKILL_ROOT / "scripts" / "content_koubo_slim.py"),
                "start", "--analysis-version", "slim-1.0",
                "--registry",
                str(registry_path),
                "--runs-root",
                str(runs_root),
                "--client-id",
                "client-alpha",
                "--speaker-mode",
                "company_brand",
                "--topic-original",
                "Original topic",
                "--reference",
                str(reference),
            ]
            first = subprocess.run(command, check=False, text=True, capture_output=True)
            second = subprocess.run(command, check=False, text=True, capture_output=True)
            self.assertEqual((first.returncode, second.returncode), (0, 0))
            self.assertTrue(json.loads(first.stdout)["run_created_now"])
            self.assertFalse(json.loads(second.stdout)["run_created_now"])
            self.assertNotIn(str(root), first.stdout)

    def test_historical_skill_creator_receipt_remains_verifiable(self) -> None:
        receipt_path = (
            FACTORY_ROOT
            / "designs"
            / "content-v2-slim"
            / "content-slim-skill-creator-receipt.json"
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        design_path = (
            FACTORY_ROOT / "designs" / "content-v2-slim" / "content-slim-design-card.md"
        )
        design_hash = hashlib.sha256(design_path.read_bytes()).hexdigest()
        self.assertEqual(receipt["exit_code"], 0)
        self.assertEqual(receipt["skill_name"], "content-slim")
        self.assertEqual(receipt["design_card_sha256"], design_hash)
        self.assertIn("initialized successfully", receipt["initializer_output"])
        self.assertEqual(receipt["structural_updates"][-1]["exit_code"], 0)
        self.assertIn("generate_openai_yaml.py", receipt["structural_updates"][-1]["command"])
        self.assertTrue(receipt["structural_updates"][-1]["changes"])
        self.assertRegex(
            receipt["structural_updates"][-1]["final_skill_sha256"], r"^[0-9a-f]{64}$"
        )

    def test_only_approved_slim_skills_are_new_beside_v1_package_selection(self) -> None:
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

    def test_runtime_has_no_old_v1_skill_dependency(self) -> None:
        old_skill_names = json.loads(
            (FACTORY_ROOT / "packages" / "content-mainline.json").read_text(encoding="utf-8")
        )["skills"]
        production_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in SKILL_ROOT.rglob("*")
            if path.is_file() and path.suffix in {".md", ".py", ".json", ".yaml"}
        )
        self.assertEqual([name for name in old_skill_names if name in production_text], [])

    def test_runtime_has_no_customer_industry_or_absolute_path_hardcode(self) -> None:
        production_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in SKILL_ROOT.rglob("*")
            if path.is_file() and path.suffix in {".md", ".py", ".json", ".yaml"}
        )
        forbidden_literals = [
            "朱梅燕",
            "保险",
            "PROFILE-001",
            "/Users/",
            "/home/",
        ]
        self.assertEqual([item for item in forbidden_literals if item in production_text], [])
        # Public folder defaults belong only to explicit common-source configuration;
        # execution still resolves logical roots through the frozen Manifest.
        for path in SKILL_ROOT.rglob("*.py"):
            if path.name != "content_source.py":
                text = path.read_text(encoding="utf-8")
                self.assertFalse(any(name in text for name in ("03-业务知识库", "04-内容方法库", "05-IP-Profile")), path)



if __name__ == "__main__":
    unittest.main()
