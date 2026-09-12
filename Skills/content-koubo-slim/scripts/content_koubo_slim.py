#!/usr/bin/env python3
"""Content 口播 Slim entry through P5 package confirmation and safe save."""

from __future__ import annotations

import os
import sys
sys.dont_write_bytecode = True

# WorkBuddy may inject sitecustomize/file hooks through PYTHONPATH. Re-exec
# before importing the filesystem runtime; stdlib-only runtime needs no site.
if __name__ == "__main__" and not (sys.flags.isolated and sys.flags.no_site):
    os.execv(sys.executable, [sys.executable, "-I", "-S", "-B", __file__, *sys.argv[1:]])

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from runtime.client_manifest import load_manifest, resolve_asset_root, resolve_speaker_mode
from runtime.client_registry import (
    default_runs_root,
    load_effective_registry,
    resolve_client,
    select_client_id,
)
from runtime.content_source import (
    apply_obsidian_configuration,
    load_profile_index,
    plan_obsidian_configuration,
    select_profile,
)
from runtime.error_model import SlimRuntimeError
from runtime.reference_prep import (
    build_reference_index,
    preflight_references,
    write_prepared_references,
)
from runtime.run_store import RunStore
from runtime.schema_validation import (
    GATE_A_CHOICES,
    approval_snapshot,
    build_gate_a,
    build_writer_reference_blueprint,
    canonical_json_hash,
    validate_analyzer_input,
    validate_analyzer_result,
    validate_content_context,
    validate_context_retriever_input,
    validate_publish_pack_result,
    validate_writer_context,
    validate_writer_result,
)
from runtime.state_machine import SlimStateMachine
from runtime.vault_save import save_markdown_pair
from runtime.batch_tasks import start_request, batch_status, validate_single_request, batch_item_digest, save_suffix
from runtime.vault_reader import (
    read_knowledge_asset,
    read_method_asset,
    read_primary_profile,
    read_selected_profile,
)
from runtime.vault_search import (search_knowledge_assets, search_method_assets,
    discover_method_assets, select_method_assets, complete_method_text, method_kind, method_is_usable,
    method_source_metadata)


DRAFT_CHOICES = ("确认正文", "需要修改")
PACKAGE_CHOICES = ("确认并保存", "需要修改")
DECISION_TRAILING_PUNCTUATION = "。．，、！!？?"
CURRENT_STATE_ACTIONS = {
    "started": "先完成方向生成并展示 Gate A。",
    "direction_pending": "请选择认可整版方向、需要修改或不采用；修改时请给出具体意见。",
    "direction_approved": "准备当前 Run 的客户内容资料；不要改写已确认方向。",
    "context_pending": "生成唯一 Content Context Pack；不要重新检索或改写方向。",
    "context_ready": "生成完整口播正文；不要重新检索客户资料。",
    "draft_pending": "请选择确认正文，或给出具体修改意见。",
    "draft_approved": "可生成配套；如需调整正文，先提交具体修改意见。",
    "package_pending": "请选择确认并保存，或给出具体修改意见。",
    "package_approved": "保存已确认正文和配套；不要重新生成内容。",
    "blocked": "先处理当前阻断问题，再复用同一个 Run 继续。",
    "saved": "已保存；如需调整正文，可给出修改意见生成新版本，原文件保留。",
    "abandoned": "本次任务已结束；如需新选题，请开始一个新 Run。",
}


def _task_key_from_record(store: RunStore, task_record: str) -> str:
    return store.resolve_task_record(task_record)


def _normalize_topic(topic_original: str) -> str:
    return re.sub(r"\s+", " ", topic_original).strip()


def _bounded_search_signal(value: str, *, limit: int = 280) -> str:
    return value.strip()[:limit].rstrip()


