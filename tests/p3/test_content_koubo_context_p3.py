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
CONTEXT_ROOT = (
    FACTORY_ROOT / "Skills" / "content-koubo-context-retriever"
)
if str(SLIM_ROOT) not in sys.path:
    sys.path.insert(0, str(SLIM_ROOT))
if str(SLIM_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(SLIM_ROOT / "scripts"))

import content_koubo_slim
from content_koubo_slim import prepare_context_stage, record_context_result
from runtime.error_model import SlimRuntimeError
from runtime.run_store import RunStore
from runtime.schema_validation import SOURCE_ROLE_POLICY, validate_content_context
from runtime.state_machine import TRANSITIONS
from runtime.vault_reader import read_primary_profile
from tests.p2.test_content_koubo_analyzer_p2 import (
    analyzer_result,
    current_task_key,
    only_task_record,
    prepare,
    record_direction_result,
    respond_direction,
)


def write_p3_assets(vault: Path, *, include_profile: bool = True) -> None:
    (vault / "private-business" / "product-service.md").write_text(
        "# 客户服务判断\n\n涉及具体产品前，先核对家庭需求、责任边界和服务适用条件。\n\n"
        "客户资料没有提供统一收益承诺，也没有授权虚构案例。\n",
        encoding="utf-8",
    )
    if include_profile:
        (vault / "private-profile" / "primary.md").write_text(
            "---\nstatus: active\nis_primary: true\n---\n"
            "# 当前主 Profile\n\n"
            "## 本人确认事实\n\n讲述者已确认长期帮助普通家庭梳理保障需求。\n\n"
            "## 项目设定\n\n表达保持克制，不制造焦虑。\n\n"
            "## 候选素材\n\n一次没有完整证据的服务片段，只能作为候选素材。\n",
            encoding="utf-8",
        )


def approved_p2_run(
    root: Path,
    *,
    speaker_mode: str = "personal_ip",
    business_needs: list[str] | None = None,
    include_profile: bool = True,
) -> tuple[Path, Path, str, str]:
    registry, vault, _, analyzer_input = prepare(
        root, reference_count=2, speaker_mode=speaker_mode
    )
    write_p3_assets(vault, include_profile=include_profile)
    result = analyzer_result(analyzer_input)
    if business_needs is not None:
        result["business_context_needs"] = business_needs
    store = RunStore(root / "runs")
    task_key = current_task_key(root / "runs")
    record_direction_result(store=store, task_key=task_key, analyzer_result=result)
    respond_direction(
        store=store,
        task_key=task_key,
        method_root=vault / "authorized-methods",
        decision="认可整版方向",
    )
    return registry, vault, only_task_record(root / "runs"), task_key


def context_result(context_input: dict) -> dict:
    content_assets: list[dict] = []
    method_assets: list[dict] = []
    boundary = context_input["approved_direction"]["generalization_boundary"]
    for asset in context_input["selected_04_assets"]:
        target = content_assets if asset["asset_role"] == "peer_content_asset" else method_assets
        writer_context = (
            "用通用问题顺序帮助普通家庭判断，不借用同行身份、业务或案例。"
            if asset["asset_role"] == "peer_content_asset"
            else "采用误区、判断标准和收束提醒的通用口播推进方式。"
        )
        target.append(
            {
                "asset_id": asset["asset_id"],
                "relative_path": asset["relative_path"],
                "source_role": asset["asset_role"],
                "approved_usage": asset["approved_usage"],
                "writer_context": writer_context,
                "transfer_boundary": boundary,
            }
        )
    business_assets = []
    if context_input["knowledge_candidates"]:
        item = context_input["knowledge_candidates"][0]
        business_assets.append(
            {
                "relative_path": item["relative_path"],
                "source_role": "client_business",
                "excerpt": item["excerpt"],
                "usage": "只在涉及具体产品时支撑核对需求和适用条件的提醒。",
            }
        )
    profile_context = None
    if context_input["speaker_mode"] == "personal_ip":
        profile_context = {
            "relative_path": context_input["profile_candidate"]["relative_path"],
            "source_role": "client_profile",
            "selected_passages": ["讲述者已确认长期帮助普通家庭梳理保障需求。"],
            "usage": "用于限定讲述者可确认的身份背景，不扩写案例。",
        }
    task = context_input["task_input"]
    approved = context_input["approved_direction"]
    return {
        "context_version": "slim-1.0",
        "client_id": context_input["client_id"],
        "speaker_mode": context_input["speaker_mode"],
        "topic_original": task["topic_original"],
        "target_audience": approved["target_audience"],
        "approved_direction": approved,
        "user_thoughts": task["user_thoughts"],
        "must_keep": task["must_keep"],
        "must_avoid": task["must_avoid"],
        "selected_external_reference_mechanisms": context_input[
            "selected_external_reference_mechanisms"
        ],
        "selected_04_content_assets": content_assets,
        "selected_04_method_assets": method_assets,
        "selected_03_business_assets": business_assets,
        "profile_context": profile_context,
        "source_role_policy": dict(SOURCE_ROLE_POLICY),
        "writer_mode": context_input["writer_mode"],
        "secondary_tactics": context_input["secondary_tactics"],
    }


