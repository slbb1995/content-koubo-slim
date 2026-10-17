from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


FACTORY_ROOT = Path(__file__).resolve().parents[2]
SLIM_ROOT = FACTORY_ROOT / "Skills" / "content-koubo-slim"
ANALYZER_ROOT = FACTORY_ROOT / "Skills" / "content-koubo-analyzer"
if str(SLIM_ROOT) not in sys.path:
    sys.path.insert(0, str(SLIM_ROOT))
if str(SLIM_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(SLIM_ROOT / "scripts"))

from content_koubo_slim import prepare_direction_stage, record_direction_result, respond_direction
from runtime.error_model import SlimRuntimeError
from runtime.run_store import RunStore
from runtime.schema_validation import build_gate_a, validate_analyzer_input, validate_analyzer_result


def manifest_data(client_id: str = "client-alpha") -> dict:
    return {
        "contract_version": "2.0",
        "client_id": client_id,
        "asset_roots": {
            "knowledge": "private-business",
            "method": "authorized-methods",
            "profile": "private-profile",
            "output": "private-output",
        },
        "default_speaker_mode": "personal_ip",
        "allowed_speaker_modes": ["personal_ip", "company_brand", "neutral"],
        "profile_policy": {
            "required_when": ["personal_ip"],
            "selector": {"status": "active", "is_primary": True},
        },
        "default_platform": "short_video",
        "output_template": "finished/{profile_or_brand}/weekly",
    }


def method_page(
    *,
    asset_id: str,
    asset_type: str,
    keyword: str,
    title: str,
    body: str,
    audience_scope: str = "consumer",
) -> str:
    return f"""---
type: {asset_type}
asset_id: {asset_id}
status: active
audience_scope: {audience_scope}
keywords: [\"{keyword}\"]
use_when: [\"受众需要判断方法\"]
---
# {title}

{body}
"""