def _limited_reference_search_fragments(content: str) -> list[str]:
    """Keep a few sentence-sized reference signals; never send a whole reference to 04 search."""

    fragments: list[tuple[int, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(re.split(r"[。！？!?；;\n]+", content)):
        bounded = _bounded_search_signal(item)
        if not bounded or bounded in seen:
            continue
        seen.add(bounded)
        fragments.append((index, bounded))
    # Longer, self-contained sentences tend to carry the actual subject and action.
    # Keep their original order and cap both count and total characters.
    selected = sorted(fragments, key=lambda item: (-len(item[1]), item[0]))[:8]
    selected.sort(key=lambda item: item[0])
    output: list[str] = []
    total = 0
    for _, fragment in selected:
        if output and total + len(fragment) > 1200:
            continue
        output.append(fragment)
        total += len(fragment)
    return output


def _method_search_query(
    *,
    topic_original: str,
    topic_normalized: str,
    user_thoughts: str | None,
    must_keep: list[str],
    prepared_references: list[Any],
) -> str:
    """Assemble the bounded, user-provided signals allowed for 04 retrieval."""

    signals = [topic_original, topic_normalized]
    if user_thoughts:
        signals.append(user_thoughts)
    signals.extend(must_keep)
    for reference in prepared_references:
        signals.append(reference.title)
        signals.extend(_limited_reference_search_fragments(reference.content))
    unique: list[str] = []
    for signal in signals:
        if not isinstance(signal, str):
            continue
        bounded = _bounded_search_signal(signal)
        if bounded and bounded not in unique:
            unique.append(bounded)
    return "\n".join(unique)


def _normalize_decision(value: str) -> str:
    """Only remove surrounding space and sentence-ending punctuation from a human choice."""

    if not isinstance(value, str):
        return value
    return value.strip().rstrip(DECISION_TRAILING_PUNCTUATION).strip()


def _current_state_error(
    *, store: RunStore, task_key: str, state: dict[str, Any], component: str, detail: str
) -> SlimRuntimeError:
    current = state["state"]
    artifacts_exist = store.artifacts_exist(task_key)
    return SlimRuntimeError(
        "SLIM_STATE_TRANSITION_INVALID",
        component,
        detail=detail,
        workflow_stage=SlimStateMachine.user_label(current),
        run_exists=True,
        artifacts_exist=artifacts_exist,
        artifacts_preserved=artifacts_exist,
        recovery_action=CURRENT_STATE_ACTIONS[current],
    )


def _verify_frozen_client_location(
    frozen: dict[str, Any],
    *,
    vault_root: Path,
    manifest_path: Path,
    binding_id: str | None = None,
    registry_sha256: str | None = None,
    workflow_stage: str = "正在准备客户内容资料",
) -> None:
    """Keep every stage of one Run bound to the client location used at start."""

    if (
        frozen.get("vault_root_resolved") != str(vault_root)
        or frozen.get("manifest_path_resolved") != str(manifest_path)
        or frozen.get("binding_id") is not None and frozen.get("binding_id") != binding_id
        or frozen.get("registry_sha256") is not None and frozen.get("registry_sha256") != registry_sha256
    ):
        raise SlimRuntimeError(
            "SLIM_TASK_IDENTITY_CHANGED",
            "content_koubo_slim",
            detail="current registry no longer matches the Run's frozen client location",
            workflow_stage=workflow_stage,
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )


def _verify_frozen_manifest(
    frozen: dict[str, Any], manifest: Any, *, workflow_stage: str
) -> None:
    expected = frozen.get("manifest_sha256")
    if expected is not None and manifest.manifest_sha256 != expected:
        raise SlimRuntimeError(
            "SLIM_TASK_IDENTITY_CHANGED",
            "content_koubo_slim",
            detail="Manifest changed after this Run was frozen",
            workflow_stage=workflow_stage,
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )


def _analyzer_input_version(
    store: RunStore, task_key: str, version: int
) -> dict[str, Any]:
    if not isinstance(version, int) or version < 1:
        raise SlimRuntimeError(
            "SLIM_ANALYZER_INPUT_INVALID",
            "content_koubo_slim",
            detail="analyzer input version is invalid",
            workflow_stage="正在拆解并匹配客户内容方向",
            run_exists=True,
        )
    return validate_analyzer_input(
        store.read_fixed_json(task_key, f"analyzer_input_v{version}.json")
    )


def prepare_direction_stage(
    *,
    registry_path: str | Path | None,
    runs_root: str | Path,
    client_id: str | None,
    speaker_mode: str | None,
    topic_original: str,
    reference_paths: list[str | Path],
    user_thoughts: str | None,
    must_keep: list[str],
    must_avoid: list[str],
    binding_id: str | None = None,
    profile: str | None = None,
    method_selections: list[dict[str, Any]] | None = None,
    planning_guidance: list[dict[str, Any]] | None = None,
    audience_scope: str | None = None,
    allow_experimental: bool = False,
    output_count: int = 1,
    batch_item: dict[str, str] | None = None,
) -> tuple[dict[str, Any], str]:
    validate_single_request(output_count, batch_item)
    if not isinstance(topic_original, str) or not topic_original.strip():
        raise SlimRuntimeError(
            "SLIM_ANALYZER_INPUT_INVALID",
            "content_koubo_slim",
            detail="topic_original is missing",
            workflow_stage="正在准备参考",
        )
    prepared = preflight_references(reference_paths)
    registry = load_effective_registry(registry_path)
    selected_binding = select_client_id(
        registry, client_id, requested_binding_id=binding_id
    )
    location = resolve_client(registry, selected_binding)
    resolved_client_id = location.client_id
    manifest = load_manifest(
        location.manifest_path, expected_client_id=resolved_client_id
    )
    if location.knowledge_base_id is not None and manifest.knowledge_base_id != location.knowledge_base_id:
        raise SlimRuntimeError(
            "SLIM_MANIFEST_INVALID", "content_koubo_slim", detail="Registry and Manifest knowledge_base_id differ"
        )
    resolved_mode = resolve_speaker_mode(speaker_mode, manifest)
    method_root = resolve_asset_root(location.vault_root, manifest, "method")
    selected_profile: dict[str, Any] | None = None
    profile_index_sha256: str | None = None
    if resolved_mode == "personal_ip":
        if location.common_contract:
            if location.profile_index_path is None or manifest.knowledge_base_id is None:
                raise SlimRuntimeError("SLIM_PROFILE_INVALID", "content_koubo_slim", detail="common Profile index is missing")
            index, profile_index_sha256 = load_profile_index(
                location.profile_index_path, knowledge_base_id=manifest.knowledge_base_id
            )
            selected_profile = select_profile(
                index,
                requested=profile,
                configured_default=location.default_profile_id,
            )
            profile_root = resolve_asset_root(location.vault_root, manifest, "profile")
            read_selected_profile(profile_root, selected_profile)
        elif profile is not None:
            raise SlimRuntimeError(
                "SLIM_PROFILE_INVALID",
                "content_koubo_slim",
                detail="legacy v2 configuration only supports its active primary Profile",
                recovery_action="请先运行 configure 迁移到通用合同，再选择任意 IP。",
            )
    reference_index = build_reference_index(prepared)
    topic_normalized = _normalize_topic(topic_original)
    query = _method_search_query(topic_original=topic_original, topic_normalized=topic_normalized,
                                user_thoughts=user_thoughts, must_keep=must_keep, prepared_references=prepared)
    if method_selections is not None:
        candidates = select_method_assets(method_root, method_selections, audience_scope=audience_scope,
                                           allow_experimental=allow_experimental)
    else:
        candidates = search_method_assets(method_root, query=query, audience_scope=audience_scope,
                                          allow_experimental=allow_experimental)
    if not prepared and not candidates:
        raise SlimRuntimeError("SLIM_ANALYZER_INPUT_INVALID", "content_koubo_slim",
            detail="no explicit reference or relevant library material selected",
            workflow_stage="正在寻找本题可用的库内资料",
            recovery_action="由 Agent 用 discover-methods 查看当前库同行和结构元数据，按本题目的选择后重试；确实缺资料时说明缺口，不要求你先懂结构编号。")
    guidance = _load_planning_guidance(method_root, planning_guidance or [], audience_scope, allow_experimental)
    business_identity = {
        "client_id": resolved_client_id,
        "speaker_mode": resolved_mode,
        "topic_original": topic_original,
        "reference_set_sha256": reference_index["reference_set_sha256"],
    }
    if location.common_contract:
        business_identity.update(
            {
                "binding_id": location.binding_id,
                "profile_id": selected_profile["profile_id"] if selected_profile else None,
            }
        )
    if not prepared or method_selections is not None or guidance:
        business_identity["library_input_sha256"] = canonical_json_hash({
            "candidates": candidates, "user_thoughts": user_thoughts,
            "must_keep": must_keep, "must_avoid": must_avoid,
            "audience_scope": audience_scope, "allow_experimental": allow_experimental, "planning_guidance": guidance})
    if batch_item is not None:
        business_identity["batch_item_sha256"] = batch_item_digest(batch_item)
    store = RunStore(runs_root)
    state, created, task_key = store.start_program_task(
        business_identity=business_identity,
        client_id=resolved_client_id,
        speaker_mode=resolved_mode,
    )
    run_dir = store.run_directory(task_key)
    _, written_reference_index = write_prepared_references(run_dir, prepared)
    if written_reference_index != reference_index:
        raise SlimRuntimeError(
            "SLIM_TASK_IDENTITY_CHANGED",
            "content_koubo_slim",
            detail="prepared references changed after task identity was generated",
            workflow_stage="正在准备参考",
            run_exists=True,
            artifacts_exist=store.artifacts_exist(task_key),
            artifacts_preserved=store.artifacts_exist(task_key),
        )
    frozen_input = {
        "contract_version": "content-koubo-slim-task-input-v1",
        "topic_original": topic_original,
        "topic_normalized": topic_normalized,
        "topic_normalized_source": "system_generated",
        "client_id": resolved_client_id,
        "speaker_mode": resolved_mode,
        "vault_root_resolved": str(location.vault_root),
        "manifest_path_resolved": str(location.manifest_path),
        "reference_set_sha256": reference_index["reference_set_sha256"],
        "references": [
            {
                "reference_id": item["reference_id"],
                "source_sha256": item["source_sha256"],
                "content_sha256": item["content_sha256"],
            }
            for item in reference_index["references"]
        ],
        "user_thoughts": user_thoughts,
        "must_keep": must_keep,
        "must_avoid": must_avoid,
        "task_key_generated_by": state["task_key_generated_by"],
        "task_key_record": state["task_key_record"],
        "task_key_retry_policy": state["task_key_retry_policy"],
    }
    if location.common_contract:
        frozen_input.update(
            {
                "binding_id": location.binding_id,
                "knowledge_base_id": location.knowledge_base_id,
                "profile_id": selected_profile["profile_id"] if selected_profile else None,
                "profile_ref": selected_profile["object_ref"] if selected_profile else None,
                "profile_sha256": selected_profile["content_sha256"] if selected_profile else None,
                "profile_display_name": selected_profile["display_name"] if selected_profile else None,
                "profile_index_path_resolved": str(location.profile_index_path) if location.profile_index_path else None,
                "profile_index_sha256": profile_index_sha256,
                "manifest_sha256": manifest.manifest_sha256,
                "registry_sha256": location.registry_sha256,
            }
        )
    if "library_input_sha256" in business_identity:
        frozen_input["library_input_sha256"] = business_identity["library_input_sha256"]
        frozen_input["source_mode"] = "external_with_library" if prepared else "library"
        frozen_input["audience_scope"] = audience_scope
        frozen_input["allow_experimental"] = allow_experimental
        frozen_input["planning_guidance"] = guidance
    if batch_item is not None:
        frozen_input["batch_item"] = batch_item
    store.freeze_task_input(task_key, frozen_input)
    analyzer_input = validate_analyzer_input(
        {
            "analysis_version": "slim-1.0",
            "topic_original": topic_original,
            "topic_normalized": topic_normalized,
            "topic_normalized_source": "system_generated",
            "client_id": resolved_client_id,
            "speaker_mode": resolved_mode,
            "user_thoughts": user_thoughts,
            "must_keep": must_keep,
            "must_avoid": must_avoid,
            "references": [item.analyzer_item() for item in prepared],
            "method_candidates": candidates,
            "revision_request": None,
            **({"planning_guidance": guidance} if guidance else {}),
        }
    )
    store.write_fixed_json(task_key, "analyzer_input_v1.json", analyzer_input)
    response = {
        "status": "working",
        "status_label": "正在拆解并匹配客户内容方向",
        "workflow_stage": "正在拆解并匹配客户内容方向",
        "message": "已准备本题的" + ("外部对标和库内资料" if prepared else "库内同行内容与方法候选") + "；下一步由 Agent 结合你的想法形成具体方向。",
        "next_action": "由 content-koubo-analyzer 生成完整方向后展示 Gate A。",
        "run_exists": True,
        "run_created_now": created,
        "artifacts_exist": True,
        "artifacts_preserved": True,
    }
    return response, state["task_key_record"]


def record_direction_result(
    *, store: RunStore, task_key: str, analyzer_result: dict[str, Any]
) -> tuple[dict[str, Any], Path]:
    state = store.get_task(task_key)
    if state["state"] not in {"started", "direction_pending"}:
        raise SlimRuntimeError(
            "SLIM_STATE_TRANSITION_INVALID",
            "content_koubo_slim",
            detail="direction result is not allowed in current state",
            workflow_stage=SlimStateMachine.user_label(state["state"]),
            run_exists=True,
            artifacts_exist=store.artifacts_exist(task_key),
            artifacts_preserved=store.artifacts_exist(task_key),
        )
    run_dir = store.run_directory(task_key)
    pattern = re.compile(r"^direction_v(\d+)\.json$")
    existing_versions = [
        int(match.group(1))
        for child in (run_dir / "artifacts").iterdir()
        if (match := pattern.fullmatch(child.name)) is not None
    ]
    next_version = max(existing_versions, default=0) + 1
    if next_version == 1 and state["state"] != "started":
        raise SlimRuntimeError(
            "SLIM_DIRECTION_RESPONSE_INVALID",
            "content_koubo_slim",
            detail="direction_v1 is only allowed from analyzer_input_v1 in started state",
            workflow_stage=SlimStateMachine.user_label(state["state"]),
            run_exists=True,
            artifacts_exist=store.artifacts_exist(task_key),
            artifacts_preserved=store.artifacts_exist(task_key),
        )
    analyzer_input = _analyzer_input_version(store, task_key, next_version)
    revision = analyzer_input["revision_request"]
    if next_version == 1 and revision is not None:
        raise SlimRuntimeError(
            "SLIM_ANALYZER_INPUT_INVALID",
            "content_koubo_slim",
            detail="analyzer_input_v1 cannot contain human revision feedback",
            workflow_stage="正在拆解并匹配客户内容方向",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    if next_version > 1 and (
        revision is None or revision["base_direction_version"] != next_version - 1
    ):
        raise SlimRuntimeError(
            "SLIM_DIRECTION_RESPONSE_INVALID",
            "content_koubo_slim",
            detail="next direction lacks matching human revision feedback",
            workflow_stage="等待你确认方向",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    validated = validate_analyzer_result(analyzer_result, analyzer_input)
    gate_a = build_gate_a(validated, next_version)
    direction = {
        "contract_version": "content-koubo-slim-direction-v1",
        "direction_version": next_version,
        "analyzer_input_version": next_version,
        "analyzer_result": validated,
        "gate_a": gate_a,
    }
    path = store.write_version(task_key, "direction", direction)
    actual_version = int(path.stem.rsplit("_v", 1)[1])
    if actual_version != next_version:
        raise SlimRuntimeError(
            "SLIM_VERSION_WRITE_FAILED",
            "content_koubo_slim",
            detail="direction version changed during write",
            workflow_stage="正在拆解并匹配客户内容方向",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    store.transition(task_key, "direction_pending")
    return gate_a, path


def _request_revision(
    store: RunStore, task_key: str, feedback: str, identity_changes: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(feedback, str) or not feedback.strip():
        raise SlimRuntimeError(
            "SLIM_DIRECTION_RESPONSE_INVALID",
            "content_koubo_slim",
            detail="revision feedback is empty",
            workflow_stage="等待你确认方向",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    if identity_changes:
        raise SlimRuntimeError(
            "SLIM_TASK_IDENTITY_CHANGED",
            "content_koubo_slim",
            detail="direction revision changes frozen task identity",
            workflow_stage="等待你确认方向",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    direction_version, _, _ = store.latest_version(task_key, "direction")
    current_input = _analyzer_input_version(store, task_key, direction_version)
    revised_input = dict(current_input)
    revised_input["revision_request"] = {
        "base_direction_version": direction_version,
        "feedback": feedback.strip(),
    }
    validate_analyzer_input(revised_input)
    next_path = (
        store.run_directory(task_key)
        / "artifacts"
        / f"analyzer_input_v{direction_version + 1}.json"
    )
    if next_path.exists():
        raise SlimRuntimeError(
            "SLIM_DIRECTION_RESPONSE_INVALID",
            "content_koubo_slim",
            detail="the current direction already has a human revision input",
            workflow_stage="等待你确认方向",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    store.write_fixed_json(task_key, next_path.name, revised_input)
    return revised_input


def respond_direction(
    *,
    store: RunStore,
    task_key: str,
    method_root: str | Path,
    decision: str,
    feedback: str | None = None,
    identity_changes: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    state = store.get_task(task_key)
    decision = _normalize_decision(decision)
    if state["state"] != "direction_pending":
        raise _current_state_error(
            store=store,
            task_key=task_key,
            state=state,
            component="content_koubo_slim",
            detail=f"respond-direction is not allowed from state={state['state']!r}",
        )
    if decision not in GATE_A_CHOICES:
        raise SlimRuntimeError(
            "SLIM_DIRECTION_RESPONSE_INVALID",
            "content_koubo_slim",
            detail=f"state={state['state']!r}, decision={decision!r}",
            workflow_stage=SlimStateMachine.user_label(state["state"]),
            run_exists=True,
            artifacts_exist=store.artifacts_exist(task_key),
            artifacts_preserved=store.artifacts_exist(task_key),
        )
    if decision == "需要修改":
        revised_input = _request_revision(
            store, task_key, feedback or "", identity_changes or {}
        )
        response = {
            "status": "working",
            "status_label": "正在修改写作方向",
            "workflow_stage": "等待你确认方向",
            "message": "修改意见已保留在同一个 Run，旧方向没有被覆盖。",
            "next_action": "按这条具体意见生成下一版完整方向。",
            "run_exists": True,
            "run_created_now": False,
            "artifacts_exist": True,
            "artifacts_preserved": True,
        }
        return response, revised_input
    if feedback or identity_changes:
        raise SlimRuntimeError(
            "SLIM_DIRECTION_RESPONSE_INVALID",
            "content_koubo_slim",
            detail="feedback or identity changes are only valid for revision",
            workflow_stage="等待你确认方向",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    if decision == "不采用":
        store.transition(task_key, "abandoned")
        return (
            {
                "status": "abandoned",
                "status_label": "已结束",
                "workflow_stage": "已结束",
                "message": "本次方向未采用，已有方向版本保留；没有生成正文或保存客户内容。",
                "next_action": "如需更换任务身份，请开始一个新 Run。",
                "run_exists": True,
                "run_created_now": False,
                "artifacts_exist": True,
                "artifacts_preserved": True,
            },
            None,
        )

    direction_version, direction, _ = store.latest_version(task_key, "direction")
    if (
        direction.get("direction_version") != direction_version
        or direction.get("analyzer_input_version") != direction_version
        or direction.get("gate_a", {}).get("direction_version") != direction_version
    ):
        raise SlimRuntimeError(
            "SLIM_DIRECTION_RESPONSE_INVALID",
            "content_koubo_slim",
            detail="latest direction is not bound to the displayed Gate A version",
            workflow_stage="等待你确认方向",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    result = direction["analyzer_result"]
    _verify_planning_guidance(store.read_task_input(task_key), method_root)
    for selected in result["selected_method_assets"]:
        read_method_asset(
            method_root,
            selected["relative_path"],
            expected_sha256=selected["page_sha256"],
        )
    approved = approval_snapshot(result, direction["gate_a"], direction_version)
    store.write_fixed_json(task_key, "approved_direction.json", approved)
    store.transition(task_key, "direction_approved")
    return (
        {
            "status": "waiting",
            "status_label": "方向已确认",
            "workflow_stage": "正在准备客户内容资料",
            "message": "整版方向已冻结，尚未读取 03/05，也没有生成正文。",
            "next_action": "准备当前 Run 的客户内容资料；不要改写已确认方向。",
            "run_exists": True,
            "run_created_now": False,
            "artifacts_exist": True,
            "artifacts_preserved": True,
        },
        None,
    )


def prepare_context_stage(
    *,
    registry_path: str | Path,
    runs_root: str | Path,
    task_record: str,
) -> tuple[dict[str, Any], str]:
    """Build the in-memory AI handoff without persisting a second Pack."""

    store = RunStore(runs_root)
    task_key = _task_key_from_record(store, task_record)
    state = store.get_task(task_key)
    if state["state"] not in {"direction_approved", "context_pending"}:
        raise SlimRuntimeError(
            "SLIM_STATE_TRANSITION_INVALID",
            "content_koubo_slim",
            detail="context preparation requires an approved direction",
            workflow_stage=SlimStateMachine.user_label(state["state"]),
            run_exists=True,
            artifacts_exist=store.artifacts_exist(task_key),
            artifacts_preserved=store.artifacts_exist(task_key),
        )
    frozen = store.read_task_input(task_key)
    approved = store.read_fixed_json(task_key, "approved_direction.json")
    expected_approval_fields = {
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
    }
    if (
        set(approved) != expected_approval_fields
        or approved.get("approval_version") != "content-koubo-slim-approved-direction-v1"
        or approved.get("speaker_mode") != frozen.get("speaker_mode")
        or approved.get("approved_gate_a", {}).get("direction_version")
        != approved.get("direction_version")
        or canonical_json_hash(approved.get("approved_gate_a"))
        != approved.get("gate_a_sha256")
    ):
        raise SlimRuntimeError(
            "SLIM_CONTEXT_INPUT_INVALID",
            "content_koubo_slim",
            detail="approved direction snapshot is incomplete or no longer bound to Gate A",
            workflow_stage="正在准备客户内容资料",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )

    direction_version, direction, _ = store.latest_version(task_key, "direction")
    if (
        direction_version != approved["direction_version"]
        or direction.get("direction_version") != direction_version
        or direction.get("analyzer_input_version") != direction_version
        or direction.get("gate_a") != approved["approved_gate_a"]
    ):
        raise SlimRuntimeError(
            "SLIM_CONTEXT_INPUT_INVALID",
            "content_koubo_slim",
            detail="approved direction is not bound to the detailed Analyzer report",
            workflow_stage="正在准备客户内容资料",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    analyzer_input = _analyzer_input_version(store, task_key, direction_version)
    analyzer_result = validate_analyzer_result(
        direction.get("analyzer_result"), analyzer_input
    )
    writer_reference_blueprint = build_writer_reference_blueprint(analyzer_result)

    registry = load_effective_registry(registry_path)
    location = resolve_client(registry, frozen.get("binding_id") or frozen["client_id"])
    _verify_frozen_client_location(
        frozen,
        vault_root=location.vault_root,
        manifest_path=location.manifest_path,
        binding_id=location.binding_id,
        registry_sha256=location.registry_sha256,
    )
    manifest = load_manifest(
        location.manifest_path, expected_client_id=frozen["client_id"]
    )
    _verify_frozen_manifest(frozen, manifest, workflow_stage="正在准备客户内容资料")
    resolved_mode = resolve_speaker_mode(frozen["speaker_mode"], manifest)
    method_root = resolve_asset_root(location.vault_root, manifest, "method")
    _verify_planning_guidance(frozen, method_root)
    selected_04_assets: list[dict[str, Any]] = []
    for selected in approved["selected_method_assets"]:
        asset = read_method_asset(
            method_root,
            selected["relative_path"],
            expected_sha256=selected["page_sha256"],
        )
        if asset.asset_id != selected["asset_id"] or asset.asset_role != selected["asset_role"]:
            raise SlimRuntimeError(
                "SLIM_CONTEXT_INPUT_INVALID",
                "content_koubo_slim",
                detail="P2 selected 04 identity or role changed",
                workflow_stage="正在准备客户内容资料",
                run_exists=True,
                artifacts_exist=True,
                artifacts_preserved=True,
            )
        selected_04_assets.append(
            {
                "asset_id": asset.asset_id,
                "asset_role": asset.asset_role,
                "relative_path": asset.relative_path,
                "page_sha256": asset.page_sha256,
                "title": asset.title,
                "source_excerpt": complete_method_text(asset),
                "approved_usage": selected["usage"],
                **({"source_metadata": method_source_metadata(asset)} if "library_input_sha256" in frozen else {}),
            }
        )

    needs = approved["business_context_needs"]
    knowledge_candidates: list[dict[str, Any]] = []
    if needs:
        knowledge_root = resolve_asset_root(location.vault_root, manifest, "knowledge")
        knowledge_candidates = search_knowledge_assets(knowledge_root, needs=needs)

    profile_candidate: dict[str, Any] | None = None
    if resolved_mode == "personal_ip":
        profile_root = resolve_asset_root(location.vault_root, manifest, "profile")
        if location.common_contract:
            if location.profile_index_path is None or manifest.knowledge_base_id is None:
                raise SlimRuntimeError("SLIM_PROFILE_INVALID", "content_koubo_slim", detail="common Profile index is missing")
            index, index_sha256 = load_profile_index(
                location.profile_index_path, knowledge_base_id=manifest.knowledge_base_id
            )
            if index_sha256 != frozen.get("profile_index_sha256"):
                raise SlimRuntimeError(
                    "SLIM_TASK_IDENTITY_CHANGED",
                    "content_koubo_slim",
                    detail="Profile index changed after this Run was frozen",
                    workflow_stage="正在准备客户内容资料",
                    run_exists=True,
                    artifacts_exist=True,
                    artifacts_preserved=True,
                )
            selected = select_profile(
                index,
                requested=frozen.get("profile_id"),
                configured_default=None,
            )
            if (
                selected.get("object_ref") != frozen.get("profile_ref")
                or selected.get("content_sha256") != frozen.get("profile_sha256")
            ):
                raise SlimRuntimeError(
                    "SLIM_TASK_IDENTITY_CHANGED",
                    "content_koubo_slim",
                    detail="selected Profile changed after this Run was frozen",
                    workflow_stage="正在准备客户内容资料",
                    run_exists=True,
                    artifacts_exist=True,
                    artifacts_preserved=True,
                )
            profile = read_selected_profile(profile_root, selected)
        else:
            profile = read_primary_profile(profile_root, manifest.profile_selector)
        profile_candidate = {
            "relative_path": profile.relative_path,
            "page_sha256": profile.page_sha256,
            "title": profile.title,
            "content": profile.body[:12000].rstrip(),
        }

    boundaries = approved["approved_direction"]["user_boundaries"]
    context_input = validate_context_retriever_input(
        {
            "context_version": "slim-1.0",
            **({"source_mode": "library"} if frozen.get("source_mode") == "library" else {}),
            "client_id": frozen["client_id"],
            "speaker_mode": resolved_mode,
            "task_input": {
                "topic_original": frozen["topic_original"],
                "user_thoughts": boundaries["user_thoughts"],
                "must_keep": boundaries["must_keep"],
                "must_avoid": boundaries["must_avoid"],
            },
            "approved_direction": approved["approved_direction"],
            "selected_external_reference_mechanisms": writer_reference_blueprint,
            "selected_04_assets": selected_04_assets,
            "business_context_needs": needs,
            "knowledge_candidates": knowledge_candidates,
            "profile_candidate": profile_candidate,
            "writer_mode": approved["writer_mode"],
            "secondary_tactics": approved["secondary_tactics"],
        }
    )
    if state["state"] == "direction_approved":
        store.transition(task_key, "context_pending")
    return context_input, task_key


def record_context_result(
    *,
    registry_path: str | Path,
    runs_root: str | Path,
    task_record: str,
    context_result: dict[str, Any],
) -> tuple[dict[str, Any], Path]:
    context_input, task_key = prepare_context_stage(
        registry_path=registry_path,
        runs_root=runs_root,
        task_record=task_record,
    )
    store = RunStore(runs_root)
    state = store.get_task(task_key)
    if state["state"] != "context_pending":
        raise SlimRuntimeError(
            "SLIM_STATE_TRANSITION_INVALID",
            "content_koubo_slim",
            detail="context result is not allowed in current state",
            workflow_stage=SlimStateMachine.user_label(state["state"]),
            run_exists=True,
            artifacts_exist=store.artifacts_exist(task_key),
            artifacts_preserved=store.artifacts_exist(task_key),
        )
    validated = validate_content_context(context_result, context_input)
    source_snapshot = {
        "contract_version": "content-koubo-slim-source-snapshot-v1",
        "methods": [
            {"relative_path": item["relative_path"], "page_sha256": item["page_sha256"]}
            for item in context_input["selected_04_assets"]
        ],
        "knowledge": [
            {"relative_path": item["relative_path"], "page_sha256": item["page_sha256"]}
            for item in context_input["knowledge_candidates"]
        ],
        "profile": (
            {
                "relative_path": context_input["profile_candidate"]["relative_path"],
                "page_sha256": context_input["profile_candidate"]["page_sha256"],
            }
            if context_input["profile_candidate"] is not None
            else None
        ),
    }
    store.write_fixed_json(task_key, "source_snapshot_v1.json", source_snapshot)
    path = store.write_fixed_json(task_key, "content_context_v1.json", validated)
    store.transition(task_key, "context_ready")
    response = {
        "status": "waiting",
        "status_label": "客户内容资料已准备",
        "workflow_stage": "客户内容资料已准备",
        "message": "唯一 Content Context Pack 已生成，尚未生成正文。",
        "next_action": "基于唯一 Content Context Pack 生成正文；不要再次检索客户资料。",
        "run_exists": True,
        "run_created_now": False,
        "artifacts_exist": True,
        "artifacts_preserved": True,
    }
    return response, path


def _approval_filename(store: RunStore, task_key: str, kind: str, version: int) -> str:
    legacy = f"approved_{kind}.json"
    target = store.run_directory(task_key) / "artifacts" / legacy
    if target.exists() or target.is_symlink():
        old = store.read_fixed_json(task_key, legacy)
        if old.get(f"{kind}_version") != version:
            return f"approved_{kind}_v{version}.json"
    return legacy


def prepare_draft_stage(
    *,
    runs_root: str | Path,
    task_record: str,
    revision_feedback: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Prepare the one-mode Writer handoff without reopening customer Vault assets."""

    store = RunStore(runs_root)
    task_key = _task_key_from_record(store, task_record)
    state = store.get_task(task_key)
    if state["state"] not in {"context_ready", "draft_pending", "draft_approved", "package_pending", "package_approved", "saved"}:
        raise SlimRuntimeError(
            "SLIM_STATE_TRANSITION_INVALID",
            "content_koubo_slim",
            detail="draft preparation requires context_ready or draft_pending",
            workflow_stage=SlimStateMachine.user_label(state["state"]),
            run_exists=True,
            artifacts_exist=store.artifacts_exist(task_key),
            artifacts_preserved=store.artifacts_exist(task_key),
        )
    feedback = revision_feedback.strip() if isinstance(revision_feedback, str) else None
    if state["state"] == "context_ready" and feedback:
        raise SlimRuntimeError(
            "SLIM_DRAFT_RESPONSE_INVALID",
            "content_koubo_slim",
            detail="draft_v1 cannot contain revision feedback",
            workflow_stage="正在生成正文",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    if state["state"] != "context_ready" and not feedback:
        raise SlimRuntimeError(
            "SLIM_DRAFT_RESPONSE_INVALID",
            "content_koubo_slim",
            detail="draft revision feedback is empty",
            workflow_stage="等待你确认正文",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )

    frozen = store.read_task_input(task_key)
    approved = store.read_fixed_json(task_key, "approved_direction.json")
    context = validate_writer_context(
        store.read_fixed_json(task_key, "content_context_v1.json"),
        frozen_task=frozen,
        approved_snapshot=approved,
    )
    base_version = 0
    previous_draft: dict[str, Any] | None = None
    if state["state"] != "context_ready":
        base_version, current, _ = store.latest_version(task_key, "draft")
        if current.get("draft_version") != base_version:
            raise SlimRuntimeError(
                "SLIM_DRAFT_RESPONSE_INVALID",
                "content_koubo_slim",
                detail="latest draft version binding is invalid",
                workflow_stage="等待你确认正文",
                run_exists=True,
                artifacts_exist=True,
                artifacts_preserved=True,
            )
        previous_draft = {
            "draft_version": base_version,
            "paragraphs": current["paragraphs"],
            "body": current["body"],
        }
    writer_input = {
        "content_context": context,
        "mode_reference": f"references/modes/{context['writer_mode']}.md",
        "base_draft_version": base_version,
        "previous_draft": previous_draft,
        "revision_request": feedback,
    }
    return writer_input, task_key


def record_draft_result(
    *,
    runs_root: str | Path,
    task_record: str,
    base_draft_version: int,
    writer_result: dict[str, Any],
    revision_feedback: str | None = None,
) -> tuple[dict[str, Any], tuple[Path, Path]]:
    writer_input, task_key = prepare_draft_stage(
        runs_root=runs_root,
        task_record=task_record,
        revision_feedback=revision_feedback,
    )
    if writer_input["base_draft_version"] != base_draft_version:
        raise SlimRuntimeError(
            "SLIM_DRAFT_RESPONSE_INVALID",
            "content_koubo_slim",
            detail="Writer result is not based on the current draft version",
            workflow_stage="等待你确认正文" if base_draft_version else "正在生成正文",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    validated, body = validate_writer_result(writer_result)
    next_version = base_draft_version + 1
    context = writer_input["content_context"]
    draft = {
        "contract_version": "content-koubo-slim-draft-v1",
        "draft_version": next_version,
        "based_on_context": "content_context_v1.json",
        "writer_mode": context["writer_mode"],
        "revision_of": base_draft_version or None,
        "revision_request": writer_input["revision_request"],
        "paragraphs": validated["paragraphs"],
        "body": body,
    }
    store = RunStore(runs_root)
    paths = store.write_version_bundle(
        task_key,
        "draft",
        expected_version=next_version,
        json_payload=draft,
        markdown_text=body + "\n",
    )
    store.transition(task_key, "draft_pending")
    return (
        {
            "status": "waiting",
            "status_label": "等待你确认正文",
            "workflow_stage": "等待你确认正文",
            "message": "完整口播正文已生成，请确认或给出具体修改意见。",
            "next_action": "请选择确认正文，或说明需要修改的具体位置和方向。",
            "run_exists": True,
            "run_created_now": False,
            "artifacts_exist": True,
            "artifacts_preserved": True,
            "draft": {"draft_version": next_version, "body": body},
        },
        paths,
    )


def respond_draft(
    *,
    runs_root: str | Path,
    task_record: str,
    decision: str,
    feedback: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    store = RunStore(runs_root)
    task_key = _task_key_from_record(store, task_record)
    state = store.get_task(task_key)
    decision = _normalize_decision(decision)
    revisable = {"draft_approved", "package_pending", "package_approved", "saved"}
    if state["state"] != "draft_pending" and not (decision == "需要修改" and state["state"] in revisable):
        raise _current_state_error(
            store=store,
            task_key=task_key,
            state=state,
            component="content_koubo_slim",
            detail=f"respond-draft is not allowed from state={state['state']!r}",
        )
    if decision not in DRAFT_CHOICES:
        raise SlimRuntimeError(
            "SLIM_DRAFT_RESPONSE_INVALID",
            "content_koubo_slim",
            detail=f"state={state['state']!r}, decision={decision!r}",
            workflow_stage=SlimStateMachine.user_label(state["state"]),
            run_exists=True,
            artifacts_exist=store.artifacts_exist(task_key),
            artifacts_preserved=store.artifacts_exist(task_key),
        )
    if decision == "需要修改":
        writer_input, _ = prepare_draft_stage(
            runs_root=runs_root,
            task_record=task_record,
            revision_feedback=feedback,
        )
        if state["state"] in revisable:
            store.transition(task_key, "draft_pending")
        return (
            {
                "status": "working",
                "status_label": "正在修改正文",
                "workflow_stage": "等待你确认正文",
                "message": "修改意见已绑定当前正文，旧版本保持不变。",
                "next_action": "按这条意见生成下一版完整正文。",
                "run_exists": True,
                "run_created_now": False,
                "artifacts_exist": True,
                "artifacts_preserved": True,
            },
            writer_input,
        )
    if feedback:
        raise SlimRuntimeError(
            "SLIM_DRAFT_RESPONSE_INVALID",
            "content_koubo_slim",
            detail="confirmation must not include revision feedback",
            workflow_stage="等待你确认正文",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    version, draft, json_path = store.latest_version(task_key, "draft")
    markdown_path = json_path.with_suffix(".md")
    try:
        markdown = markdown_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SlimRuntimeError(
            "SLIM_DRAFT_RESPONSE_INVALID",
            "content_koubo_slim",
            detail=str(exc),
            workflow_stage="等待你确认正文",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        ) from exc
    if draft.get("draft_version") != version or markdown != draft.get("body", "") + "\n":
        raise SlimRuntimeError(
            "SLIM_DRAFT_RESPONSE_INVALID",
            "content_koubo_slim",
            detail="latest JSON and Markdown draft versions do not match",
            workflow_stage="等待你确认正文",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    approval = {
        "approval_version": "content-koubo-slim-approved-draft-v1",
        "draft_version": version,
        "draft_sha256": canonical_json_hash(draft),
        "decision": "确认正文",
    }
    filename = _approval_filename(store, task_key, "draft", version)
    target = store.run_directory(task_key) / "artifacts" / filename
    if target.exists() or target.is_symlink():
        raise SlimRuntimeError("SLIM_DRAFT_RESPONSE_INVALID", "content_koubo_slim",
            detail="generate and display a new draft before confirming a reopened draft",
            workflow_stage="等待你确认正文", run_exists=True, artifacts_exist=True, artifacts_preserved=True)
    store.write_fixed_json(task_key, filename, approval)
    store.transition(task_key, "draft_approved")
    return (
        {
            "status": "waiting",
            "status_label": "正文已确认",
            "workflow_stage": "正文已确认",
            "message": "当前正文已确认，可以基于这份正文生成配套文案。",
            "next_action": CURRENT_STATE_ACTIONS["draft_approved"],
            "run_exists": True,
            "run_created_now": False,
            "artifacts_exist": True,
            "artifacts_preserved": True,
        },
        None,
    )


def _approved_draft_input(store: RunStore, task_key: str) -> tuple[dict[str, Any], dict[str, Any]]:
    version, draft, json_path = store.latest_version(task_key, "draft")
    approval = store.read_fixed_json(task_key, _approval_filename(store, task_key, "draft", version))
    expected_fields = {"approval_version", "draft_version", "draft_sha256", "decision"}
    try:
        markdown = json_path.with_suffix(".md").read_text(encoding="utf-8")
    except OSError as exc:
        raise SlimRuntimeError(
            "SLIM_PACKAGE_OUTPUT_INVALID",
            "content_koubo_slim",
            detail=str(exc),
            workflow_stage="正在生成配套文案",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        ) from exc
    if (
        set(approval) != expected_fields
        or approval.get("approval_version") != "content-koubo-slim-approved-draft-v1"
        or approval.get("decision") != "确认正文"
        or approval.get("draft_version") != version
        or approval.get("draft_sha256") != canonical_json_hash(draft)
        or draft.get("draft_version") != version
        or markdown != draft.get("body", "") + "\n"
    ):
        raise SlimRuntimeError(
            "SLIM_PACKAGE_OUTPUT_INVALID",
            "content_koubo_slim",
            detail="approved draft no longer matches the latest JSON/Markdown body",
            workflow_stage="正在生成配套文案",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    return {"draft_version": version, "body": draft["body"]}, approval


def prepare_package_stage(
    *,
    runs_root: str | Path,
    task_record: str,
    revision_feedback: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Prepare the one P5 semantic handoff from the confirmed body only."""

    store = RunStore(runs_root)
    task_key = _task_key_from_record(store, task_record)
    state = store.get_task(task_key)
    if state["state"] not in {"draft_approved", "package_pending"}:
        raise SlimRuntimeError(
            "SLIM_STATE_TRANSITION_INVALID",
            "content_koubo_slim",
            detail="package preparation requires draft_approved or package_pending",
            workflow_stage=SlimStateMachine.user_label(state["state"]),
            run_exists=True,
            artifacts_exist=store.artifacts_exist(task_key),
            artifacts_preserved=store.artifacts_exist(task_key),
        )
    feedback = revision_feedback.strip() if isinstance(revision_feedback, str) else None
    if state["state"] == "package_pending" and not feedback:
        raise SlimRuntimeError(
            "SLIM_PACKAGE_RESPONSE_INVALID",
            "content_koubo_slim",
            detail="package revision feedback is empty",
            workflow_stage="等待你确认并保存",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )

    approved_draft, approval = _approved_draft_input(store, task_key)
    base_version = 0
    previous_package: dict[str, Any] | None = None
    has_packages = any((store.run_directory(task_key) / "artifacts").glob("package_v*.json"))
    if has_packages:
        base_version, current, _ = store.latest_version(task_key, "package")
    if state["state"] == "package_pending":
        expected_fields = {
            "contract_version",
            "package_version",
            "based_on_draft_version",
            "based_on_draft_sha256",
            "revision_of",
            "revision_request",
            "content",
        }
        if (
            set(current) != expected_fields
            or current.get("contract_version") != "content-koubo-slim-package-v1"
            or current.get("package_version") != base_version
            or current.get("based_on_draft_version") != approved_draft["draft_version"]
            or current.get("based_on_draft_sha256") != approval["draft_sha256"]
        ):
            raise SlimRuntimeError(
                "SLIM_PACKAGE_RESPONSE_INVALID",
                "content_koubo_slim",
                detail="latest package version binding is invalid",
                workflow_stage="等待你确认并保存",
                run_exists=True,
                artifacts_exist=True,
                artifacts_preserved=True,
            )
        previous_package = validate_publish_pack_result(current["content"])
    return (
        {
            "approved_draft": approved_draft,
            "base_package_version": base_version,
            "previous_package": previous_package,
            "revision_request": feedback,
        },
        task_key,
    )


def record_package_result(
    *,
    runs_root: str | Path,
    task_record: str,
    base_package_version: int,
    package_result: dict[str, Any],
    revision_feedback: str | None = None,
    based_on_draft_version: int | None = None,
) -> tuple[dict[str, Any], Path]:
    package_input, task_key = prepare_package_stage(
        runs_root=runs_root,
        task_record=task_record,
        revision_feedback=revision_feedback,
    )
    current_draft_version = package_input["approved_draft"]["draft_version"]
    # Old first-draft callers remain compatible; revised drafts require the
    # generation-time body version, never stamp a late result with a new body.
    expected_draft_version = 1 if based_on_draft_version is None else based_on_draft_version
    if type(expected_draft_version) is not int or expected_draft_version != current_draft_version:
        raise SlimRuntimeError("SLIM_PACKAGE_RESPONSE_INVALID", "content_koubo_slim",
            detail="publish pack was generated for a different draft version",
            workflow_stage="正在生成配套文案", run_exists=True, artifacts_exist=True, artifacts_preserved=True)
    if package_input["base_package_version"] != base_package_version:
        raise SlimRuntimeError(
            "SLIM_PACKAGE_RESPONSE_INVALID",
            "content_koubo_slim",
            detail="publish pack result is not based on the current package version",
            workflow_stage=(
                "等待你确认并保存" if base_package_version else "正在生成配套文案"
            ),
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    validated = validate_publish_pack_result(package_result)
    store = RunStore(runs_root)
    _, draft_approval = _approved_draft_input(store, task_key)
    next_version = base_package_version + 1
    package = {
        "contract_version": "content-koubo-slim-package-v1",
        "package_version": next_version,
        "based_on_draft_version": package_input["approved_draft"]["draft_version"],
        "based_on_draft_sha256": draft_approval["draft_sha256"],
        "revision_of": base_package_version or None,
        "revision_request": package_input["revision_request"],
        "content": validated,
    }
    path = store.write_version(task_key, "package", package)
    actual_version = int(path.stem.rsplit("_v", 1)[1])
    if actual_version != next_version:
        raise SlimRuntimeError(
            "SLIM_VERSION_WRITE_FAILED",
            "content_koubo_slim",
            detail="package version changed during write",
            workflow_stage="正在生成配套文案",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    store.transition(task_key, "package_pending")
    return (
        {
            "status": "waiting",
            "status_label": "等待你确认并保存",
            "workflow_stage": "等待你确认并保存",
            "message": "标题、发布正文和标签已生成，请确认并保存或给出具体修改意见。",
            "next_action": "请选择确认并保存，或说明需要修改的具体内容。",
            "run_exists": True,
            "run_created_now": False,
            "artifacts_exist": True,
            "artifacts_preserved": True,
            "package": {"package_version": next_version, **validated},
        },
        path,
    )


def _package_markdown(approval: dict[str, Any], content: dict[str, Any]) -> str:
    return (
        f"封面标题：{approval['selected_cover_title']}\n\n"
        f"发布标题：{approval['selected_publish_title']}\n\n"
        f"发布说明：\n{content['publish_copy']}\n\n"
        f"标签：\n{' '.join(content['tags'])}"
    )


def _verify_source_snapshot_before_save(
    *, store: RunStore, task_key: str, frozen: dict[str, Any], location: Any, manifest: Any
) -> None:
    _verify_planning_guidance(frozen, resolve_asset_root(location.vault_root, manifest, "method"))
    if "manifest_sha256" not in frozen:
        # Pre-v3 Runs keep their original behavior and remain resumable.
        return
    snapshot = store.read_fixed_json(task_key, "source_snapshot_v1.json")
    if snapshot.get("contract_version") != "content-koubo-slim-source-snapshot-v1":
        raise SlimRuntimeError(
            "SLIM_TASK_IDENTITY_CHANGED", "content_koubo_slim", detail="source snapshot is invalid",
            workflow_stage="等待你确认并保存", run_exists=True, artifacts_exist=True, artifacts_preserved=True,
        )
    method_root = resolve_asset_root(location.vault_root, manifest, "method")
    for item in snapshot.get("methods", []):
        read_method_asset(method_root, item["relative_path"], expected_sha256=item["page_sha256"])
    knowledge_root = resolve_asset_root(location.vault_root, manifest, "knowledge")
    for item in snapshot.get("knowledge", []):
        read_knowledge_asset(knowledge_root, item["relative_path"], expected_sha256=item["page_sha256"])
    profile_snapshot = snapshot.get("profile")
    if profile_snapshot is not None:
        profile_root = resolve_asset_root(location.vault_root, manifest, "profile")
        if location.common_contract:
            index, index_sha256 = load_profile_index(
                location.profile_index_path, knowledge_base_id=manifest.knowledge_base_id
            )
            if index_sha256 != frozen.get("profile_index_sha256"):
                raise SlimRuntimeError(
                    "SLIM_TASK_IDENTITY_CHANGED", "content_koubo_slim", detail="Profile index changed after Gate A",
                    workflow_stage="等待你确认并保存", run_exists=True, artifacts_exist=True, artifacts_preserved=True,
                )
            selected = select_profile(index, requested=frozen.get("profile_id"), configured_default=None)
            profile = read_selected_profile(profile_root, selected)
        else:
            profile = read_primary_profile(profile_root, manifest.profile_selector)
        if profile.relative_path != profile_snapshot.get("relative_path") or profile.page_sha256 != profile_snapshot.get("page_sha256"):
            raise SlimRuntimeError(
                "SLIM_TASK_IDENTITY_CHANGED", "content_koubo_slim", detail="Profile changed after Gate A",
                workflow_stage="等待你确认并保存", run_exists=True, artifacts_exist=True, artifacts_preserved=True,
            )


def _save_approved_package(
    *,
    registry_path: str | Path,
    runs_root: str | Path,
    task_key: str,
) -> dict[str, Any]:
    store = RunStore(runs_root)
    try:
        frozen = store.read_task_input(task_key)
        approved_draft, draft_approval = _approved_draft_input(store, task_key)
        version, package, _ = store.latest_version(task_key, "package")
        content = validate_publish_pack_result(package.get("content"))
        approval = store.read_fixed_json(task_key, _approval_filename(store, task_key, "package", version))
        expected_fields = {
            "approval_version",
            "package_version",
            "package_sha256",
            "draft_version",
            "draft_sha256",
            "selected_cover_title",
            "selected_publish_title",
            "decision",
            "publish_status",
        }
        if (
            set(approval) != expected_fields
            or approval.get("approval_version") != "content-koubo-slim-approved-package-v1"
            or approval.get("package_version") != version
            or approval.get("package_sha256") != canonical_json_hash(package)
            or approval.get("draft_version") != approved_draft["draft_version"]
            or approval.get("draft_sha256") != draft_approval["draft_sha256"]
            or approval.get("selected_cover_title") not in content["cover_titles"]
            or approval.get("selected_publish_title") not in content["publish_titles"]
            or approval.get("decision") != "确认并保存"
            or approval.get("publish_status") != "not_requested"
        ):
            raise SlimRuntimeError(
                "SLIM_PACKAGE_RESPONSE_INVALID",
                "content_koubo_slim",
                detail="approved package no longer matches the latest confirmed package",
                workflow_stage="等待你确认并保存",
                run_exists=True,
                artifacts_exist=True,
                artifacts_preserved=True,
            )

        registry = load_effective_registry(registry_path)
        location = resolve_client(registry, frozen.get("binding_id") or frozen["client_id"])
        _verify_frozen_client_location(
            frozen,
            vault_root=location.vault_root,
            manifest_path=location.manifest_path,
            binding_id=location.binding_id,
            registry_sha256=location.registry_sha256,
            workflow_stage="等待你确认并保存",
        )
        manifest = load_manifest(
            location.manifest_path, expected_client_id=frozen["client_id"]
        )
        _verify_frozen_manifest(frozen, manifest, workflow_stage="等待你确认并保存")
        _verify_source_snapshot_before_save(
            store=store,
            task_key=task_key,
            frozen=frozen,
            location=location,
            manifest=manifest,
        )
        output_root = resolve_asset_root(location.vault_root, manifest, "output")
        saved_pair = save_markdown_pair(
            output_root=output_root,
            output_template=manifest.output_template,
            client_id=frozen.get("profile_id") or frozen["client_id"],
            selected_publish_title=approval["selected_publish_title"],
            oral_body=approved_draft["body"],
            package_markdown=_package_markdown(approval, content),
            draft_version=approved_draft["draft_version"],
            item_suffix=save_suffix(frozen.get("batch_item")),
        )
        if frozen.get("batch_item") is not None:
            store.write_fixed_json(task_key, f"saved_pair_v{approved_draft['draft_version']}.json",
                {key: str(value) if isinstance(value, Path) else value for key, value in saved_pair.items()})
        store.transition(task_key, "saved")
    except SlimRuntimeError as exc:
        current = store.get_task(task_key)
        if current["state"] == "package_approved":
            store.transition(task_key, "blocked")
        raise SlimRuntimeError(
            exc.error_code,
            exc.component,
            detail=exc.detail,
            workflow_stage="等待你确认并保存",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        ) from exc
    return {
        "status": "completed",
        "status_label": "已完成",
        "workflow_stage": "已完成",
        "message": "纯口播稿和配套文案已同时保存；本次任务保持未发布。",
        "next_action": "P5 到此停止，等待独立 Review。",
        "run_exists": True,
        "run_created_now": False,
        "artifacts_exist": True,
        "artifacts_preserved": True,
        "publish_status": "not_requested",
    }


def respond_package(
    *,
    registry_path: str | Path,
    runs_root: str | Path,
    task_record: str,
    decision: str,
    feedback: str | None = None,
    selected_cover_title: str | None = None,
    selected_publish_title: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    store = RunStore(runs_root)
    task_key = _task_key_from_record(store, task_record)
    state = store.get_task(task_key)
    decision = _normalize_decision(decision)
    if (
        state["state"] == "blocked"
        and state.get("blocked_resume_state") == "package_approved"
        and decision == "确认并保存"
    ):
        if feedback or selected_cover_title or selected_publish_title:
            raise SlimRuntimeError(
                "SLIM_PACKAGE_RESPONSE_INVALID",
                "content_koubo_slim",
                detail="save retry must reuse the already confirmed package selection",
                workflow_stage="等待你确认并保存",
                run_exists=True,
                artifacts_exist=True,
                artifacts_preserved=True,
            )
        store.transition(task_key, "package_approved")
        return _save_approved_package(
            registry_path=registry_path,
            runs_root=runs_root,
            task_key=task_key,
        ), None
    if state["state"] != "package_pending":
        raise _current_state_error(
            store=store,
            task_key=task_key,
            state=state,
            component="content_koubo_slim",
            detail=f"respond-package is not allowed from state={state['state']!r}",
        )
    if decision not in PACKAGE_CHOICES:
        raise SlimRuntimeError(
            "SLIM_PACKAGE_RESPONSE_INVALID",
            "content_koubo_slim",
            detail=f"state={state['state']!r}, decision={decision!r}",
            workflow_stage=SlimStateMachine.user_label(state["state"]),
            run_exists=True,
            artifacts_exist=store.artifacts_exist(task_key),
            artifacts_preserved=store.artifacts_exist(task_key),
        )
    if decision == "需要修改":
        if selected_cover_title or selected_publish_title:
            raise SlimRuntimeError(
                "SLIM_PACKAGE_RESPONSE_INVALID",
                "content_koubo_slim",
                detail="revision must not select final titles",
                workflow_stage="等待你确认并保存",
                run_exists=True,
                artifacts_exist=True,
                artifacts_preserved=True,
            )
        package_input, _ = prepare_package_stage(
            runs_root=runs_root,
            task_record=task_record,
            revision_feedback=feedback,
        )
        return (
            {
                "status": "working",
                "status_label": "正在修改配套文案",
                "workflow_stage": "等待你确认并保存",
                "message": "修改意见已绑定当前配套，旧版本保持不变。",
                "next_action": "按这条意见生成下一版完整配套。",
                "run_exists": True,
                "run_created_now": False,
                "artifacts_exist": True,
                "artifacts_preserved": True,
            },
            package_input,
        )
    if feedback:
        raise SlimRuntimeError(
            "SLIM_PACKAGE_RESPONSE_INVALID",
            "content_koubo_slim",
            detail="confirmation must not include revision feedback",
            workflow_stage="等待你确认并保存",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    version, package, _ = store.latest_version(task_key, "package")
    content = validate_publish_pack_result(package.get("content"))
    selected_cover = selected_cover_title or content["recommended_cover_title"]
    selected_publish = selected_publish_title or content["recommended_publish_title"]
    if selected_cover not in content["cover_titles"] or selected_publish not in content[
        "publish_titles"
    ]:
        raise SlimRuntimeError(
            "SLIM_PACKAGE_RESPONSE_INVALID",
            "content_koubo_slim",
            detail="selected title is not one of the current candidates",
            workflow_stage="等待你确认并保存",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    _, draft_approval = _approved_draft_input(store, task_key)
    if (package.get("based_on_draft_version") != draft_approval["draft_version"]
            or package.get("based_on_draft_sha256") != draft_approval["draft_sha256"]):
        raise SlimRuntimeError("SLIM_PACKAGE_RESPONSE_INVALID", "content_koubo_slim",
            detail="package belongs to an earlier draft; generate new package before confirming",
            run_exists=True, artifacts_exist=True, artifacts_preserved=True)
    approval = {
        "approval_version": "content-koubo-slim-approved-package-v1",
        "package_version": version,
        "package_sha256": canonical_json_hash(package),
        "draft_version": draft_approval["draft_version"],
        "draft_sha256": draft_approval["draft_sha256"],
        "selected_cover_title": selected_cover,
        "selected_publish_title": selected_publish,
        "decision": "确认并保存",
        "publish_status": "not_requested",
    }
    store.write_fixed_json(task_key, _approval_filename(store, task_key, "package", version), approval)
    store.transition(task_key, "package_approved")
    return _save_approved_package(
        registry_path=registry_path,
        runs_root=runs_root,
        task_key=task_key,
    ), None


def _start(args: argparse.Namespace) -> dict[str, Any]:
    selections = None
    guidance = None
    if args.method_selection:
        try:
            selections = json.loads(Path(args.method_selection).read_text(encoding="utf-8"))
            if isinstance(selections, dict):
                if set(selections) - {"materials", "planning_guidance"} or "materials" not in selections:
                    raise ValueError("selection object requires materials and optional planning_guidance")
                guidance = selections.get("planning_guidance", [])
                selections = selections["materials"]
        except (OSError, UnicodeError, ValueError) as exc:
            raise SlimRuntimeError("SLIM_ANALYZER_INPUT_INVALID", "content_koubo_slim", detail=str(exc)) from exc
    request = dict(
        registry_path=args.registry,
        runs_root=args.runs_root,
        client_id=args.client_id,
        speaker_mode=args.speaker_mode,
        topic_original=args.topic_original,
        reference_paths=args.reference,
        user_thoughts=args.user_thoughts,
        must_keep=args.must_keep,
        must_avoid=args.must_avoid,
        binding_id=args.binding_id,
        profile=args.profile,
        method_selections=selections,
        planning_guidance=guidance,
        audience_scope=args.audience_scope,
        allow_experimental=args.allow_experimental,
    )
    return start_request(prepare_direction_stage, request, output_count=args.output_count, plan_path=args.batch_plan)


def _discover_methods(args: argparse.Namespace) -> dict[str, Any]:
    registry = load_effective_registry(args.registry)
    binding = select_client_id(registry, args.client_id, requested_binding_id=args.binding_id)
    location = resolve_client(registry, binding)
    manifest = load_manifest(location.manifest_path, expected_client_id=location.client_id)
    if location.knowledge_base_id is not None and location.knowledge_base_id != manifest.knowledge_base_id:
        raise SlimRuntimeError("SLIM_MANIFEST_INVALID", "content_koubo_slim", detail="binding differs from Manifest")
    root = resolve_asset_root(location.vault_root, manifest, "method")
    if args.read_path:
        if not args.expected_sha256 or not re.fullmatch(r"[0-9a-f]{64}", args.expected_sha256):
            raise SlimRuntimeError("SLIM_ANALYZER_INPUT_INVALID", "content_koubo_slim", detail="read requires discovered snapshot hash")
        asset = read_method_asset(root, args.read_path, expected_sha256=args.expected_sha256, include_guidance=True)
        if not method_is_usable(asset, args.audience_scope, args.allow_experimental):
            raise SlimRuntimeError("SLIM_METHOD_ASSET_INVALID", "content_koubo_slim", detail="material is excluded for this audience or usage scope")
        return {"wrote": False, "asset_id": asset.asset_id, "method_kind": method_kind(asset),
                "page_sha256": asset.page_sha256, "source_metadata": method_source_metadata(asset),
                "content": complete_method_text(asset)}
    return discover_method_assets(root, offset=args.offset, limit=args.limit,
                                  audience_scope=args.audience_scope, allow_experimental=args.allow_experimental)


def _load_planning_guidance(root, selections, audience_scope, allow_experimental):
    if not isinstance(selections, list) or len(selections) > 3:
        raise SlimRuntimeError("SLIM_ANALYZER_INPUT_INVALID", "content_koubo_slim", detail="at most three planning guides")
    result, ids = [], set()
    for item in selections:
        if not isinstance(item, dict) or set(item) != {"relative_path", "page_sha256", "reason"} or not isinstance(item["reason"], str) or not item["reason"].strip() or not isinstance(item["page_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["page_sha256"]):
            raise SlimRuntimeError("SLIM_ANALYZER_INPUT_INVALID", "content_koubo_slim", detail="invalid planning guide selection")
        asset = read_method_asset(root, item["relative_path"], expected_sha256=item["page_sha256"], include_guidance=True)
        if method_kind(asset) not in {"selection_guide", "index", "methodology"} or asset.asset_id in ids or not method_is_usable(asset, audience_scope, allow_experimental):
            raise SlimRuntimeError("SLIM_METHOD_ASSET_INVALID", "content_koubo_slim", detail="not permitted planning guidance")
        ids.add(asset.asset_id)
        result.append({**item, "asset_id": asset.asset_id, "content": complete_method_text(asset)})
    return result


def _verify_planning_guidance(frozen, root):
    for item in frozen.get("planning_guidance", []):
        read_method_asset(root, item["relative_path"], expected_sha256=item["page_sha256"], include_guidance=True)


def _configure(args: argparse.Namespace) -> dict[str, Any]:
    if args.confirmation:
        return apply_obsidian_configuration(
            args.vault,
            confirmation=args.confirmation,
            registry_path=args.registry,
            client_id=args.client_id,
        )
    plan = plan_obsidian_configuration(
        args.vault,
        registry_path=args.registry,
        client_id=args.client_id,
    )
    return {
        "status": "confirmation_required",
        "message": "配置预览已生成；当前零写入。确认后才创建清单并登记知识库。",
        "preview": plan["preview"],
        "confirmation": plan["confirmation"],
    }


def _record_direction(args: argparse.Namespace) -> dict[str, Any]:
    store = RunStore(args.runs_root)
    task_key = _task_key_from_record(store, args.task_record)
    try:
        result = json.loads(Path(args.analyzer_result).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SlimRuntimeError(
            "SLIM_ANALYZER_OUTPUT_INVALID",
            "content_koubo_slim",
            detail=str(exc),
            workflow_stage="正在拆解并匹配客户内容方向",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        ) from exc
    gate_a, _ = record_direction_result(store=store, task_key=task_key, analyzer_result=result)
    return {
        "status": "waiting",
        "status_label": "等待你确认方向",
        "workflow_stage": "等待你确认方向",
        "message": "完整写作方向已生成，请一次判断整版方向。",
        "next_action": "请选择认可整版方向、需要修改或不采用。",
        "run_exists": True,
        "run_created_now": False,
        "artifacts_exist": True,
        "artifacts_preserved": True,
        "gate_a": gate_a,
    }


def _respond_direction(args: argparse.Namespace) -> dict[str, Any]:
    registry = load_effective_registry(args.registry)
    store = RunStore(args.runs_root)
    task_key = _task_key_from_record(store, args.task_record)
    frozen = store.read_task_input(task_key)
    location = resolve_client(registry, frozen.get("binding_id") or frozen["client_id"])
    _verify_frozen_client_location(
        frozen,
        vault_root=location.vault_root,
        manifest_path=location.manifest_path,
        binding_id=location.binding_id,
        registry_sha256=location.registry_sha256,
    )
    manifest = load_manifest(
        location.manifest_path, expected_client_id=frozen["client_id"]
    )
    _verify_frozen_manifest(frozen, manifest, workflow_stage="等待你确认方向")
    method_root = resolve_asset_root(location.vault_root, manifest, "method")
    response, _ = respond_direction(
        store=store,
        task_key=task_key,
        method_root=method_root,
        decision=args.decision,
        feedback=args.feedback,
        identity_changes=(
            {"task_identity": "changed"} if args.task_identity_changed else {}
        ),
    )
    return response


def _prepare_context(args: argparse.Namespace) -> dict[str, Any]:
    context_input, _ = prepare_context_stage(
        registry_path=args.registry,
        runs_root=args.runs_root,
        task_record=args.task_record,
    )
    return {
        "status": "working",
        "status_label": "正在准备客户内容资料",
        "workflow_stage": "正在准备客户内容资料",
        "message": "受控 03/04/05 已准备，只交给 content-koubo-context-retriever 装配。",
        "next_action": "生成唯一 Content Context Pack；不要调用 Writer。",
        "run_exists": True,
        "run_created_now": False,
        "artifacts_exist": True,
        "artifacts_preserved": True,
        "context_input": context_input,
    }


def _record_context(args: argparse.Namespace) -> dict[str, Any]:
    try:
        result = json.loads(Path(args.context_result).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SlimRuntimeError(
            "SLIM_CONTEXT_OUTPUT_INVALID",
            "content_koubo_slim",
            detail=str(exc),
            workflow_stage="正在准备客户内容资料",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        ) from exc
    response, _ = record_context_result(
        registry_path=args.registry,
        runs_root=args.runs_root,
        task_record=args.task_record,
        context_result=result,
    )
    return response


def _prepare_draft(args: argparse.Namespace) -> dict[str, Any]:
    writer_input, _ = prepare_draft_stage(
        runs_root=args.runs_root,
        task_record=args.task_record,
        revision_feedback=args.feedback,
    )
    return {
        "status": "working",
        "status_label": "正在生成正文",
        "workflow_stage": "正在生成正文",
        "message": "唯一 Context Pack 和冻结主模式已准备，只交给 content-koubo-writer 写正文。",
        "next_action": "生成完整口播正文；不要生成标题、标签或配套文案。",
        "run_exists": True,
        "run_created_now": False,
        "artifacts_exist": True,
        "artifacts_preserved": True,
        "writer_input": writer_input,
    }


def _record_draft(args: argparse.Namespace) -> dict[str, Any]:
    try:
        result = json.loads(Path(args.writer_result).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SlimRuntimeError(
            "SLIM_WRITER_OUTPUT_INVALID",
            "content_koubo_slim",
            detail=str(exc),
            workflow_stage="正在生成正文",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        ) from exc
    response, _ = record_draft_result(
        runs_root=args.runs_root,
        task_record=args.task_record,
        base_draft_version=args.base_draft_version,
        writer_result=result,
        revision_feedback=args.feedback,
    )
    return response


def _respond_draft(args: argparse.Namespace) -> dict[str, Any]:
    response, writer_input = respond_draft(
        runs_root=args.runs_root,
        task_record=args.task_record,
        decision=args.decision,
        feedback=args.feedback,
    )
    if writer_input is not None:
        response["writer_input"] = writer_input
    return response


def _prepare_package(args: argparse.Namespace) -> dict[str, Any]:
    package_input, _ = prepare_package_stage(
        runs_root=args.runs_root,
        task_record=args.task_record,
        revision_feedback=args.feedback,
    )
    return {
        "status": "working",
        "status_label": "正在生成配套文案",
        "workflow_stage": "正在生成配套文案",
        "message": "已确认正文已准备，只交给 content-koubo-publish-pack 生成完整配套。",
        "next_action": "生成标题、发布正文和标签；不要修改或重复输出正文。",
        "run_exists": True,
        "run_created_now": False,
        "artifacts_exist": True,
        "artifacts_preserved": True,
        "package_input": package_input,
    }


def _record_package(args: argparse.Namespace) -> dict[str, Any]:
    try:
        result = json.loads(Path(args.package_result).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SlimRuntimeError(
            "SLIM_PACKAGE_OUTPUT_INVALID",
            "content_koubo_slim",
            detail=str(exc),
            workflow_stage="正在生成配套文案",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        ) from exc
    response, _ = record_package_result(
        runs_root=args.runs_root,
        task_record=args.task_record,
        base_package_version=args.base_package_version,
        package_result=result,
        revision_feedback=args.feedback,
        based_on_draft_version=args.based_on_draft_version,
    )
    return response


def _respond_package(args: argparse.Namespace) -> dict[str, Any]:
    response, package_input = respond_package(
        registry_path=args.registry,
        runs_root=args.runs_root,
        task_record=args.task_record,
        decision=args.decision,
        feedback=args.feedback,
        selected_cover_title=args.selected_cover_title,
        selected_publish_title=args.selected_publish_title,
    )
    if package_input is not None:
        response["package_input"] = package_input
    return response


def _status(args: argparse.Namespace) -> dict[str, Any]:
    store = RunStore(args.runs_root)
    task_key = _task_key_from_record(store, args.task_record)
    state = store.get_task(task_key)
    label = SlimStateMachine.user_label(state["state"])
    terminal = state["state"] in {"saved", "abandoned"}
    artifacts_exist = store.artifacts_exist(task_key)
    return {
        "status": "completed" if terminal else "waiting",
        "status_label": label,
        "workflow_stage": label,
        "message": f"当前任务状态：{label}。",
        "next_action": CURRENT_STATE_ACTIONS[state["state"]],
        "run_exists": True,
        "run_created_now": False,
        "artifacts_exist": artifacts_exist,
        "artifacts_preserved": artifacts_exist,
    }


def _add_registry_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--registry", default=None)


def _add_runs_root_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--runs-root", default=str(default_runs_root()))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Content 口播 Slim runtime entry")
    subparsers = parser.add_subparsers(dest="operation", required=True)

    configure = subparsers.add_parser("configure", help="preview or confirm one Obsidian binding")
    configure.add_argument("--vault", required=True, type=Path)
    configure.add_argument("--registry")
    configure.add_argument("--client-id")
    configure.add_argument("--confirmation")
    configure.set_defaults(handler=_configure)

    discovery = subparsers.add_parser("discover-methods", help="internal: bounded library metadata for semantic material selection")
    _add_registry_argument(discovery)
    discovery.add_argument("--client-id")
    discovery.add_argument("--binding-id")
    discovery.add_argument("--audience-scope", choices=("consumer", "internal_sales_training"))
    discovery.add_argument("--allow-experimental", action="store_true", help="only for explicitly authorized experiment tasks")
    discovery.add_argument("--offset", type=int, default=0)
    discovery.add_argument("--limit", type=int, default=40)
    discovery.add_argument("--read-path")
    discovery.add_argument("--expected-sha256")
    discovery.set_defaults(handler=_discover_methods)

    start = subparsers.add_parser("start", help="prepare one Run through Analyzer input")
    _add_registry_argument(start)
    _add_runs_root_argument(start)
    start.add_argument("--client-id")
    start.add_argument("--binding-id")
    start.add_argument("--profile", help="active Profile id, display name, or unique alias")
    start.add_argument("--speaker-mode", choices=("personal_ip", "company_brand", "neutral"))
    start.add_argument("--topic-original", required=True)
    start.add_argument("--reference", action="append", default=[])
    start.add_argument("--method-selection", help="internal JSON list selected from discover-methods")
    start.add_argument("--audience-scope", choices=("consumer", "internal_sales_training"))
    start.add_argument("--allow-experimental", action="store_true", help="only for explicitly authorized experiment tasks")
    start.add_argument("--user-thoughts")
    start.add_argument("--must-keep", action="append", default=[])
    start.add_argument("--must-avoid", action="append", default=[])
    start.add_argument("--output-count", type=int, default=1)
    start.add_argument("--batch-plan", help="internal JSON plan for independent deliverables")
    start.set_defaults(handler=_start)

    batch = subparsers.add_parser("batch-status", help="internal: verify batch progress and saved files")
    _add_runs_root_argument(batch)
    batch.add_argument("--batch-id", required=True)
    batch.set_defaults(handler=lambda args: batch_status(RunStore(args.runs_root), args.batch_id))

    record = subparsers.add_parser("record-direction", help="internal: validate Analyzer result")
    _add_runs_root_argument(record)
    record.add_argument("--task-record", required=True)
    record.add_argument("--analyzer-result", required=True)
    record.set_defaults(handler=_record_direction)

    respond = subparsers.add_parser("respond-direction", help="record the human Gate A choice")
    _add_registry_argument(respond)
    _add_runs_root_argument(respond)
    respond.add_argument("--task-record", required=True)
    respond.add_argument(
        "--decision", required=True, type=_normalize_decision, choices=GATE_A_CHOICES
    )
    respond.add_argument("--feedback")
    respond.add_argument(
        "--task-identity-changed", action="store_true", help=argparse.SUPPRESS
    )
    respond.set_defaults(handler=_respond_direction)

    prepare_context = subparsers.add_parser(
        "prepare-context", help="internal: prepare the P3 semantic handoff"
    )
    _add_registry_argument(prepare_context)
    _add_runs_root_argument(prepare_context)
    prepare_context.add_argument("--task-record", required=True)
    prepare_context.set_defaults(handler=_prepare_context)

    record_context = subparsers.add_parser(
        "record-context", help="internal: validate and save the single Context Pack"
    )
    _add_registry_argument(record_context)
    _add_runs_root_argument(record_context)
    record_context.add_argument("--task-record", required=True)
    record_context.add_argument("--context-result", required=True)
    record_context.set_defaults(handler=_record_context)

    prepare_draft = subparsers.add_parser(
        "prepare-draft", help="internal: prepare the single-mode P4 Writer handoff"
    )
    _add_runs_root_argument(prepare_draft)
    prepare_draft.add_argument("--task-record", required=True)
    prepare_draft.add_argument("--feedback")
    prepare_draft.set_defaults(handler=_prepare_draft)

    record_draft = subparsers.add_parser(
        "record-draft", help="internal: validate and save one draft version"
    )
    _add_runs_root_argument(record_draft)
    record_draft.add_argument("--task-record", required=True)
    record_draft.add_argument("--base-draft-version", required=True, type=int)
    record_draft.add_argument("--writer-result", required=True)
    record_draft.add_argument("--feedback")
    record_draft.set_defaults(handler=_record_draft)

    respond_draft_parser = subparsers.add_parser(
        "respond-draft", help="record the human body confirmation or revision choice"
    )
    _add_runs_root_argument(respond_draft_parser)
    respond_draft_parser.add_argument("--task-record", required=True)
    respond_draft_parser.add_argument(
        "--decision", required=True, type=_normalize_decision, choices=DRAFT_CHOICES
    )
    respond_draft_parser.add_argument("--feedback")
    respond_draft_parser.set_defaults(handler=_respond_draft)

    prepare_package = subparsers.add_parser(
        "prepare-package", help="internal: prepare the confirmed-body P5 handoff"
    )
    _add_runs_root_argument(prepare_package)
    prepare_package.add_argument("--task-record", required=True)
    prepare_package.add_argument("--feedback")
    prepare_package.set_defaults(handler=_prepare_package)

    record_package = subparsers.add_parser(
        "record-package", help="internal: validate and save one publish-pack version"
    )
    _add_runs_root_argument(record_package)
    record_package.add_argument("--task-record", required=True)
    record_package.add_argument("--base-package-version", required=True, type=int)
    record_package.add_argument("--package-result", required=True)
    record_package.add_argument("--feedback")
    record_package.add_argument("--based-on-draft-version", type=int, help="body version from prepare-package; required after body revisions")
    record_package.set_defaults(handler=_record_package)

    respond_package_parser = subparsers.add_parser(
        "respond-package", help="record the human package choice and save both files"
    )
    _add_registry_argument(respond_package_parser)
    _add_runs_root_argument(respond_package_parser)
    respond_package_parser.add_argument("--task-record", required=True)
    respond_package_parser.add_argument(
        "--decision", required=True, type=_normalize_decision, choices=PACKAGE_CHOICES
    )
    respond_package_parser.add_argument("--feedback")
    respond_package_parser.add_argument("--selected-cover-title")
    respond_package_parser.add_argument("--selected-publish-title")
    respond_package_parser.set_defaults(handler=_respond_package)

    status = subparsers.add_parser("status", help="read the current state")
    _add_runs_root_argument(status)
    status.add_argument("--task-record", required=True)
    status.set_defaults(handler=_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    host_parser = argparse.ArgumentParser(add_help=False)
    host_parser.add_argument("--host", choices=("codex", "workbuddy"))
    host_parser.add_argument("--host-root")
    host, remaining = host_parser.parse_known_args(argv)
    if host.host and host.host_root:
        host_parser.error("choose --host or --host-root, not both")
    if host.host_root:
        root = Path(host.host_root).expanduser()
        if not root.is_absolute():
            host_parser.error("--host-root must be absolute")
        os.environ["CONTENT_KOUBO_HOME"] = str(root)
    elif host.host:
        os.environ["CONTENT_KOUBO_HOME"] = str(Path.home() / (".workbuddy" if host.host == "workbuddy" else ".codex"))
    args = build_parser().parse_args(remaining)
    try:
        response = args.handler(args)
        exit_code = 0
    except SlimRuntimeError as exc:
        response = exc.user_response()
        exit_code = 2
    print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
