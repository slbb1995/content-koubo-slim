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

from runtime.client_registry import load_effective_registry, resolve_client, select_client_id  # noqa: E402
from runtime.content_source import (  # noqa: E402
    apply_obsidian_configuration,
    plan_obsidian_configuration,
    stable_id,
)
from runtime.error_model import SlimRuntimeError  # noqa: E402
from runtime.run_store import RunStore  # noqa: E402
from runtime.schema_validation import SOURCE_ROLE_POLICY  # noqa: E402
from scripts.content_koubo_slim import (  # noqa: E402
    prepare_context_stage,
    prepare_direction_stage,
    record_context_result,
    record_direction_result,
    record_draft_result,
    record_package_result,
    respond_direction,
    respond_draft,
    respond_package,
)


class ContentSourceV1Tests(unittest.TestCase):
    def temporary_root(self):
        parent = Path("/private/tmp") if Path("/private/tmp").is_dir() else None
        return tempfile.TemporaryDirectory(prefix="content-koubo-v3-", dir=parent)

    @staticmethod
    def make_vault(root: Path) -> Path:
        vault = root / "知识库"
        vault.mkdir()
        for name in ("03-业务知识库", "04-内容方法库", "05-IP-Profile", "06-Agent与Workflow", "07-生产与反馈"):
            (vault / name).mkdir()
        return vault

    @staticmethod
    def write_profile(vault: Path, client_id: str, name: str, *, primary: bool) -> str:
        profile_id = stable_id("PRF", client_id, name.casefold())
        body = (
            "---\n"
            "status: active\n"
            f"is_primary: {'true' if primary else 'false'}\n"
            f"profile_id: {profile_id}\n"
            "profile_schema: zsk-profile-v2\n"
            f"display_name: \"{name}\"\n"
            f"aliases: [\"{name}老师\"]\n"
            "---\n\n"
            f"# {name} Profile\n\n## 确认事实\n\n- {name}的事实。\n"
        )
        (vault / "05-IP-Profile" / f"{name}.md").write_text(body, encoding="utf-8")
        return profile_id

    def test_configure_is_zero_write_then_selects_any_active_profile(self) -> None:
        with self.temporary_root() as directory:
            root = Path(directory)
            vault = self.make_vault(root)
            client_id = "CLT-1234567890ABCD"
            primary_id = self.write_profile(vault, client_id, "甲", primary=True)
            other_id = self.write_profile(vault, client_id, "乙", primary=False)
            for name in ("AGENTS.md", "README.md", "00-IP-Profile索引.md"):
                (vault / "05-IP-Profile" / name).write_text("# 说明\n这不是人物资料。", encoding="utf-8")
            registry = root / "host" / ".content-workflows" / "knowledge-base-registry.json"
            plan = plan_obsidian_configuration(vault, registry_path=registry, client_id=client_id)
            self.assertEqual(plan['preview']['profile_count'], 2)
            self.assertFalse(registry.exists())
            self.assertFalse((vault / "06-Agent与Workflow" / "content-source-manifest.json").exists())
            applied = apply_obsidian_configuration(
                vault,
                confirmation=plan["confirmation"],
                registry_path=registry,
                client_id=client_id,
            )
            self.assertEqual(applied["readback"], "verified")
            reference = root / "reference.md"
            reference.write_text("# 参考\n\n先判断问题，再给行动。\n", encoding="utf-8")
            response_a, record_a = prepare_direction_stage(
                registry_path=registry,
                runs_root=root / "runs",
                client_id=None,
                speaker_mode="personal_ip",
                topic_original="测试多 IP",
                reference_paths=[reference],
                user_thoughts=None,
                must_keep=[],
                must_avoid=[],
                profile="甲",
            )
            response_b, record_b = prepare_direction_stage(
                registry_path=registry,
                runs_root=root / "runs",
                client_id=None,
                speaker_mode="personal_ip",
                topic_original="测试多 IP",
                reference_paths=[reference],
                user_thoughts=None,
                must_keep=[],
                must_avoid=[],
                profile="乙老师",
            )
            self.assertTrue(response_a["run_created_now"])
            self.assertTrue(response_b["run_created_now"])
            self.assertNotEqual(record_a, record_b)
            store = RunStore(root / "runs")
            frozen_a = store.read_task_input(store.resolve_task_record(record_a))
            frozen_b = store.read_task_input(store.resolve_task_record(record_b))
            self.assertEqual(frozen_a["profile_id"], primary_id)
            self.assertEqual(frozen_b["profile_id"], other_id)

    def test_invalid_feishu_reference_fails_before_transport(self) -> None:
        with self.temporary_root() as directory:
            root = Path(directory)
            client_id = "CLT-1234567890ABCD"
            kb_id = stable_id("KB", "feishu", "https://feishu.cn/wiki/space/123")
            binding_id = stable_id("BND", client_id, kb_id)
            registry_path = root / "registry.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "contract_version": "content-source-v1",
                        "bindings": {
                            binding_id: {
                                "binding_id": binding_id,
                                "client_id": client_id,
                                "knowledge_base_id": kb_id,
                                "backend": "feishu",
                                "locator": {"knowledge_base_ref": "https://feishu.cn/wiki/space/123"},
                                "manifest_ref": "doc-manifest",
                                "profile_index_ref": "doc-profiles",
                                "supported_workflows": ["content-koubo-slim"],
                                "workflow_defaults": {"content-koubo-slim": {"profile_id": None, "use_no_ip": False}},
                                "status": "active",
                            }
                        },
                        "workflow_defaults": {"content-koubo-slim": binding_id},
                        "revision": 1,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(SlimRuntimeError) as caught:
                load_effective_registry(registry_path)
            self.assertEqual(caught.exception.error_code, "SLIM_REGISTRY_NOT_READABLE")

    def test_common_and_legacy_conflict_stops(self) -> None:
        with self.temporary_root() as directory:
            host = Path(directory) / "host"
            common = host / ".content-workflows" / "knowledge-base-registry.json"
            legacy = host / ".content-koubo-slim" / "client-registry.json"
            common.parent.mkdir(parents=True)
            legacy.parent.mkdir(parents=True)
            client_id = "CLT-1234567890ABCD"
            kb_id = stable_id("KB", "obsidian", "/private/tmp/a")
            binding_id = stable_id("BND", client_id, kb_id)
            common.write_text(json.dumps({"contract_version": "content-source-v1", "bindings": {binding_id: {"binding_id": binding_id, "client_id": client_id, "knowledge_base_id": kb_id, "backend": "obsidian", "locator": {"vault_root": "/private/tmp/a"}, "manifest_ref": "06-Agent与Workflow/content-source-manifest.json", "profile_index_ref": "06-Agent与Workflow/content-profile-index.json", "supported_workflows": ["content-koubo-slim"], "workflow_defaults": {"content-koubo-slim": {"profile_id": None, "use_no_ip": False}}, "status": "active"}}, "workflow_defaults": {"content-koubo-slim": binding_id}, "revision": 1}), encoding="utf-8")
            legacy.write_text(json.dumps({"registry_version": "2.0", "clients": {client_id: {"vault_root": "/private/tmp/b", "manifest_relative_path": "config/manifest.json"}}}), encoding="utf-8")
            with mock.patch.dict(os.environ, {"CODEX_HOME": str(host)}):
                with self.assertRaisesRegex(SlimRuntimeError, "当前客户索引"):
                    load_effective_registry()

    def test_registry_manifest_and_profile_index_drift_after_gate_a_are_blocked(self) -> None:
        for target in ("registry", "manifest", "profile_index"):
            with self.subTest(target=target), self.temporary_root() as directory:
                root = Path(directory)
                vault = self.make_vault(root)
                client_id = "CLT-1234567890ABCD"
                self.write_profile(vault, client_id, "甲", primary=True)
                registry = root / "registry.json"
                plan = plan_obsidian_configuration(vault, registry_path=registry, client_id=client_id)
                apply_obsidian_configuration(
                    vault,
                    confirmation=plan["confirmation"],
                    registry_path=registry,
                    client_id=client_id,
                )
                reference = root / "reference.md"
                reference.write_text(
                    "# 参考\n\n先识别真正的问题，再给一个可以复核的最小行动。\n",
                    encoding="utf-8",
                )
                runs = root / "runs"
                _response, task_record = prepare_direction_stage(
                    registry_path=registry,
                    runs_root=runs,
                    client_id=None,
                    speaker_mode="personal_ip",
                    topic_original="如何先确认需求",
                    reference_paths=[reference],
                    user_thoughts=None,
                    must_keep=[],
                    must_avoid=[],
                    profile="甲",
                )
                store = RunStore(runs)
                task_key = store.resolve_task_record(task_record)
                analyzer = {
                    "analysis_version": "slim-1.0",
                    "reference_analyses": [{
                        "reference_id": "REF-001",
                        "content_value": "提供从问题到行动的推进方式",
                        "hook_mechanism": "先提出常见误区",
                        "structure_mechanism": "问题判断后给最小行动",
                        "transferable_points": ["先判断再行动"],
                        "prohibited_transfers": ["对标作者专属经历"],
                    }],
                    "selected_method_assets": [],
                    "fused_direction": {
                        "target_audience": "需要确认客户需求的服务人员",
                        "core_promise": "给出一条不跑偏的确认顺序",
                        "external_reference_value": ["先判断再行动"],
                        "structure_plan": ["指出误区", "给出确认顺序", "提醒复核"],
                        "conflicts": [],
                        "user_boundaries": {"user_thoughts": None, "must_keep": [], "must_avoid": []},
                        "generalization_boundary": "只借鉴结构，不迁移身份案例和数据",
                    },
                    "content_goal": "explain",
                    "speaker_mode": "personal_ip",
                    "writer_mode": "ganhuo",
                    "writer_mode_reason": "适合按步骤讲清楚",
                    "secondary_tactics": [],
                    "business_context_needs": [],
                    "customer_readable_direction": {
                        "original_topic": "如何先确认需求",
                        "target_audience": "需要确认客户需求的服务人员",
                        "core_promise": "给出一条不跑偏的确认顺序",
                        "borrowed_value": ["先判断再行动"],
                        "method_asset_usage": [],
                        "oral_structure": ["指出误区", "给出确认顺序", "提醒复核"],
                        "user_boundaries": {"user_thoughts": None, "must_keep": [], "must_avoid": []},
                        "speaker_mode_explanation": "由本次明确选择的甲来讲",
                        "writer_recommendation": {"mode": "ganhuo", "reason": "适合按步骤讲清楚"},
                        "generalization_boundary": "只借鉴结构，不迁移身份案例和数据",
                    },
                }
                record_direction_result(store=store, task_key=task_key, analyzer_result=analyzer)
                respond_direction(
                    store=store,
                    task_key=task_key,
                    method_root=vault / "04-内容方法库",
                    decision="认可整版方向",
                )
                path = {
                    "registry": registry,
                    "manifest": vault / "06-Agent与Workflow" / "content-source-manifest.json",
                    "profile_index": vault / "06-Agent与Workflow" / "content-profile-index.json",
                }[target]
                value = json.loads(path.read_text(encoding="utf-8"))
                value["revision"] += 1
                path.write_text(
                    json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                with self.assertRaises(SlimRuntimeError) as caught:
                    prepare_context_stage(
                        registry_path=registry,
                        runs_root=runs,
                        task_record=task_record,
                    )
                self.assertEqual(caught.exception.error_code, "SLIM_TASK_IDENTITY_CHANGED")
                self.assertTrue(caught.exception.artifacts_preserved)

    def test_common_profile_completes_three_gates_and_saves_to_its_own_path(self) -> None:
        with self.temporary_root() as directory:
            root = Path(directory)
            vault = self.make_vault(root)
            client_id = "CLT-1234567890ABCD"
            selected_profile_id = self.write_profile(vault, client_id, "甲", primary=True)
            self.write_profile(vault, client_id, "乙", primary=False)
            registry = root / "registry.json"
            plan = plan_obsidian_configuration(vault, registry_path=registry, client_id=client_id)
            apply_obsidian_configuration(vault, confirmation=plan["confirmation"], registry_path=registry, client_id=client_id)
            reference = root / "reference.md"
            reference.write_text("# 完整参考\n\n先识别真正的问题，再给出一个可以执行的最小行动，最后提醒读者核对结果。\n", encoding="utf-8")
            runs = root / "runs"
            _response, task_record = prepare_direction_stage(
                registry_path=registry,
                runs_root=runs,
                client_id=None,
                speaker_mode="personal_ip",
                topic_original="如何先确认需求",
                reference_paths=[reference],
                user_thoughts=None,
                must_keep=[],
                must_avoid=[],
                profile="甲",
            )
            store = RunStore(runs)
            task_key = store.resolve_task_record(task_record)
            analyzer = {
                "analysis_version": "slim-1.0",
                "reference_analyses": [{
                    "reference_id": "REF-001",
                    "content_value": "提供从问题到行动的推进方式",
                    "hook_mechanism": "先提出常见误区",
                    "structure_mechanism": "问题判断后给最小行动",
                    "transferable_points": ["先判断再行动"],
                    "prohibited_transfers": ["对标作者专属经历"],
                }],
                "selected_method_assets": [],
                "fused_direction": {
                    "target_audience": "需要确认客户需求的服务人员",
                    "core_promise": "给出一条不跑偏的确认顺序",
                    "external_reference_value": ["先判断再行动"],
                    "structure_plan": ["指出误区", "给出确认顺序", "提醒复核"],
                    "conflicts": [],
                    "user_boundaries": {"user_thoughts": None, "must_keep": [], "must_avoid": []},
                    "generalization_boundary": "只借鉴结构，不迁移身份案例和数据",
                },
                "content_goal": "explain",
                "speaker_mode": "personal_ip",
                "writer_mode": "ganhuo",
                "writer_mode_reason": "适合按步骤讲清楚",
                "secondary_tactics": [],
                "business_context_needs": [],
                "customer_readable_direction": {
                    "original_topic": "如何先确认需求",
                    "target_audience": "需要确认客户需求的服务人员",
                    "core_promise": "给出一条不跑偏的确认顺序",
                    "borrowed_value": ["先判断再行动"],
                    "method_asset_usage": [],
                    "oral_structure": ["指出误区", "给出确认顺序", "提醒复核"],
                    "user_boundaries": {"user_thoughts": None, "must_keep": [], "must_avoid": []},
                    "speaker_mode_explanation": "由本次明确选择的甲来讲",
                    "writer_recommendation": {"mode": "ganhuo", "reason": "适合按步骤讲清楚"},
                    "generalization_boundary": "只借鉴结构，不迁移身份案例和数据",
                },
            }
            record_direction_result(store=store, task_key=task_key, analyzer_result=analyzer)
            respond_direction(store=store, task_key=task_key, method_root=vault / "04-内容方法库", decision="认可整版方向")
            context_input, _ = prepare_context_stage(registry_path=registry, runs_root=runs, task_record=task_record)
            context = {
                "context_version": context_input["context_version"],
                "client_id": context_input["client_id"],
                "speaker_mode": context_input["speaker_mode"],
                "topic_original": context_input["task_input"]["topic_original"],
                "target_audience": context_input["approved_direction"]["target_audience"],
                "approved_direction": context_input["approved_direction"],
                "user_thoughts": None,
                "must_keep": [],
                "must_avoid": [],
                "selected_external_reference_mechanisms": context_input["selected_external_reference_mechanisms"],
                "selected_04_content_assets": [],
                "selected_04_method_assets": [],
                "selected_03_business_assets": [],
                "profile_context": {"relative_path": context_input["profile_candidate"]["relative_path"], "source_role": "client_profile", "selected_passages": ["甲的事实。"], "usage": "保持本次选定 IP 的已确认表达边界"},
                "source_role_policy": SOURCE_ROLE_POLICY,
                "writer_mode": context_input["writer_mode"],
                "secondary_tactics": [],
            }
            record_context_result(registry_path=registry, runs_root=runs, task_record=task_record, context_result=context)
            record_draft_result(runs_root=runs, task_record=task_record, base_draft_version=0, writer_result={"paragraphs": [{"text": "很多人一上来就急着给方案，但真正重要的是先确认客户到底卡在哪里。"}, {"text": "先问清目标，再核对现状，最后只给一个可以执行的下一步。这样既不夸大，也不会让方案跑偏。"}]})
            respond_draft(runs_root=runs, task_record=task_record, decision="确认正文")
            package = {
                "cover_titles": ["先别急着给方案", "需求确认三步法"],
                "publish_titles": ["给方案之前先问清这三件事", "客户需求总跑偏问题出在这里", "一条不跑偏的需求确认顺序"],
                "recommended_cover_title": "先别急着给方案",
                "recommended_publish_title": "给方案之前先问清这三件事",
                "publish_copy": "给方案之前，先把目标、现状和下一步问清楚。真正有效的服务，不是信息堆得多，而是每一步都能被客户理解、执行和复核。",
                "tags": ["#需求确认", "#客户服务", "#工作方法", "#内容口播", "#流程优化"],
            }
            record_package_result(runs_root=runs, task_record=task_record, base_package_version=0, package_result=package)
            completed, _ = respond_package(registry_path=registry, runs_root=runs, task_record=task_record, decision="确认并保存")
            self.assertEqual(completed["status"], "completed")
            saved = list((vault / "07-生产与反馈" / "content-koubo-slim" / selected_profile_id / "weekly").glob("*.md"))
            self.assertEqual(len(saved), 2)
            self.assertEqual(completed["publish_status"], "not_requested")


if __name__ == "__main__":
    unittest.main()