def write_fixture(root: Path, client_id: str = "client-alpha") -> tuple[Path, Path]:
    vault = root / "generic-vault"
    config = vault / "workflow-config"
    config.mkdir(parents=True)
    for directory in (
        "private-business",
        "authorized-methods",
        "private-profile",
        "private-output",
    ):
        (vault / directory).mkdir()
    (config / "content-koubo-client-manifest.json").write_text(
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
    methods = vault / "authorized-methods"
    for index in range(1, 5):
        (methods / f"peer-{index}.md").write_text(
            method_page(
                asset_id=f"PEER-{index:03d}",
                asset_type="benchmark_deconstruction",
                keyword="保险选择",
                title=f"保险选择同行拆解 {index}",
                body=f"用普通家庭的疑问组织保险选择内容，同行页编号 {index}。",
                audience_scope=("internal_sales_training" if index == 2 else "consumer"),
            ),
            encoding="utf-8",
        )
    for index in range(1, 4):
        (methods / f"oral-{index}.md").write_text(
            method_page(
                asset_id=f"ORAL-{index:03d}",
                asset_type="oral_structure",
                keyword="保险选择",
                title=f"保险选择口播结构 {index}",
                body=f"先说误区，再给判断标准，最后收束，结构页编号 {index}。",
            ),
            encoding="utf-8",
        )
    (methods / "irrelevant.md").write_text(
        method_page(
            asset_id="PEER-999",
            asset_type="benchmark_deconstruction",
            keyword="宠物摄影",
            title="宠物摄影同行拆解",
            body="只讨论宠物摄影光线。",
        ),
        encoding="utf-8",
    )
    for outside_root in (vault / "private-business", vault / "private-profile"):
        (outside_root / "forbidden-relevant.md").write_text(
            method_page(
                asset_id=f"FORBIDDEN-{outside_root.name}",
                asset_type="benchmark_deconstruction",
                keyword="保险选择",
                title="绝不能被 04 检索读到",
                body="这页位于 Manifest 的其他逻辑根。",
            ),
            encoding="utf-8",
        )
    return registry_path, vault


def write_references(root: Path, count: int) -> list[Path]:
    paths: list[Path] = []
    for index in range(1, count + 1):
        path = root / f"reference-{index}.md"
        path.write_text(
            f"# 参考 {index}\n\n这是一段关于家庭如何判断保障选择的独立参考材料第 {index} 篇。"
            f"作者自称拥有第 {index} 号专属经历，但这个身份不能转移。\n",
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def prepare(
    root: Path,
    *,
    reference_count: int,
    topic_original: str = "普通家庭做保险选择前，先问哪几个问题？",
    speaker_mode: str = "personal_ip",
) -> tuple[Path, Path, dict, dict]:
    registry_path, vault = write_fixture(root)
    references = write_references(root, reference_count)
    response, task_record = prepare_direction_stage(analysis_version="slim-1.0",
        registry_path=registry_path,
        runs_root=root / "runs",
        client_id="client-alpha",
        speaker_mode=speaker_mode,
        topic_original=topic_original,
        reference_paths=references,
        user_thoughts="不要制造焦虑",
        must_keep=["先问清需求"],
        must_avoid=["同行身份背书"],
    )
    store = RunStore(root / "runs")
    task_key = store.resolve_task_record(task_record)
    analyzer_input = store.read_fixed_json(task_key, "analyzer_input_v1.json")
    return registry_path, vault, response, analyzer_input


def only_task_record(runs_root: Path) -> str:
    records = sorted((runs_root / "task-keys").glob("*.json"))
    if len(records) != 1:
        raise AssertionError(f"expected one task record, found {len(records)}")
    return records[0].relative_to(runs_root).as_posix()


def current_task_key(runs_root: Path) -> str:
    store = RunStore(runs_root)
    return store.resolve_task_record(only_task_record(runs_root))


def analyzer_result(analyzer_input: dict, *, include_methods: bool = True) -> dict:
    selected = []
    if include_methods:
        roles: set[str] = set()
        for candidate in analyzer_input["method_candidates"]:
            if candidate["asset_role"] in roles:
                continue
            roles.add(candidate["asset_role"])
            selected.append(
                {
                    "asset_id": candidate["asset_id"],
                    "asset_role": candidate["asset_role"],
                    "relative_path": candidate["relative_path"],
                    "page_sha256": candidate["page_sha256"],
                    "usage": "提供通用问题顺序" if candidate["asset_role"] == "peer_content_asset" else "提供先误区后标准的推进方式",
                    "reason": "与当前受众和问题直接相关",
                }
            )
    boundaries = {
        "user_thoughts": analyzer_input["user_thoughts"],
        "must_keep": analyzer_input["must_keep"],
        "must_avoid": analyzer_input["must_avoid"],
    }
    return {
        "analysis_version": "slim-1.0",
        "reference_analyses": [
            {
                "reference_id": reference["reference_id"],
                "content_value": "帮助普通人先建立判断顺序",
                "hook_mechanism": "从常见误区切入",
                "structure_mechanism": "问题、判断标准、行动提醒",
                "transferable_points": ["通用判断问题"],
                "prohibited_transfers": [f"作者第 {index} 号专属经历"],
            }
            for index, reference in enumerate(analyzer_input["references"], 1)
        ],
        "selected_method_assets": selected,
        "fused_direction": {
            "target_audience": "正在为家庭保障做功课的普通人",
            "core_promise": "听完能先用几个问题判断自己的保障需求",
            "external_reference_value": ["参考内容提供先澄清问题再给标准的通用思路"],
            "structure_plan": ["先说误区", "再给判断问题", "最后提醒按自身情况核实"],
            "conflicts": [],
            "user_boundaries": boundaries,
            "generalization_boundary": "同行专属身份、经历、案例、业务、数据和原句全部舍弃或一般化。",
        },
        "content_goal": "explain",
        "speaker_mode": analyzer_input["speaker_mode"],
        "writer_mode": "ganhuo",
        "writer_mode_reason": "核心目标是让普通人学会一套判断方法",
        "secondary_tactics": ["误区钩子"],
        "business_context_needs": ["若涉及具体产品，再核对当前客户业务资料"],
        "customer_readable_direction": {
            "original_topic": analyzer_input["topic_original"],
            "target_audience": "正在为家庭保障做功课的普通人",
            "core_promise": "听完能先用几个问题判断自己的保障需求",
            "borrowed_value": ["参考内容提供先澄清问题再给标准的通用思路"],
            "method_asset_usage": [item["usage"] for item in selected],
            "oral_structure": ["先说误区", "再给判断问题", "最后提醒按自身情况核实"],
            "user_boundaries": boundaries,
            "speaker_mode_explanation": "以当前个人讲述者身份表达，但不新增职业、经历或案例。",
            "writer_recommendation": {
                "mode": "ganhuo",
                "reason": "核心目标是让普通人学会一套判断方法",
            },
            "generalization_boundary": "同行专属身份、经历、案例、业务、数据和原句全部舍弃或一般化。",
        },
    }


class TaskKeyAndReferenceTests(unittest.TestCase):
    def test_task_key_is_program_generated_persisted_and_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "runs"
            store = RunStore(root)
            identity = {
                "client_id": "client-alpha",
                "speaker_mode": "neutral",
                "topic_original": "用户原始选题",
                "reference_set_sha256": "a" * 64,
            }
            state, created, first_key = store.start_program_task(
                business_identity=identity,
                client_id="client-alpha",
                speaker_mode="neutral",
            )
            repeated, created_again, second_key = store.start_program_task(
                business_identity=identity,
                client_id="client-alpha",
                speaker_mode="neutral",
            )
            first_record = state["task_key_record"]
            record_path = root / first_record
            record = json.loads(record_path.read_text(encoding="utf-8"))
            self.assertEqual(record["generated_by"], "deterministic_program")
            self.assertEqual(
                record["retry_policy"],
                "reuse_same_record_for_same_frozen_business_identity",
            )
            self.assertTrue(created)
            self.assertFalse(created_again)
            self.assertEqual(first_key, second_key)
            self.assertEqual(store.resolve_task_record(first_record), first_key)
            self.assertEqual(state["run_id"], repeated["run_id"])
            self.assertEqual(state["task_key_record"], first_record)
            self.assertEqual(state["task_key_generated_by"], "deterministic_program")
            self.assertNotIn("用户原始选题", (root / "run-index.json").read_text())
            self.assertEqual(sum(path.is_dir() for path in root.glob("run-*")), 1)

    def test_user_and_ai_task_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = RunStore(Path(temp) / "runs")
            for origin in ("user", "ai"):
                with self.subTest(origin=origin), self.assertRaises(SlimRuntimeError) as caught:
                    store.start_task(
                        task_key="invented",
                        task_key_generated_by=origin,
                        task_key_record="not-trusted",
                        client_id="client-alpha",
                        speaker_mode="neutral",
                    )
                self.assertEqual(caught.exception.error_code, "SLIM_TASK_KEY_UNTRUSTED")
            self.assertFalse((Path(temp) / "runs").exists())

    def test_cli_start_has_no_host_request_or_raw_task_key_option(self) -> None:
        source = (SLIM_ROOT / "scripts" / "content_koubo_slim.py").read_text(encoding="utf-8")
        self.assertNotIn('"--host-request-id"', source)
        self.assertNotIn('"--task-key"', source)
        self.assertIn('"--task-record"', source)
        help_result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SLIM_ROOT / "scripts" / "content_koubo_slim.py"),
                "start", "--analysis-version", "slim-1.0",
                "--help",
            ],
            check=False,
            text=True,
            capture_output=True,
        )
        for option in (
            "--host-request-id",
            "--task-key",
            "--topic-normalized",
            "--target-audience",
            "--target-audience-scope",
        ):
            self.assertNotIn(option, help_result.stdout)

    def test_real_start_rejects_user_or_ai_identity_options_before_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry, _ = write_fixture(root)
            reference = write_references(root, 1)[0]
            base = [
                sys.executable,
                "-B",
                str(SLIM_ROOT / "scripts" / "content_koubo_slim.py"),
                "start", "--analysis-version", "slim-1.0",
                "--registry",
                str(registry),
                "--runs-root",
                str(root / "runs"),
                "--client-id",
                "client-alpha",
                "--speaker-mode",
                "neutral",
                "--topic-original",
                "用户原始选题",
                "--reference",
                str(reference),
            ]
            for option in ("--host-request-id", "--task-key"):
                result = subprocess.run(
                    [*base, option, "ai-or-user-invented"],
                    check=False,
                    text=True,
                    capture_output=True,
                )
                self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / "runs").exists())

    def test_controlled_task_record_cannot_be_invented(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runs_root = Path(temp) / "runs"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SLIM_ROOT / "scripts" / "content_koubo_slim.py"),
                    "status",
                    "--runs-root",
                    str(runs_root),
                    "--task-record",
                    f"task-keys/{'a' * 64}.json",
                ],
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 2)
            response = json.loads(result.stdout)
            self.assertFalse(response["run_exists"])
            self.assertNotIn("task_key", result.stdout)

    def test_one_two_and_five_references_pass_without_source_changes(self) -> None:
        for count in (1, 2, 5):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                registry, _ = write_fixture(root)
                references = write_references(root, count)
                before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in references}
                response, task_record = prepare_direction_stage(analysis_version="slim-1.0",
                    registry_path=registry,
                    runs_root=root / "runs",
                    client_id="client-alpha",
                    speaker_mode="neutral",
                    topic_original="普通家庭买保障前先问什么",
                    reference_paths=references,
                    user_thoughts=None,
                    must_keep=[],
                    must_avoid=[],
                )
                store = RunStore(root / "runs")
                task_key = store.resolve_task_record(task_record)
                value = store.read_fixed_json(task_key, "analyzer_input_v1.json")
                self.assertTrue(response["run_created_now"])
                self.assertEqual(value["topic_normalized_source"], "system_generated")
                self.assertNotIn("target_audience", value)
                self.assertEqual(len(value["references"]), count)
                self.assertEqual(
                    [item["reference_id"] for item in value["references"]],
                    [f"REF-{index:03d}" for index in range(1, count + 1)],
                )
                self.assertEqual(
                    before,
                    {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in references},
                )
                self.assertEqual(sum(path.is_dir() for path in (root / "runs").glob("run-*")), 1)

    def test_zero_and_six_references_stop_before_run(self) -> None:
        for count in (0, 6):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                registry, _ = write_fixture(root)
                references = write_references(root, count)
                with self.assertRaises(SlimRuntimeError) as caught:
                    prepare_direction_stage(analysis_version="slim-1.0",
                        registry_path=registry,
                        runs_root=root / "runs",
                        client_id="client-alpha",
                        speaker_mode="neutral",
                        topic_original="原始选题",
                        reference_paths=references,
                        user_thoughts=None,
                        must_keep=[],
                        must_avoid=[],
                    )
                self.assertEqual(caught.exception.error_code, "SLIM_ANALYZER_INPUT_INVALID" if count == 0 else "SLIM_REFERENCE_INVALID")
                self.assertFalse((root / "runs").exists())

    def test_frozen_topic_reference_client_and_speaker_cannot_be_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry, _ = write_fixture(root)
            references = write_references(root, 2)
            common = dict(
                analysis_version="slim-1.0",
                registry_path=registry,
                runs_root=root / "runs",
                client_id="client-alpha",
                speaker_mode="personal_ip",
                topic_original="用户逐字原始选题",
                reference_paths=references,
                user_thoughts=None,
                must_keep=[],
                must_avoid=[],
            )
            first, task_record = prepare_direction_stage(**common)
            second, repeated_record = prepare_direction_stage(**common)
            self.assertTrue(first["run_created_now"])
            self.assertFalse(second["run_created_now"])
            self.assertEqual(task_record, repeated_record)
            store = RunStore(root / "runs")
            task_key = store.resolve_task_record(task_record)
            frozen = store.read_task_input(task_key)
            self.assertEqual(frozen["topic_original"], "用户逐字原始选题")
            self.assertEqual(frozen["topic_normalized"], "用户逐字原始选题")
            self.assertEqual(frozen["topic_normalized_source"], "system_generated")
            changed = dict(common)
            changed["user_thoughts"] = "另一条用户想法"
            with self.assertRaises(SlimRuntimeError) as caught:
                prepare_direction_stage(**changed)
            self.assertEqual(caught.exception.error_code, "SLIM_TASK_IDENTITY_CHANGED")
            self.assertEqual(sum(path.is_dir() for path in (root / "runs").glob("run-*")), 1)


