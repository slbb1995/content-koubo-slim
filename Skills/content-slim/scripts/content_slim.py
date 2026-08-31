#!/usr/bin/env python3
"""Content V2 Slim entry through P5 package confirmation and safe save."""

from __future__ import annotations

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
    default_registry_path,
    default_runs_root,
    load_registry,
    resolve_client,
    select_client_id,
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
from runtime.vault_reader import read_method_asset, read_primary_profile
from runtime.vault_search import search_knowledge_assets, search_method_assets


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
    "draft_approved": "生成标题、发布正文和标签；不要修改已确认正文。",
    "package_pending": "请选择确认并保存，或给出具体修改意见。",
    "package_approved": "保存已确认正文和配套；不要重新生成内容。",
    "blocked": "先处理当前阻断问题，再复用同一个 Run 继续。",
    "saved": "本次任务无需继续。",
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
    workflow_stage: str = "正在准备客户内容资料",
) -> None:
    """Keep every stage of one Run bound to the client location used at start."""

    if (
        frozen.get("vault_root_resolved") != str(vault_root)
        or frozen.get("manifest_path_resolved") != str(manifest_path)
    ):
        raise SlimRuntimeError(
            "SLIM_TASK_IDENTITY_CHANGED",
            "content_slim",
            detail="current registry no longer matches the Run's frozen client location",
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
            "content_slim",
            detail="analyzer input version is invalid",
            workflow_stage="正在拆解并匹配客户内容方向",
            run_exists=True,
        )
    return validate_analyzer_input(
        store.read_fixed_json(task_key, f"analyzer_input_v{version}.json")
    )