class RealP3PathTests(unittest.TestCase):
    def test_profile_reader_accepts_unrelated_json_object_lists(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "primary.md").write_text(
                "---\n"
                "status: active\n"
                "is_primary: true\n"
                "cta_grants:\n"
                "  - {\"grant_id\":\"CTA-001\",\"usage_scope\":\"internal_test\"}\n"
                "---\n"
                "# 当前主 Profile\n\n"
                "## 本人确认事实\n\n只使用已确认事实。\n",
                encoding="utf-8",
            )
            profile = read_primary_profile(
                root, {"status": "active", "is_primary": True}
            )
            self.assertEqual(profile.relative_path, "primary.md")

    def test_real_personal_ip_path_creates_one_context_pack_and_stops(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry, _, task_record, task_key = approved_p2_run(root)
            prepare_result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SLIM_ROOT / "scripts" / "content_koubo_slim.py"),
                    "prepare-context",
                    "--registry",
                    str(registry),
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
            self.assertEqual(prepare_result.returncode, 0, prepare_result.stdout + prepare_result.stderr)
            context_input = json.loads(prepare_result.stdout)["context_input"]
            self.assertEqual(
                {item["asset_role"] for item in context_input["selected_04_assets"]},
                {"peer_content_asset", "oral_method_asset"},
            )
            self.assertEqual(len(context_input["knowledge_candidates"]), 1)
            self.assertIsNotNone(context_input["profile_candidate"])
            result_path = root / "context-result.json"
            result_path.write_text(
                json.dumps(context_result(context_input), ensure_ascii=False), encoding="utf-8"
            )
            record_result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SLIM_ROOT / "scripts" / "content_koubo_slim.py"),
                    "record-context",
                    "--registry",
                    str(registry),
                    "--runs-root",
                    str(root / "runs"),
                    "--task-record",
                    task_record,
                    "--context-result",
                    str(result_path),
                ],
                check=False,
                text=True,
                capture_output=True,
                env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(record_result.returncode, 0, record_result.stdout + record_result.stderr)
            response = json.loads(record_result.stdout)
            store = RunStore(root / "runs")
            context_path = store.run_directory(task_key) / "artifacts" / "content_context_v1.json"
            self.assertEqual(context_path.name, "content_context_v1.json")
            self.assertEqual(store.get_task(task_key)["state"], "context_ready")
            self.assertIn("唯一 Content Context Pack 已生成", response["message"])
            self.assertIn("尚未生成正文", response["message"])
            names = {
                path.name for path in (store.run_directory(task_key) / "artifacts").iterdir()
            }
            self.assertEqual([name for name in names if "content_context" in name], ["content_context_v1.json"])
            self.assertFalse(any("draft" in name or "title" in name or name.endswith(".md") for name in names))
            saved = json.loads(context_path.read_text(encoding="utf-8"))
            self.assertNotIn(str(root), context_path.read_text(encoding="utf-8"))
            self.assertFalse(any(repr(item["page_sha256"]) in repr(saved) for item in context_input["selected_04_assets"]))

    def test_p3_preparation_never_calls_04_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry, _, task_record, _ = approved_p2_run(root)
            with mock.patch.object(
                content_koubo_slim,
                "search_method_assets",
                side_effect=AssertionError("P3 must not search 04"),
            ):
                context_input, _ = prepare_context_stage(
                    registry_path=registry,
                    runs_root=root / "runs",
                    task_record=task_record,
                )
            self.assertEqual(len(context_input["selected_04_assets"]), 2)

    def test_registry_rebind_to_another_vault_blocks_before_reading_03_or_05(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, original_vault, task_record, task_key = approved_p2_run(root)
            rebound_vault = root / "rebound-vault"
            shutil.copytree(original_vault, rebound_vault)
            rebound_registry = root / "rebound-registry.json"
            rebound_registry.write_text(
                json.dumps(
                    {
                        "registry_version": "2.0",
                        "clients": {
                            "client-alpha": {
                                "vault_root": str(rebound_vault),
                                "manifest_relative_path": (
                                    "workflow-config/content-koubo-client-manifest.json"
                                ),
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with mock.patch.object(
                content_koubo_slim,
                "search_knowledge_assets",
                side_effect=AssertionError("rebound 03 must not be read"),
            ), mock.patch.object(
                content_koubo_slim,
                "read_primary_profile",
                side_effect=AssertionError("rebound 05 must not be read"),
            ):
                with self.assertRaises(SlimRuntimeError) as caught:
                    prepare_context_stage(
                        registry_path=rebound_registry,
                        runs_root=root / "runs",
                        task_record=task_record,
                    )

            self.assertEqual(caught.exception.error_code, "SLIM_TASK_IDENTITY_CHANGED")
            store = RunStore(root / "runs")
            self.assertEqual(store.get_task(task_key)["state"], "direction_approved")
            self.assertFalse(
                (store.run_directory(task_key) / "artifacts" / "content_context_v1.json").exists()
            )

    def test_company_brand_and_neutral_do_not_resolve_or_read_profile(self) -> None:
        for mode in ("company_brand", "neutral"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                registry, vault, task_record, _ = approved_p2_run(
                    root,
                    speaker_mode=mode,
                    business_needs=[],
                    include_profile=False,
                )
                shutil.rmtree(vault / "private-profile")
                resolved: list[str] = []
                original = content_koubo_slim.resolve_asset_root

                def tracking_root(vault_root, manifest, logical_name):
                    resolved.append(logical_name)
                    return original(vault_root, manifest, logical_name)

                with mock.patch.object(content_koubo_slim, "resolve_asset_root", side_effect=tracking_root):
                    context_input, _ = prepare_context_stage(
                        registry_path=registry,
                        runs_root=root / "runs",
                        task_record=task_record,
                    )
                self.assertEqual(resolved, ["method"])
                self.assertEqual(context_input["knowledge_candidates"], [])
                self.assertIsNone(context_input["profile_candidate"])
                self.assertIsNone(context_result(context_input)["profile_context"])

    def test_personal_ip_missing_or_multiple_primary_profiles_blocks_before_context(self) -> None:
        for mode in ("missing", "multiple"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                registry, vault, task_record, task_key = approved_p2_run(
                    root,
                    business_needs=[],
                    include_profile=(mode == "multiple"),
                )
                if mode == "multiple":
                    (vault / "private-profile" / "second.md").write_text(
                        "---\nstatus: active\nis_primary: true\n---\n# 第二主 Profile\n\n冲突。\n",
                        encoding="utf-8",
                    )
                with self.assertRaises(SlimRuntimeError) as caught:
                    prepare_context_stage(
                        registry_path=registry,
                        runs_root=root / "runs",
                        task_record=task_record,
                    )
                self.assertEqual(caught.exception.error_code, "SLIM_PROFILE_INVALID")
                store = RunStore(root / "runs")
                self.assertEqual(store.get_task(task_key)["state"], "direction_approved")
                self.assertFalse(
                    (store.run_directory(task_key) / "artifacts" / "content_context_v1.json").exists()
                )

    def test_missing_relevant_03_continues_without_invention(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry, _, task_record, task_key = approved_p2_run(
                root, business_needs=["火星火山专属业务线索"]
            )
            context_input, _ = prepare_context_stage(
                registry_path=registry,
                runs_root=root / "runs",
                task_record=task_record,
            )
            self.assertEqual(context_input["knowledge_candidates"], [])
            result = context_result(context_input)
            self.assertEqual(result["selected_03_business_assets"], [])
            record_context_result(
                registry_path=registry,
                runs_root=root / "runs",
                task_record=task_record,
                context_result=result,
            )


class ContextBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry, _, self.task_record, self.task_key = approved_p2_run(self.root)
        self.context_input, _ = prepare_context_stage(
            registry_path=self.registry,
            runs_root=self.root / "runs",
            task_record=self.task_record,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_rejects_unselected_04_and_identifiable_source_phrase(self) -> None:
        invented = context_result(self.context_input)
        invented["selected_04_content_assets"][0]["asset_id"] = "INVENTED"
        with self.assertRaises(SlimRuntimeError):
            validate_content_context(invented, self.context_input)

        copied = context_result(self.context_input)
        source = self.context_input["selected_04_assets"][0]["source_excerpt"]
        copied["selected_04_content_assets"][0]["writer_context"] = source
        with self.assertRaises(SlimRuntimeError) as caught:
            validate_content_context(copied, self.context_input)
        self.assertEqual(caught.exception.error_code, "SLIM_CONTEXT_OUTPUT_INVALID")

    def test_rejects_unoffered_03_fake_profile_passage_hash_and_absolute_path(self) -> None:
        bad_03 = context_result(self.context_input)
        bad_03["selected_03_business_assets"][0]["relative_path"] = "other.md"
        with self.assertRaises(SlimRuntimeError):
            validate_content_context(bad_03, self.context_input)

        bad_profile = context_result(self.context_input)
        bad_profile["profile_context"]["selected_passages"] = ["不存在的本人事实"]
        with self.assertRaises(SlimRuntimeError):
            validate_content_context(bad_profile, self.context_input)

        for forbidden in ("a" * 64, "/private/customer/profile.md"):
            with self.subTest(forbidden=forbidden):
                result = context_result(self.context_input)
                result["selected_03_business_assets"][0]["usage"] = forbidden
                with self.assertRaises(SlimRuntimeError):
                    validate_content_context(result, self.context_input)

    def test_output_cannot_change_direction_mode_or_user_boundaries(self) -> None:
        mutations = (
            ("target_audience", "另一类受众"),
            ("writer_mode", "huati"),
            ("speaker_mode", "neutral"),
            ("must_keep", ["另一条要求"]),
        )
        for field, replacement in mutations:
            with self.subTest(field=field):
                result = context_result(self.context_input)
                result[field] = replacement
                with self.assertRaises(SlimRuntimeError):
                    validate_content_context(result, self.context_input)

    def test_failed_output_keeps_context_pending_without_pack(self) -> None:
        result = context_result(self.context_input)
        result["writer_mode"] = "huati"
        store = RunStore(self.root / "runs")
        with self.assertRaises(SlimRuntimeError):
            record_context_result(
                registry_path=self.registry,
                runs_root=self.root / "runs",
                task_record=self.task_record,
                context_result=result,
            )
        self.assertEqual(store.get_task(self.task_key)["state"], "context_pending")
        self.assertFalse(
            (store.run_directory(self.task_key) / "artifacts" / "content_context_v1.json").exists()
        )


class StructureAndReceiptTests(unittest.TestCase):
    def test_skill_creator_validator_and_json_schemas_pass(self) -> None:
        validator = FACTORY_ROOT / "tools/quick_validate_skill.py"
        completed = subprocess.run(
            [sys.executable, "-B", str(validator), str(CONTEXT_ROOT)],
            cwd=FACTORY_ROOT,
            check=False,
            text=True,
            capture_output=True,
            env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        for schema in (CONTEXT_ROOT / "schemas").glob("*.json"):
            self.assertIsInstance(json.loads(schema.read_text(encoding="utf-8")), dict)

    def test_historical_skill_creator_receipt_remains_verifiable(self) -> None:
        design = (
            FACTORY_ROOT
            / "designs"
            / "content-v2-slim"
            / "content-context-retriever-design-card.md"
        )
        receipt = json.loads(
            (
                FACTORY_ROOT
                / "designs"
                / "content-v2-slim"
                / "content-context-retriever-skill-creator-receipt.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["skill_name"], "content-context-retriever")
        self.assertEqual(receipt["exit_code"], 0)
        self.assertEqual(
            receipt["design_card_sha256"], hashlib.sha256(design.read_bytes()).hexdigest()
        )
        self.assertRegex(receipt["final_validation"]["skill_sha256"], r"^[0-9a-f]{64}$")

    def test_p3_complexity_budget_remains_intact_during_p6(self) -> None:
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
        runtime_modules = {
            path.name for path in (SLIM_ROOT / "runtime").glob("*.py")
        }
        self.assertNotIn("content_context_store.py", runtime_modules)
        runtime_text = "\n".join(
            path.read_text(encoding="utf-8") for path in SLIM_ROOT.rglob("*.py")
        )
        self.assertNotIn("content_context_v2.json", runtime_text)
        self.assertEqual(
            set(TRANSITIONS),
            {
                "started", "direction_pending", "direction_approved", "context_pending",
                "context_ready", "draft_pending", "draft_approved", "package_pending",
                "package_approved", "blocked", "saved", "abandoned",
            },
        )

    def test_project_state_keeps_p3_through_p6_gate_history(self) -> None:
        state = json.loads((FACTORY_ROOT / "project-state.json").read_text(encoding="utf-8"))
        self.assertTrue(
            {"P0", "P1", "P2", "P3", "P4", "P5", "P6"}.issubset(
                state["phase"]["passed_gates"]
            )
        )
        self.assertIn(state["phase"]["current"], {"P6", "P7"})


if __name__ == "__main__":
    unittest.main()