class MethodSearchTests(unittest.TestCase):
    def test_only_manifest_method_root_is_read_with_role_limits(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, _, _, value = prepare(root, reference_count=1)
            peer = [item for item in value["method_candidates"] if item["asset_role"] == "peer_content_asset"]
            oral = [item for item in value["method_candidates"] if item["asset_role"] == "oral_method_asset"]
            self.assertEqual((len(peer), len(oral)), (3, 2))
            self.assertFalse(any("FORBIDDEN" in item["asset_id"] for item in value["method_candidates"]))
            self.assertTrue(all(not Path(item["relative_path"]).is_absolute() for item in value["method_candidates"]))
            self.assertTrue(all(item["relevance_evidence"] for item in value["method_candidates"]))
            self.assertIn(
                "internal_sales_training",
                {item["audience_scope"] for item in value["method_candidates"]},
            )

    def test_no_relevant_method_asset_returns_empty_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry, _ = write_fixture(root)
            references = write_references(root, 1)
            response, task_record = prepare_direction_stage(analysis_version="slim-1.0",
                registry_path=registry,
                runs_root=root / "runs",
                client_id="client-alpha",
                speaker_mode="neutral",
                topic_original="阳台植物如何过冬",
                reference_paths=references,
                user_thoughts=None,
                must_keep=[],
                must_avoid=[],
            )
            store = RunStore(root / "runs")
            value = store.read_fixed_json(
                store.resolve_task_record(task_record), "analyzer_input_v1.json"
            )
            self.assertEqual(value["method_candidates"], [])
            self.assertTrue(response["run_exists"])


class GateADirectionTests(unittest.TestCase):
    def test_cli_start_and_respond_outputs_do_not_leak_internal_analyzer_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry, vault = write_fixture(root)
            reference = write_references(root, 1)[0]
            runs_root = root / "runs"
            start = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SLIM_ROOT / "scripts" / "content_koubo_slim.py"),
                    "start", "--analysis-version", "slim-1.0",
                    "--registry",
                    str(registry),
                    "--runs-root",
                    str(runs_root),
                    "--client-id",
                    "client-alpha",
                    "--speaker-mode",
                    "neutral",
                    "--topic-original",
                    "普通家庭买保障前先问什么",
                    "--reference",
                    str(reference),
                ],
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(start.returncode, 0)
            task_record = only_task_record(runs_root)
            store = RunStore(runs_root)
            task_key = store.resolve_task_record(task_record)
            value = store.read_fixed_json(task_key, "analyzer_input_v1.json")
            result_path = root / "analyzer-result.json"
            result_path.write_text(
                json.dumps(analyzer_result(value), ensure_ascii=False), encoding="utf-8"
            )
            record = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SLIM_ROOT / "scripts" / "content_koubo_slim.py"),
                    "record-direction",
                    "--runs-root",
                    str(runs_root),
                    "--task-record",
                    task_record,
                    "--analyzer-result",
                    str(result_path),
                ],
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(record.returncode, 0)
            respond = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SLIM_ROOT / "scripts" / "content_koubo_slim.py"),
                    "respond-direction",
                    "--registry",
                    str(registry),
                    "--runs-root",
                    str(runs_root),
                    "--task-record",
                    task_record,
                    "--decision",
                    "需要修改",
                    "--feedback",
                    "把中段说得更生活化",
                ],
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(respond.returncode, 0)
            forbidden = (
                "page_sha256",
                "relative_path",
                "analysis_version",
                "gate_version",
                "contract_version",
                "client_id",
                "method_candidates",
                "reference_analyses",
                value["references"][0]["content"],
                str(vault),
            )
            for output in (start.stdout, record.stdout, respond.stdout):
                self.assertEqual([item for item in forbidden if item in output], [])

    def test_complete_gate_revision_v2_v3_and_approval_freeze(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, vault, _, value = prepare(root, reference_count=2)
            store = RunStore(root / "runs")
            task_key = current_task_key(root / "runs")
            gate_v1, direction_v1 = record_direction_result(
                store=store, task_key=task_key, analyzer_result=analyzer_result(value)
            )
            self.assertEqual(direction_v1.name, "direction_v1.json")
            self.assertEqual(
                gate_v1["choices"], ["认可整版方向", "需要修改", "不采用"]
            )
            for field in (
                "original_topic",
                "target_audience",
                "core_promise",
                "external_reference_value",
                "method_asset_usage",
                "oral_structure",
                "user_boundaries",
                "speaker_mode",
                "speaker_mode_explanation",
                "content_goal",
                "writer_recommendation",
                "secondary_tactics",
                "business_context_needs",
                "generalization_boundary",
            ):
                self.assertIn(field, gate_v1)
            v1_hash = hashlib.sha256(direction_v1.read_bytes()).hexdigest()

            with self.assertRaises(SlimRuntimeError):
                record_direction_result(
                    store=store,
                    task_key=task_key,
                    analyzer_result=analyzer_result(value),
                )

            _, input_v2 = respond_direction(
                store=store,
                task_key=task_key,
                method_root=vault / "authorized-methods",
                decision="需要修改",
                feedback="把第二部分说得更生活化",
            )
            self.assertEqual(input_v2["revision_request"]["base_direction_version"], 1)
            self.assertEqual(
                input_v2["revision_request"]["feedback"],
                "把第二部分说得更生活化",
            )
            with self.assertRaises(SlimRuntimeError):
                respond_direction(
                    store=store,
                    task_key=task_key,
                    method_root=vault / "authorized-methods",
                    decision="需要修改",
                    feedback="静默覆盖上一条意见",
                )
            gate_v2, direction_v2 = record_direction_result(
                store=store, task_key=task_key, analyzer_result=analyzer_result(input_v2)
            )
            self.assertEqual((gate_v2["direction_version"], direction_v2.name), (2, "direction_v2.json"))

            _, input_v3 = respond_direction(
                store=store,
                task_key=task_key,
                method_root=vault / "authorized-methods",
                decision="需要修改",
                feedback="结尾不要带行动催促",
            )
            gate_v3, direction_v3 = record_direction_result(
                store=store, task_key=task_key, analyzer_result=analyzer_result(input_v3)
            )
            self.assertEqual((gate_v3["direction_version"], direction_v3.name), (3, "direction_v3.json"))
            self.assertEqual(hashlib.sha256(direction_v1.read_bytes()).hexdigest(), v1_hash)

            response, downstream = respond_direction(
                store=store,
                task_key=task_key,
                method_root=vault / "authorized-methods",
                decision="认可整版方向",
            )
            self.assertIsNone(downstream)
            self.assertEqual(response["workflow_stage"], "正在准备客户内容资料")
            self.assertIn("已选方向已冻结", response["message"])
            self.assertIn("尚未装配正文资料", response["message"])
            self.assertEqual(store.get_task(task_key)["state"], "direction_approved")
            approved = store.read_fixed_json(task_key, "approved_direction.json")
            self.assertEqual(
                set(approved),
                {
                    "approval_version",
                    "direction_version",
                    "approved_gate_a",
                    "gate_a_sha256",
                    "approved_direction",
                    "selected_method_assets",
                    "content_goal",
                    "speaker_mode",
                    "writer_mode",
                    "writer_mode_reason",
                    "secondary_tactics",
                    "business_context_needs",
                },
            )
            self.assertEqual(approved["direction_version"], 3)
            self.assertEqual(approved["approved_gate_a"], gate_v3)
            self.assertEqual(
                approved["approved_direction"],
                {
                    "target_audience": gate_v3["target_audience"],
                    "core_promise": gate_v3["core_promise"],
                    "external_reference_value": gate_v3["external_reference_value"],
                    "structure_plan": gate_v3["oral_structure"],
                    "user_boundaries": gate_v3["user_boundaries"],
                    "generalization_boundary": gate_v3["generalization_boundary"],
                },
            )
            names = {path.name for path in (store.run_directory(task_key) / "artifacts").iterdir()}
            self.assertFalse(any("context" in name or "draft" in name or "title" in name for name in names))

    def test_reject_abandons_without_downstream(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, vault, _, value = prepare(root, reference_count=1)
            store = RunStore(root / "runs")
            task_key = current_task_key(root / "runs")
            record_direction_result(store=store, task_key=task_key, analyzer_result=analyzer_result(value))
            response, downstream = respond_direction(
                store=store,
                task_key=task_key,
                method_root=vault / "authorized-methods",
                decision="不采用",
            )
            self.assertEqual(response["status"], "abandoned")
            self.assertIsNone(downstream)
            self.assertEqual(store.get_task(task_key)["state"], "abandoned")

    def test_revision_rejects_empty_feedback_and_identity_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, vault, _, value = prepare(root, reference_count=1)
            store = RunStore(root / "runs")
            task_key = current_task_key(root / "runs")
            record_direction_result(store=store, task_key=task_key, analyzer_result=analyzer_result(value))
            with self.assertRaises(SlimRuntimeError):
                respond_direction(
                    store=store,
                    task_key=task_key,
                    method_root=vault / "authorized-methods",
                    decision="需要修改",
                    feedback="",
                )
            with self.assertRaises(SlimRuntimeError) as caught:
                respond_direction(
                    store=store,
                    task_key=task_key,
                    method_root=vault / "authorized-methods",
                    decision="需要修改",
                    feedback="换成公司号",
                    identity_changes={"speaker_mode": "company_brand"},
                )
            self.assertEqual(caught.exception.error_code, "SLIM_TASK_IDENTITY_CHANGED")
            self.assertEqual(store.latest_version(task_key, "direction")[0], 1)

    def test_method_page_drift_blocks_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, vault, _, value = prepare(root, reference_count=1)
            store = RunStore(root / "runs")
            task_key = current_task_key(root / "runs")
            result = analyzer_result(value)
            record_direction_result(store=store, task_key=task_key, analyzer_result=result)
            selected_path = vault / "authorized-methods" / result["selected_method_assets"][0]["relative_path"]
            selected_path.write_text(selected_path.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
            with self.assertRaises(SlimRuntimeError) as caught:
                respond_direction(
                    store=store,
                    task_key=task_key,
                    method_root=vault / "authorized-methods",
                    decision="认可整版方向",
                )
            self.assertEqual(caught.exception.error_code, "SLIM_METHOD_ASSET_INVALID")
            self.assertEqual(store.get_task(task_key)["state"], "direction_pending")

    def test_peer_identity_and_identifiable_source_phrase_do_not_transfer(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, _, _, value = prepare(root, reference_count=1)
            result = analyzer_result(value)
            result["reference_analyses"][0]["prohibited_transfers"] = ["同行作者服务过上百位客户"]
            result["customer_readable_direction"]["borrowed_value"] = ["同行作者服务过上百位客户"]
            with self.assertRaises(SlimRuntimeError) as caught:
                validate_analyzer_result(result, value)
            self.assertEqual(caught.exception.error_code, "SLIM_ANALYZER_OUTPUT_INVALID")

            copied = analyzer_result(value)
            source_clause = value["references"][0]["content"].split("。", 1)[0]
            copied["customer_readable_direction"]["borrowed_value"] = [source_clause]
            with self.assertRaises(SlimRuntimeError):
                validate_analyzer_result(copied, value)

    def test_customer_readable_cannot_diverge_from_frozen_direction(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, _, _, value = prepare(root, reference_count=2)
            mutations = (
                ("core", lambda result: result["customer_readable_direction"].__setitem__(
                    "core_promise", "展示 B 的另一项核心承诺"
                )),
                ("structure", lambda result: result["customer_readable_direction"].__setitem__(
                    "oral_structure", ["展示 B 的另一套结构"]
                )),
                ("writer_reason", lambda result: result["customer_readable_direction"]
                 ["writer_recommendation"].__setitem__("reason", "展示 B 的另一项 Writer 理由")),
            )
            for label, mutate in mutations:
                with self.subTest(label=label):
                    result = analyzer_result(value)
                    mutate(result)
                    with self.assertRaises(SlimRuntimeError) as caught:
                        validate_analyzer_result(result, value)
                    self.assertEqual(
                        caught.exception.error_code, "SLIM_ANALYZER_OUTPUT_INVALID"
                    )

    def test_multi_reference_conflict_binds_both_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, _, _, value = prepare(root, reference_count=2)
            result = analyzer_result(value)
            result["fused_direction"]["conflicts"] = [
                {
                    "reference_ids": ["REF-001", "REF-002"],
                    "issue": "一篇强调先列责任，另一篇先从预算进入",
                    "resolution": "保留三个判断维度，不锁定唯一先后顺序",
                }
            ]
            self.assertIs(validate_analyzer_result(result, value), result)
            result["fused_direction"]["conflicts"][0]["reference_ids"] = ["REF-001"]
            with self.assertRaises(SlimRuntimeError):
                validate_analyzer_result(result, value)


class SkillEvidenceAndBoundaryTests(unittest.TestCase):
    def test_real_content_analyzer_forward_evidence_is_exact_and_complete(self) -> None:
        evidence_path = (
            FACTORY_ROOT
            / "audits"
            / "p2-gate-review"
            / "content-analyzer-forward-evidence.json"
        )
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        self.assertEqual(evidence["skill_invocation"]["skill"], "$content-analyzer")
        self.assertEqual(evidence["skill_invocation"]["invocation_count"], 1)
        self.assertFalse(evidence["skill_invocation"]["reviewer_created"])
        analyzer_input = validate_analyzer_input(evidence["sanitized_input"])
        result = validate_analyzer_result(
            evidence["actual_analyzer_output"], analyzer_input
        )
        self.assertEqual(len(analyzer_input["references"]), 2)
        self.assertEqual(
            {item["asset_role"] for item in analyzer_input["method_candidates"]},
            {"peer_content_asset", "oral_method_asset"},
        )
        self.assertEqual(build_gate_a(result, 1), evidence["final_gate_a"])
        self.assertEqual(set(evidence["checks"].values()), {"pass"})

    def test_project_state_preserves_passed_p2_gate(self) -> None:
        state = json.loads((FACTORY_ROOT / "project-state.json").read_text(encoding="utf-8"))
        self.assertIn("P2", state["phase"]["passed_gates"])

    def test_historical_design_card_receipt_remains_verifiable(self) -> None:
        design = FACTORY_ROOT / "designs" / "content-v2-slim" / "content-analyzer-design-card.md"
        receipt_path = FACTORY_ROOT / "designs" / "content-v2-slim" / "content-analyzer-skill-creator-receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["skill_name"], "content-analyzer")
        self.assertEqual(receipt["exit_code"], 0)
        self.assertEqual(receipt["design_card_sha256"], hashlib.sha256(design.read_bytes()).hexdigest())
        self.assertIn("initialized successfully", receipt["initializer_output"])
        update = receipt["structural_updates"][-1]
        self.assertEqual(update["design_card_sha256"], receipt["design_card_sha256"])
        self.assertTrue(update["changes"])
        self.assertRegex(update["final_skill_sha256"], r"^[0-9a-f]{64}$")
        for heading in (
            "## 名称",
            "## 唯一目的",
            "## 何时使用 / 何时不得使用",
            "## 唯一输入 / 唯一输出",
            "## AI 职责 / 程序职责",
            "## 依赖工具",
            "## 禁止访问范围",
            "## 错误与返修",
            "## 最小示例",
            "## P2 验收标准",
        ):
            self.assertIn(heading, design.read_text(encoding="utf-8"))

    def test_skill_creator_validator_passes_and_schemas_are_json(self) -> None:
        validator = FACTORY_ROOT / "tools/quick_validate_skill.py"
        completed = subprocess.run(
            [sys.executable, "-B", str(validator), str(ANALYZER_ROOT)],
            cwd=FACTORY_ROOT,
            check=False,
            text=True,
            capture_output=True,
            env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        for schema in (ANALYZER_ROOT / "schemas").glob("*.json"):
            self.assertIsInstance(json.loads(schema.read_text(encoding="utf-8")), dict)

    def test_p2_legacy_runtime_stays_absent_during_later_slim_phases(self) -> None:
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
        runtime_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in SLIM_ROOT.rglob("*.py")
        )
        old_names = selection["skills"]
        self.assertEqual([name for name in old_names if name in runtime_text], [])
        self.assertNotIn("Reviewer", runtime_text)
        self.assertNotIn("analyzer_program.py", runtime_text)
        self.assertNotIn("content_context_v2.json", runtime_text)


if __name__ == "__main__":
    unittest.main()