def prepare_direction_stage(
    *,
    registry_path: str | Path,
    runs_root: str | Path,
    client_id: str | None,
    speaker_mode: str | None,
    topic_original: str,
    reference_paths: list[str | Path],
    user_thoughts: str | None,
    must_keep: list[str],
    must_avoid: list[str],
) -> tuple[dict[str, Any], str]:
    if not isinstance(topic_original, str) or not topic_original.strip():
        raise SlimRuntimeError(
            "SLIM_ANALYZER_INPUT_INVALID",
            "content_slim",
            detail="topic_original is missing",
            workflow_stage="正在准备参考",
        )
    prepared = preflight_references(reference_paths)
    registry = load_registry(registry_path)
    resolved_client_id = select_client_id(registry, client_id)
    location = resolve_client(registry, resolved_client_id)
    manifest = load_manifest(
        location.manifest_path, expected_client_id=resolved_client_id
    )
    resolved_mode = resolve_speaker_mode(speaker_mode, manifest)
    method_root = resolve_asset_root(location.vault_root, manifest, "method")
    reference_index = build_reference_index(prepared)
    topic_normalized = _normalize_topic(topic_original)
    business_identity = {
        "client_id": resolved_client_id,
        "speaker_mode": resolved_mode,
        "topic_original": topic_original,
        "reference_set_sha256": reference_index["reference_set_sha256"],
    }
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
            "content_slim",
            detail="prepared references changed after task identity was generated",
            workflow_stage="正在准备参考",
            run_exists=True,
            artifacts_exist=store.artifacts_exist(task_key),
            artifacts_preserved=store.artifacts_exist(task_key),
        )
    frozen_input = {
        "contract_version": "content-v2-slim-task-input-v1",
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
    store.freeze_task_input(task_key, frozen_input)
    candidates = search_method_assets(
        method_root,
        query=_method_search_query(
            topic_original=topic_original,
            topic_normalized=topic_normalized,
            user_thoughts=user_thoughts,
            must_keep=must_keep,
            prepared_references=prepared,
        ),
    )
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
        }
    )
    store.write_fixed_json(task_key, "analyzer_input_v1.json", analyzer_input)
    response = {
        "status": "working",
        "status_label": "正在拆解并匹配客户内容方向",
        "workflow_stage": "正在拆解并匹配客户内容方向",
        "message": "参考件和当前客户 04 候选已准备；下一步只生成完整方向，不写正文。",
        "next_action": "由 content-analyzer 生成完整方向后展示 Gate A。",
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
            "content_slim",
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
            "content_slim",
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
            "content_slim",
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
            "content_slim",
            detail="next direction lacks matching human revision feedback",
            workflow_stage="等待你确认方向",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    validated = validate_analyzer_result(analyzer_result, analyzer_input)
    gate_a = build_gate_a(validated, next_version)
    direction = {
        "contract_version": "content-v2-slim-direction-v1",
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
            "content_slim",
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
            "content_slim",
            detail="revision feedback is empty",
            workflow_stage="等待你确认方向",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    if identity_changes:
        raise SlimRuntimeError(
            "SLIM_TASK_IDENTITY_CHANGED",
            "content_slim",
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
            "content_slim",
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
            component="content_slim",
            detail=f"respond-direction is not allowed from state={state['state']!r}",
        )
    if decision not in GATE_A_CHOICES:
        raise SlimRuntimeError(
            "SLIM_DIRECTION_RESPONSE_INVALID",
            "content_slim",
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
            "content_slim",
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
            "content_slim",
            detail="latest direction is not bound to the displayed Gate A version",
            workflow_stage="等待你确认方向",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    result = direction["analyzer_result"]
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
            "content_slim",
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
        or approved.get("approval_version") != "content-v2-slim-approved-direction-v1"
        or approved.get("speaker_mode") != frozen.get("speaker_mode")
        or approved.get("approved_gate_a", {}).get("direction_version")
        != approved.get("direction_version")
        or canonical_json_hash(approved.get("approved_gate_a"))
        != approved.get("gate_a_sha256")
    ):
        raise SlimRuntimeError(
            "SLIM_CONTEXT_INPUT_INVALID",
            "content_slim",
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
            "content_slim",
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

    registry = load_registry(registry_path)
    location = resolve_client(registry, frozen["client_id"])
    _verify_frozen_client_location(
        frozen,
        vault_root=location.vault_root,
        manifest_path=location.manifest_path,
    )
    manifest = load_manifest(
        location.manifest_path, expected_client_id=frozen["client_id"]
    )
    resolved_mode = resolve_speaker_mode(frozen["speaker_mode"], manifest)
    method_root = resolve_asset_root(location.vault_root, manifest, "method")
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
                "content_slim",
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
                "source_excerpt": asset.body[:1800].rstrip(),
                "approved_usage": selected["usage"],
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
            "content_slim",
            detail="context result is not allowed in current state",
            workflow_stage=SlimStateMachine.user_label(state["state"]),
            run_exists=True,
            artifacts_exist=store.artifacts_exist(task_key),
            artifacts_preserved=store.artifacts_exist(task_key),
        )
    validated = validate_content_context(context_result, context_input)
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
    if state["state"] not in {"context_ready", "draft_pending"}:
        raise SlimRuntimeError(
            "SLIM_STATE_TRANSITION_INVALID",
            "content_slim",
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
            "content_slim",
            detail="draft_v1 cannot contain revision feedback",
            workflow_stage="正在生成正文",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    if state["state"] == "draft_pending" and not feedback:
        raise SlimRuntimeError(
            "SLIM_DRAFT_RESPONSE_INVALID",
            "content_slim",
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
    if state["state"] == "draft_pending":
        base_version, current, _ = store.latest_version(task_key, "draft")
        if current.get("draft_version") != base_version:
            raise SlimRuntimeError(
                "SLIM_DRAFT_RESPONSE_INVALID",
                "content_slim",
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
            "content_slim",
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
        "contract_version": "content-v2-slim-draft-v1",
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
    if state["state"] != "draft_pending":
        raise _current_state_error(
            store=store,
            task_key=task_key,
            state=state,
            component="content_slim",
            detail=f"respond-draft is not allowed from state={state['state']!r}",
        )
    if decision not in DRAFT_CHOICES:
        raise SlimRuntimeError(
            "SLIM_DRAFT_RESPONSE_INVALID",
            "content_slim",
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
            "content_slim",
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
            "content_slim",
            detail=str(exc),
            workflow_stage="等待你确认正文",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        ) from exc
    if draft.get("draft_version") != version or markdown != draft.get("body", "") + "\n":
        raise SlimRuntimeError(
            "SLIM_DRAFT_RESPONSE_INVALID",
            "content_slim",
            detail="latest JSON and Markdown draft versions do not match",
            workflow_stage="等待你确认正文",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    approval = {
        "approval_version": "content-v2-slim-approved-draft-v1",
        "draft_version": version,
        "draft_sha256": canonical_json_hash(draft),
        "decision": "确认正文",
    }
    store.write_fixed_json(task_key, "approved_draft.json", approval)
    store.transition(task_key, "draft_approved")
    return (
        {
            "status": "waiting",
            "status_label": "正文已确认",
            "workflow_stage": "正文已确认",
            "message": "当前正文已确认，可以基于这份正文生成配套文案。",
            "next_action": "生成标题、发布正文和标签；不要修改已确认正文。",
            "run_exists": True,
            "run_created_now": False,
            "artifacts_exist": True,
            "artifacts_preserved": True,
        },
        None,
    )


def _approved_draft_input(store: RunStore, task_key: str) -> tuple[dict[str, Any], dict[str, Any]]:
    approval = store.read_fixed_json(task_key, "approved_draft.json")
    expected_fields = {"approval_version", "draft_version", "draft_sha256", "decision"}
    version, draft, json_path = store.latest_version(task_key, "draft")
    try:
        markdown = json_path.with_suffix(".md").read_text(encoding="utf-8")
    except OSError as exc:
        raise SlimRuntimeError(
            "SLIM_PACKAGE_OUTPUT_INVALID",
            "content_slim",
            detail=str(exc),
            workflow_stage="正在生成配套文案",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        ) from exc
    if (
        set(approval) != expected_fields
        or approval.get("approval_version") != "content-v2-slim-approved-draft-v1"
        or approval.get("decision") != "确认正文"
        or approval.get("draft_version") != version
        or approval.get("draft_sha256") != canonical_json_hash(draft)
        or draft.get("draft_version") != version
        or markdown != draft.get("body", "") + "\n"
    ):
        raise SlimRuntimeError(
            "SLIM_PACKAGE_OUTPUT_INVALID",
            "content_slim",
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
            "content_slim",
            detail="package preparation requires draft_approved or package_pending",
            workflow_stage=SlimStateMachine.user_label(state["state"]),
            run_exists=True,
            artifacts_exist=store.artifacts_exist(task_key),
            artifacts_preserved=store.artifacts_exist(task_key),
        )
    feedback = revision_feedback.strip() if isinstance(revision_feedback, str) else None
    if state["state"] == "draft_approved" and feedback:
        raise SlimRuntimeError(
            "SLIM_PACKAGE_RESPONSE_INVALID",
            "content_slim",
            detail="package_v1 cannot contain revision feedback",
            workflow_stage="正在生成配套文案",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    if state["state"] == "package_pending" and not feedback:
        raise SlimRuntimeError(
            "SLIM_PACKAGE_RESPONSE_INVALID",
            "content_slim",
            detail="package revision feedback is empty",
            workflow_stage="等待你确认并保存",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )

    approved_draft, approval = _approved_draft_input(store, task_key)
    base_version = 0
    previous_package: dict[str, Any] | None = None
    if state["state"] == "package_pending":
        base_version, current, _ = store.latest_version(task_key, "package")
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
            or current.get("contract_version") != "content-v2-slim-package-v1"
            or current.get("package_version") != base_version
            or current.get("based_on_draft_version") != approved_draft["draft_version"]
            or current.get("based_on_draft_sha256") != approval["draft_sha256"]
        ):
            raise SlimRuntimeError(
                "SLIM_PACKAGE_RESPONSE_INVALID",
                "content_slim",
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
) -> tuple[dict[str, Any], Path]:
    package_input, task_key = prepare_package_stage(
        runs_root=runs_root,
        task_record=task_record,
        revision_feedback=revision_feedback,
    )
    if package_input["base_package_version"] != base_package_version:
        raise SlimRuntimeError(
            "SLIM_PACKAGE_RESPONSE_INVALID",
            "content_slim",
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
        "contract_version": "content-v2-slim-package-v1",
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
            "content_slim",
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
        f"发布正文：\n{content['publish_copy']}\n\n"
        f"标签：\n{' '.join(content['tags'])}"
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
        approval = store.read_fixed_json(task_key, "approved_package.json")
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
            or approval.get("approval_version") != "content-v2-slim-approved-package-v1"
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
                "content_slim",
                detail="approved package no longer matches the latest confirmed package",
                workflow_stage="等待你确认并保存",
                run_exists=True,
                artifacts_exist=True,
                artifacts_preserved=True,
            )

        registry = load_registry(registry_path)
        location = resolve_client(registry, frozen["client_id"])
        _verify_frozen_client_location(
            frozen,
            vault_root=location.vault_root,
            manifest_path=location.manifest_path,
            workflow_stage="等待你确认并保存",
        )
        manifest = load_manifest(
            location.manifest_path, expected_client_id=frozen["client_id"]
        )
        output_root = resolve_asset_root(location.vault_root, manifest, "output")
        save_markdown_pair(
            output_root=output_root,
            output_template=manifest.output_template,
            client_id=frozen["client_id"],
            selected_publish_title=approval["selected_publish_title"],
            oral_body=approved_draft["body"],
            package_markdown=_package_markdown(approval, content),
        )
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
                "content_slim",
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
            component="content_slim",
            detail=f"respond-package is not allowed from state={state['state']!r}",
        )
    if decision not in PACKAGE_CHOICES:
        raise SlimRuntimeError(
            "SLIM_PACKAGE_RESPONSE_INVALID",
            "content_slim",
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
                "content_slim",
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
            "content_slim",
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
            "content_slim",
            detail="selected title is not one of the current candidates",
            workflow_stage="等待你确认并保存",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    _, draft_approval = _approved_draft_input(store, task_key)
    approval = {
        "approval_version": "content-v2-slim-approved-package-v1",
        "package_version": version,
        "package_sha256": canonical_json_hash(package),
        "draft_version": draft_approval["draft_version"],
        "draft_sha256": draft_approval["draft_sha256"],
        "selected_cover_title": selected_cover,
        "selected_publish_title": selected_publish,
        "decision": "确认并保存",
        "publish_status": "not_requested",
    }
    store.write_fixed_json(task_key, "approved_package.json", approval)
    store.transition(task_key, "package_approved")
    return _save_approved_package(
        registry_path=registry_path,
        runs_root=runs_root,
        task_key=task_key,
    ), None


def _start(args: argparse.Namespace) -> dict[str, Any]:
    response, _ = prepare_direction_stage(
        registry_path=args.registry,
        runs_root=args.runs_root,
        client_id=args.client_id,
        speaker_mode=args.speaker_mode,
        topic_original=args.topic_original,
        reference_paths=args.reference,
        user_thoughts=args.user_thoughts,
        must_keep=args.must_keep,
        must_avoid=args.must_avoid,
    )
    return response


def _record_direction(args: argparse.Namespace) -> dict[str, Any]:
    store = RunStore(args.runs_root)
    task_key = _task_key_from_record(store, args.task_record)
    try:
        result = json.loads(Path(args.analyzer_result).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SlimRuntimeError(
            "SLIM_ANALYZER_OUTPUT_INVALID",
            "content_slim",
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
    registry = load_registry(args.registry)
    store = RunStore(args.runs_root)
    task_key = _task_key_from_record(store, args.task_record)
    frozen = store.read_task_input(task_key)
    location = resolve_client(registry, frozen["client_id"])
    _verify_frozen_client_location(
        frozen,
        vault_root=location.vault_root,
        manifest_path=location.manifest_path,
    )
    manifest = load_manifest(
        location.manifest_path, expected_client_id=frozen["client_id"]
    )
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
        "message": "受控 03/04/05 已准备，只交给 content-context-retriever 装配。",
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
            "content_slim",
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
        "message": "唯一 Context Pack 和冻结主模式已准备，只交给 content-writer 写正文。",
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
            "content_slim",
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
        "message": "已确认正文已准备，只交给 content-publish-pack 生成完整配套。",
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
            "content_slim",
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
        "next_action": "按当前阶段继续；不要跳过真人确认。" if not terminal else "本次任务无需继续。",
        "run_exists": True,
        "run_created_now": False,
        "artifacts_exist": artifacts_exist,
        "artifacts_preserved": artifacts_exist,
    }


def _add_registry_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--registry", default=str(default_registry_path()))


def _add_runs_root_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--runs-root", default=str(default_runs_root()))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Content V2 Slim runtime entry")
    subparsers = parser.add_subparsers(dest="operation", required=True)

    start = subparsers.add_parser("start", help="prepare one Run through Analyzer input")
    _add_registry_argument(start)
    _add_runs_root_argument(start)
    start.add_argument("--client-id")
    start.add_argument("--speaker-mode", choices=("personal_ip", "company_brand", "neutral"))
    start.add_argument("--topic-original", required=True)
    start.add_argument("--reference", action="append", required=True)
    start.add_argument("--user-thoughts")
    start.add_argument("--must-keep", action="append", default=[])
    start.add_argument("--must-avoid", action="append", default=[])
    start.set_defaults(handler=_start)

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
    args = build_parser().parse_args(argv)
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
