"""Validate Slim semantic handoffs without adding another runtime module."""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Any, Iterable

from .error_model import SlimRuntimeError


ANALYZER_INPUT_FIELDS = {
    "analysis_version",
    "topic_original",
    "topic_normalized",
    "topic_normalized_source",
    "client_id",
    "speaker_mode",
    "user_thoughts",
    "must_keep",
    "must_avoid",
    "references",
    "method_candidates",
    "revision_request",
}
ANALYZER_OUTPUT_FIELDS = {
    "analysis_version",
    "reference_analyses",
    "selected_method_assets",
    "fused_direction",
    "content_goal",
    "speaker_mode",
    "writer_mode",
    "writer_mode_reason",
    "secondary_tactics",
    "business_context_needs",
    "customer_readable_direction",
}
ASSET_ROLES = {"peer_content_asset", "oral_method_asset"}
SPEAKER_MODES = {"personal_ip", "company_brand", "neutral"}
CONTENT_GOALS = {"explain", "discuss", "convert"}
WRITER_MODES = {"ganhuo", "huati", "zhuanhua"}
GATE_A_CHOICES = ("认可整版方向", "需要修改", "不采用")
CONTEXT_INPUT_FIELDS = {
    "context_version",
    "client_id",
    "speaker_mode",
    "task_input",
    "approved_direction",
    "selected_external_reference_mechanisms",
    "selected_04_assets",
    "business_context_needs",
    "knowledge_candidates",
    "profile_candidate",
    "writer_mode",
    "secondary_tactics",
}
CONTEXT_OUTPUT_FIELDS = {
    "context_version",
    "client_id",
    "speaker_mode",
    "topic_original",
    "target_audience",
    "approved_direction",
    "user_thoughts",
    "must_keep",
    "must_avoid",
    "selected_external_reference_mechanisms",
    "selected_04_content_assets",
    "selected_04_method_assets",
    "selected_03_business_assets",
    "profile_context",
    "source_role_policy",
    "writer_mode",
    "secondary_tactics",
}
SOURCE_ROLE_POLICY = {
    "peer_content": "generalize_without_peer_identity_experience_case_business_data_or_quote",
    "client_business": "use_only_selected_03_for_client_specific_business_support",
    "client_profile": "personal_ip_only_keep_confirmed_profile_layers_separate",
    "missing_business": "use_general_or_conditional_language_and_do_not_invent_client_facts",
}
WRITER_RESULT_FIELDS = {"paragraphs"}
PUBLISH_PACK_RESULT_FIELDS = {
    "cover_titles",
    "publish_titles",
    "recommended_cover_title",
    "recommended_publish_title",
    "publish_copy",
    "tags",
}


def _fail(
    code: str,
    detail: str,
    *,
    workflow_stage: str = "正在拆解并匹配客户内容方向",
) -> None:
    raise SlimRuntimeError(
        code,
        "schema_validation",
        detail=detail,
        workflow_stage=workflow_stage,
        run_exists=True,
        artifacts_exist=True,
        artifacts_preserved=True,
    )


def _nonempty(value: Any, field: str, *, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(code, f"{field} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, field: str, *, code: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        _fail(code, f"{field} must be a string list")
    normalized = [item.strip() for item in value]
    if len(normalized) != len(set(normalized)):
        _fail(code, f"{field} contains duplicates")
    return normalized


def _relative_markdown(value: Any, field: str, *, code: str) -> str:
    if not isinstance(value, str) or "\\" in value:
        _fail(code, f"{field} is not a relative POSIX path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.suffix.casefold() != ".md"
    ):
        _fail(code, f"{field} escapes method_root or is not Markdown")
    return path.as_posix()


def validate_analyzer_input(value: Any) -> dict[str, Any]:
    code = "SLIM_ANALYZER_INPUT_INVALID"
    if not isinstance(value, dict) or set(value) - {"planning_guidance"} != ANALYZER_INPUT_FIELDS:
        _fail(code, "analyzer input fields do not match the single contract")
    if value["analysis_version"] != "slim-1.0":
        _fail(code, "unsupported analysis_version")
    _nonempty(value["topic_original"], "topic_original", code=code)
    _nonempty(value["topic_normalized"], "topic_normalized", code=code)
    if value["topic_normalized_source"] != "system_generated":
        _fail(code, "topic_normalized must be marked as a system result")
    _nonempty(value["client_id"], "client_id", code=code)
    if value["speaker_mode"] not in SPEAKER_MODES:
        _fail(code, "speaker_mode is invalid")
    if value["user_thoughts"] is not None:
        _nonempty(value["user_thoughts"], "user_thoughts", code=code)
    _string_list(value["must_keep"], "must_keep", code=code)
    _string_list(value["must_avoid"], "must_avoid", code=code)

    references = value["references"]
    if not isinstance(references, list) or not 0 <= len(references) <= 5:
        _fail(code, "references must contain 0 to 5 items")
    expected_ids = [f"REF-{index:03d}" for index in range(1, len(references) + 1)]
    actual_ids: list[str] = []
    for index, item in enumerate(references, 1):
        if not isinstance(item, dict) or set(item) != {
            "reference_id",
            "title",
            "content",
            "source_boundary",
        }:
            _fail(code, f"reference #{index} fields are invalid")
        actual_ids.append(_nonempty(item["reference_id"], "reference_id", code=code))
        _nonempty(item["title"], "reference title", code=code)
        _nonempty(item["content"], "reference content", code=code)
        _nonempty(item["source_boundary"], "source_boundary", code=code)
    if actual_ids != expected_ids:
        _fail(code, "reference ids must preserve the prepared source order")

    candidates = value["method_candidates"]
    if not isinstance(candidates, list) or len(candidates) > 5:
        _fail(code, "method_candidates must contain at most 5 items")
    counts = {role: 0 for role in ASSET_ROLES}
    seen_assets: set[str] = set()
    for index, item in enumerate(candidates, 1):
        if not isinstance(item, dict) or set(item) - {"source_metadata"} != {
            "asset_id",
            "asset_role",
            "relative_path",
            "page_sha256",
            "audience_scope",
            "excerpt",
            "relevance_evidence",
        }:
            _fail(code, f"method candidate #{index} fields are invalid")
        asset_id = _nonempty(item["asset_id"], "asset_id", code=code)
        if asset_id in seen_assets:
            _fail(code, "method candidate asset_id is duplicated")
        seen_assets.add(asset_id)
        role = item["asset_role"]
        if role not in ASSET_ROLES:
            _fail(code, "method candidate role is invalid")
        counts[role] += 1
        _relative_markdown(item["relative_path"], "relative_path", code=code)
        if not isinstance(item["page_sha256"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", item["page_sha256"]
        ):
            _fail(code, "method candidate page_sha256 is invalid")
        if item["audience_scope"] not in {"consumer", "internal_sales_training", "both"}:
            _fail(code, "method candidate audience_scope is invalid")
        _nonempty(item["excerpt"], "method excerpt", code=code)
        _string_list(item["relevance_evidence"], "relevance_evidence", code=code)
        if "source_metadata" in item and not isinstance(item["source_metadata"], dict):
            _fail(code, "candidate source metadata must be an object")
    if counts["peer_content_asset"] > 3 or counts["oral_method_asset"] > 2:
        _fail(code, "method candidate role limits were exceeded")
    guidance = value.get("planning_guidance", [])
    if not isinstance(guidance, list) or len(guidance) > 3:
        _fail(code, "planning guidance exceeds three bounded documents")
    for item in guidance:
        if not isinstance(item, dict) or set(item) != {"asset_id", "relative_path", "page_sha256", "content", "reason"}:
            _fail(code, "invalid planning guidance fields")
        _relative_markdown(item["relative_path"], "planning guidance path", code=code)
        for field in ("asset_id", "content", "reason"):
            _nonempty(item[field], field, code=code)
        if not isinstance(item["page_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["page_sha256"]):
            _fail(code, "invalid planning guidance hash")

    revision = value["revision_request"]
    if revision is not None:
        if not isinstance(revision, dict) or set(revision) != {
            "base_direction_version",
            "feedback",
        }:
            _fail(code, "revision_request fields are invalid")
        if not isinstance(revision["base_direction_version"], int) or revision[
            "base_direction_version"
        ] < 1:
            _fail(code, "base_direction_version is invalid")
        _nonempty(revision["feedback"], "revision feedback", code=code)
    return value


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def _normalized_phrase(value: str) -> str:
    return re.sub(r"[\s，。！？；：、,.!?;:'\"“”‘’（）()【】\[\]-]", "", value.casefold())


def _exact_source_phrases(references: list[dict[str, Any]]) -> set[str]:
    phrases: set[str] = set()
    for reference in references:
        for clause in re.split(r"[。！？!?\n]", reference["content"]):
            normalized = _normalized_phrase(clause)
            if 18 <= len(normalized) <= 120:
                phrases.add(normalized)
    return phrases


def validate_analyzer_result(
    value: Any, analyzer_input: dict[str, Any]
) -> dict[str, Any]:
    code = "SLIM_ANALYZER_OUTPUT_INVALID"
    validate_analyzer_input(analyzer_input)
    if not isinstance(value, dict) or set(value) != ANALYZER_OUTPUT_FIELDS:
        _fail(code, "analyzer output fields do not match the single contract")
    if value["analysis_version"] != "slim-1.0":
        _fail(code, "unsupported analysis_version")
    if value["speaker_mode"] != analyzer_input["speaker_mode"]:
        _fail(code, "Analyzer changed frozen speaker_mode")
    if value["content_goal"] not in CONTENT_GOALS:
        _fail(code, "content_goal is invalid")
    if value["writer_mode"] not in WRITER_MODES:
        _fail(code, "writer_mode is invalid")
    _nonempty(value["writer_mode_reason"], "writer_mode_reason", code=code)
    _string_list(value["secondary_tactics"], "secondary_tactics", code=code)
    _string_list(value["business_context_needs"], "business_context_needs", code=code)

    analyses = value["reference_analyses"]
    if not isinstance(analyses, list):
        _fail(code, "reference_analyses must be a list")
    expected_ids = [item["reference_id"] for item in analyzer_input["references"]]
    actual_ids: list[str] = []
    protected_fragments: set[str] = set()
    for index, item in enumerate(analyses, 1):
        if not isinstance(item, dict) or set(item) != {
            "reference_id",
            "content_value",
            "hook_mechanism",
            "structure_mechanism",
            "transferable_points",
            "prohibited_transfers",
        }:
            _fail(code, f"reference analysis #{index} fields are invalid")
        actual_ids.append(_nonempty(item["reference_id"], "reference_id", code=code))
        _nonempty(item["content_value"], "content_value", code=code)
        _nonempty(item["hook_mechanism"], "hook_mechanism", code=code)
        _nonempty(item["structure_mechanism"], "structure_mechanism", code=code)
        _string_list(item["transferable_points"], "transferable_points", code=code)
        protected_fragments.update(
            _string_list(item["prohibited_transfers"], "prohibited_transfers", code=code)
        )
    if actual_ids != expected_ids:
        _fail(code, "reference analyses must preserve every prepared reference exactly once")

    candidates = {item["asset_id"]: item for item in analyzer_input["method_candidates"]}
    selected = value["selected_method_assets"]
    if not isinstance(selected, list) or len(selected) > 5:
        _fail(code, "selected_method_assets must contain at most 5 items")
    if not expected_ids and not selected:
        _fail(code, "without explicit references, select supported library material before proposing a library-backed direction")
    selected_ids: set[str] = set()
    for index, item in enumerate(selected, 1):
        if not isinstance(item, dict) or set(item) != {
            "asset_id",
            "asset_role",
            "relative_path",
            "page_sha256",
            "usage",
            "reason",
        }:
            _fail(code, f"selected method asset #{index} fields are invalid")
        asset_id = _nonempty(item["asset_id"], "selected asset_id", code=code)
        if asset_id in selected_ids or asset_id not in candidates:
            _fail(code, "selected method asset is duplicated or was not offered")
        selected_ids.add(asset_id)
        offered = candidates[asset_id]
        for field in ("asset_role", "relative_path", "page_sha256"):
            if item[field] != offered[field]:
                _fail(code, f"selected method asset changed {field}")
        _nonempty(item["usage"], "method asset usage", code=code)
        _nonempty(item["reason"], "method asset reason", code=code)

    if not expected_ids and selected and all(
        candidates[item["asset_id"]].get("source_metadata", {}).get("method_kind") in {"enhancement", "selection_guide", "index", "methodology"}
        or candidates[item["asset_id"]].get("source_metadata", {}).get("structure_layer") == "enhancement"
        or item["asset_id"].startswith("ORAL-ENH-") for item in selected
    ):
        _fail(code, "enhancements or planning guides alone cannot supply a content blueprint")

    fused = value["fused_direction"]
    if not isinstance(fused, dict) or set(fused) != {
        "target_audience",
        "core_promise",
        "external_reference_value",
        "structure_plan",
        "conflicts",
        "user_boundaries",
        "generalization_boundary",
    }:
        _fail(code, "fused_direction fields are invalid")
    _nonempty(fused["target_audience"], "target_audience", code=code)
    _nonempty(fused["core_promise"], "core_promise", code=code)
    _string_list(fused["external_reference_value"], "external_reference_value", code=code)
    _string_list(fused["structure_plan"], "structure_plan", code=code)
    if not expected_ids and not fused["structure_plan"]:
        _fail(code, "structure_plan must explain the actual content progression")
    if not expected_ids and fused["external_reference_value"]:
        _fail(code, "library materials must not be presented as user-supplied external references")
    if not isinstance(fused["conflicts"], list):
        _fail(code, "conflicts must be a list")
    for conflict in fused["conflicts"]:
        if not isinstance(conflict, dict) or set(conflict) != {
            "reference_ids",
            "issue",
            "resolution",
        }:
            _fail(code, "conflict fields are invalid")
        ids = _string_list(conflict["reference_ids"], "conflict reference_ids", code=code)
        if len(ids) < 2 or any(item not in expected_ids for item in ids):
            _fail(code, "conflict must bind at least two known references")
        _nonempty(conflict["issue"], "conflict issue", code=code)
        _nonempty(conflict["resolution"], "conflict resolution", code=code)
    if not isinstance(fused["user_boundaries"], dict) or set(fused["user_boundaries"]) != {
        "user_thoughts",
        "must_keep",
        "must_avoid",
    }:
        _fail(code, "user_boundaries fields are invalid")
    if fused["user_boundaries"] != {
        "user_thoughts": analyzer_input["user_thoughts"],
        "must_keep": analyzer_input["must_keep"],
        "must_avoid": analyzer_input["must_avoid"],
    }:
        _fail(code, "Analyzer changed frozen user boundaries")
    _nonempty(fused["generalization_boundary"], "generalization_boundary", code=code)

    readable = value["customer_readable_direction"]
    if not isinstance(readable, dict) or set(readable) != {
        "original_topic",
        "target_audience",
        "core_promise",
        "borrowed_value",
        "method_asset_usage",
        "oral_structure",
        "user_boundaries",
        "speaker_mode_explanation",
        "writer_recommendation",
        "generalization_boundary",
    }:
        _fail(code, "customer_readable_direction fields are invalid")
    if readable["original_topic"] != analyzer_input["topic_original"]:
        _fail(code, "customer direction did not preserve topic_original verbatim")
    if readable["target_audience"] != fused["target_audience"]:
        _fail(code, "customer direction changed Analyzer target audience")
    _nonempty(readable["core_promise"], "customer core_promise", code=code)
    _string_list(readable["borrowed_value"], "borrowed_value", code=code)
    _string_list(readable["method_asset_usage"], "method_asset_usage", code=code)
    _string_list(readable["oral_structure"], "oral_structure", code=code)
    if readable["user_boundaries"] != fused["user_boundaries"]:
        _fail(code, "customer direction changed user boundaries")
    _nonempty(readable["speaker_mode_explanation"], "speaker_mode_explanation", code=code)
    if not isinstance(readable["writer_recommendation"], dict) or set(
        readable["writer_recommendation"]
    ) != {"mode", "reason"}:
        _fail(code, "writer_recommendation fields are invalid")
    if readable["writer_recommendation"]["mode"] != value["writer_mode"]:
        _fail(code, "customer direction changed Writer mode")
    _nonempty(
        readable["writer_recommendation"]["reason"],
        "customer Writer recommendation reason",
        code=code,
    )
    _nonempty(readable["generalization_boundary"], "generalization_boundary", code=code)

    if readable["core_promise"] != fused["core_promise"]:
        _fail(code, "customer direction changed the fused core promise")
    if readable["borrowed_value"] != fused["external_reference_value"]:
        _fail(code, "customer direction changed the fused reference value")
    if readable["oral_structure"] != fused["structure_plan"]:
        _fail(code, "customer direction changed the fused oral structure")
    if readable["generalization_boundary"] != fused["generalization_boundary"]:
        _fail(code, "customer direction changed the fused generalization boundary")
    if readable["writer_recommendation"]["reason"] != value["writer_mode_reason"]:
        _fail(code, "customer direction changed the Writer reason")
    if readable["method_asset_usage"] != [item["usage"] for item in selected]:
        _fail(code, "customer direction changed selected 04 asset usage")

    customer_text = _normalized_phrase("\n".join(_walk_strings(readable)))
    fused_text = _normalized_phrase("\n".join(_walk_strings(fused)))
    for fragment in protected_fragments:
        normalized = _normalized_phrase(fragment)
        if len(normalized) >= 6 and (normalized in customer_text or normalized in fused_text):
            _fail(code, "a prohibited peer identity, case, business, data, or phrase was transferred")
    blueprint_text = _normalized_phrase(
        "\n".join(build_writer_reference_blueprint(value))
    )
    for phrase in _exact_source_phrases(analyzer_input["references"]):
        if phrase in customer_text:
            _fail(code, "customer direction copied a long identifiable source phrase")
        if phrase in blueprint_text:
            _fail(code, "detailed reference blueprint copied a long identifiable source phrase")
    return value


def build_gate_a(result: dict[str, Any], direction_version: int) -> dict[str, Any]:
    readable = result["customer_readable_direction"]
    return {
        "direction_version": direction_version,
        "original_topic": readable["original_topic"],
        "target_audience": readable["target_audience"],
        "core_promise": readable["core_promise"],
        "external_reference_value": readable["borrowed_value"],
        "method_asset_usage": readable["method_asset_usage"],
        "oral_structure": readable["oral_structure"],
        "user_boundaries": readable["user_boundaries"],
        "speaker_mode": result["speaker_mode"],
        "speaker_mode_explanation": readable["speaker_mode_explanation"],
        "content_goal": result["content_goal"],
        "writer_recommendation": readable["writer_recommendation"],
        "secondary_tactics": result["secondary_tactics"],
        "business_context_needs": result["business_context_needs"],
        "generalization_boundary": readable["generalization_boundary"],
        "choices": list(GATE_A_CHOICES),
    }


def build_writer_reference_blueprint(result: dict[str, Any]) -> list[str]:
    """Project the detailed Analyzer report into the existing Writer context field."""

    blueprint: list[str] = []
    for analysis in result["reference_analyses"]:
        transferable = "；".join(analysis["transferable_points"]) or "无"
        prohibited = "；".join(analysis["prohibited_transfers"]) or "无"
        blueprint.append(
            f"{analysis['reference_id']}｜内容价值：{analysis['content_value']}"
            f"｜钩子机制：{analysis['hook_mechanism']}"
            f"｜结构机制：{analysis['structure_mechanism']}"
            f"｜可迁移：{transferable}"
            f"｜禁止迁移：{prohibited}"
        )
    for conflict in result["fused_direction"]["conflicts"]:
        reference_ids = "+".join(conflict["reference_ids"])
        blueprint.append(
            f"融合冲突（{reference_ids}）｜冲突：{conflict['issue']}"
            f"｜处理：{conflict['resolution']}"
        )
    return blueprint


def approval_snapshot(
    result: dict[str, Any], gate_a: dict[str, Any], direction_version: int
) -> dict[str, Any]:
    if gate_a.get("direction_version") != direction_version:
        _fail("SLIM_DIRECTION_RESPONSE_INVALID", "Gate A version does not match approval")
    approved_direction = {
        "target_audience": gate_a["target_audience"],
        "core_promise": gate_a["core_promise"],
        "external_reference_value": gate_a["external_reference_value"],
        "structure_plan": gate_a["oral_structure"],
        "user_boundaries": gate_a["user_boundaries"],
        "generalization_boundary": gate_a["generalization_boundary"],
    }
    return {
        "approval_version": "content-koubo-slim-approved-direction-v1",
        "direction_version": direction_version,
        "approved_gate_a": gate_a,
        "gate_a_sha256": canonical_json_hash(gate_a),
        "approved_direction": approved_direction,
        "selected_method_assets": result["selected_method_assets"],
        "content_goal": gate_a["content_goal"],
        "speaker_mode": gate_a["speaker_mode"],
        "writer_mode": gate_a["writer_recommendation"]["mode"],
        "writer_mode_reason": gate_a["writer_recommendation"]["reason"],
        "secondary_tactics": gate_a["secondary_tactics"],
        "business_context_needs": gate_a["business_context_needs"],
    }


def canonical_json_hash(value: Any) -> str:
    return __import__("hashlib").sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _validate_approved_direction(value: Any, *, code: str) -> dict[str, Any]:
    expected = {
        "target_audience",
        "core_promise",
        "external_reference_value",
        "structure_plan",
        "user_boundaries",
        "generalization_boundary",
    }
    if not isinstance(value, dict) or set(value) != expected:
        _fail(code, "approved_direction fields are invalid", workflow_stage="正在准备客户内容资料")
    _nonempty(value["target_audience"], "target_audience", code=code)
    _nonempty(value["core_promise"], "core_promise", code=code)
    _string_list(value["external_reference_value"], "external_reference_value", code=code)
    _string_list(value["structure_plan"], "structure_plan", code=code)
    boundaries = value["user_boundaries"]
    if not isinstance(boundaries, dict) or set(boundaries) != {
        "user_thoughts",
        "must_keep",
        "must_avoid",
    }:
        _fail(code, "approved user_boundaries are invalid", workflow_stage="正在准备客户内容资料")
    if boundaries["user_thoughts"] is not None:
        _nonempty(boundaries["user_thoughts"], "user_thoughts", code=code)
    _string_list(boundaries["must_keep"], "must_keep", code=code)
    _string_list(boundaries["must_avoid"], "must_avoid", code=code)
    _nonempty(value["generalization_boundary"], "generalization_boundary", code=code)
    return value


def validate_context_retriever_input(value: Any) -> dict[str, Any]:
    code = "SLIM_CONTEXT_INPUT_INVALID"
    stage = "正在准备客户内容资料"
    if not isinstance(value, dict) or set(value) - {"source_mode"} != CONTEXT_INPUT_FIELDS:
        _fail(code, "context retriever input fields do not match the single contract", workflow_stage=stage)
    if value["context_version"] != "slim-1.0":
        _fail(code, "unsupported context_version", workflow_stage=stage)
    _nonempty(value["client_id"], "client_id", code=code)
    if value["speaker_mode"] not in SPEAKER_MODES:
        _fail(code, "speaker_mode is invalid", workflow_stage=stage)
    task = value["task_input"]
    if not isinstance(task, dict) or set(task) != {
        "topic_original",
        "user_thoughts",
        "must_keep",
        "must_avoid",
    }:
        _fail(code, "task_input fields are invalid", workflow_stage=stage)
    _nonempty(task["topic_original"], "topic_original", code=code)
    if task["user_thoughts"] is not None:
        _nonempty(task["user_thoughts"], "user_thoughts", code=code)
    _string_list(task["must_keep"], "must_keep", code=code)
    _string_list(task["must_avoid"], "must_avoid", code=code)

    approved = _validate_approved_direction(value["approved_direction"], code=code)
    if approved["user_boundaries"] != {
        "user_thoughts": task["user_thoughts"],
        "must_keep": task["must_keep"],
        "must_avoid": task["must_avoid"],
    }:
        _fail(code, "approved direction changed frozen user boundaries", workflow_stage=stage)
    mechanisms = _string_list(
        value["selected_external_reference_mechanisms"],
        "selected_external_reference_mechanisms",
        code=code,
    )
    library_mode = value.get("source_mode") == "library"
    if value.get("source_mode", "external") not in {"external", "library"}:
        _fail(code, "unknown source mode", workflow_stage=stage)
    if library_mode and mechanisms:
        _fail(code, "library mode cannot invent external mechanisms", workflow_stage=stage)
    if not mechanisms and not (library_mode and value["selected_04_assets"] and approved["structure_plan"]):
        _fail(code, "detailed reference blueprint is missing", workflow_stage=stage)

    selected = value["selected_04_assets"]
    if not isinstance(selected, list) or len(selected) > 5:
        _fail(code, "selected_04_assets must contain at most five items", workflow_stage=stage)
    seen: set[str] = set()
    for item in selected:
        if not isinstance(item, dict) or set(item) - {"source_metadata"} != {
            "asset_id",
            "asset_role",
            "relative_path",
            "page_sha256",
            "title",
            "source_excerpt",
            "approved_usage",
        }:
            _fail(code, "selected 04 asset fields are invalid", workflow_stage=stage)
        asset_id = _nonempty(item["asset_id"], "asset_id", code=code)
        if asset_id in seen:
            _fail(code, "selected 04 asset is duplicated", workflow_stage=stage)
        seen.add(asset_id)
        if item["asset_role"] not in ASSET_ROLES:
            _fail(code, "selected 04 role is invalid", workflow_stage=stage)
        _relative_markdown(item["relative_path"], "selected 04 path", code=code)
        if not isinstance(item["page_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["page_sha256"]):
            _fail(code, "selected 04 hash is invalid", workflow_stage=stage)
        for field in ("title", "source_excerpt", "approved_usage"):
            _nonempty(item[field], field, code=code)
        if "source_metadata" in item and not isinstance(item["source_metadata"], dict):
            _fail(code, "source metadata must be an object", workflow_stage=stage)

    needs = _string_list(value["business_context_needs"], "business_context_needs", code=code)
    candidates = value["knowledge_candidates"]
    if not isinstance(candidates, list) or len(candidates) > 5 or (not needs and candidates):
        _fail(code, "knowledge candidates do not match business needs", workflow_stage=stage)
    seen_paths: set[str] = set()
    for item in candidates:
        if not isinstance(item, dict) or set(item) != {
            "relative_path",
            "page_sha256",
            "title",
            "excerpt",
            "relevance_evidence",
        }:
            _fail(code, "knowledge candidate fields are invalid", workflow_stage=stage)
        relative = _relative_markdown(item["relative_path"], "knowledge path", code=code)
        if relative in seen_paths:
            _fail(code, "knowledge candidate is duplicated", workflow_stage=stage)
        seen_paths.add(relative)
        if not isinstance(item["page_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["page_sha256"]):
            _fail(code, "knowledge hash is invalid", workflow_stage=stage)
        _nonempty(item["title"], "knowledge title", code=code)
        _nonempty(item["excerpt"], "knowledge excerpt", code=code)
        if not _string_list(item["relevance_evidence"], "relevance_evidence", code=code):
            _fail(code, "knowledge candidate lacks relevance evidence", workflow_stage=stage)

    profile = value["profile_candidate"]
    if value["speaker_mode"] == "personal_ip":
        if not isinstance(profile, dict) or set(profile) != {
            "relative_path",
            "page_sha256",
            "title",
            "content",
        }:
            _fail(code, "personal_ip requires one selected frozen Profile", workflow_stage=stage)
        _relative_markdown(profile["relative_path"], "profile path", code=code)
        if not isinstance(profile["page_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", profile["page_sha256"]):
            _fail(code, "profile hash is invalid", workflow_stage=stage)
        _nonempty(profile["title"], "profile title", code=code)
        _nonempty(profile["content"], "profile content", code=code)
    elif profile is not None:
        _fail(code, "non-personal speaker mode must not receive profile content", workflow_stage=stage)
    if value["writer_mode"] not in WRITER_MODES:
        _fail(code, "writer_mode is invalid", workflow_stage=stage)
    _string_list(value["secondary_tactics"], "secondary_tactics", code=code)
    return value


def _source_phrases(text: str) -> list[str]:
    phrases: list[str] = []
    for part in re.split(r"[。！？!?\n]+", text):
        normalized = _normalized_phrase(part)
        if len(normalized) >= 18:
            phrases.append(normalized)
    return phrases


def validate_content_context(
    value: Any, context_input: dict[str, Any]
) -> dict[str, Any]:
    code = "SLIM_CONTEXT_OUTPUT_INVALID"
    stage = "正在准备客户内容资料"
    context_input = validate_context_retriever_input(context_input)
    if not isinstance(value, dict) or set(value) != CONTEXT_OUTPUT_FIELDS:
        _fail(code, "content context fields do not match the single contract", workflow_stage=stage)
    task = context_input["task_input"]
    approved = context_input["approved_direction"]
    exact_pairs = {
        "context_version": context_input["context_version"],
        "client_id": context_input["client_id"],
        "speaker_mode": context_input["speaker_mode"],
        "topic_original": task["topic_original"],
        "target_audience": approved["target_audience"],
        "approved_direction": approved,
        "user_thoughts": task["user_thoughts"],
        "must_keep": task["must_keep"],
        "must_avoid": task["must_avoid"],
        "selected_external_reference_mechanisms": context_input["selected_external_reference_mechanisms"],
        "writer_mode": context_input["writer_mode"],
        "secondary_tactics": context_input["secondary_tactics"],
    }
    for field, expected in exact_pairs.items():
        if value[field] != expected:
            _fail(code, f"content context changed frozen field {field}", workflow_stage=stage)

    selected_by_id = {item["asset_id"]: item for item in context_input["selected_04_assets"]}
    actual_ids: set[str] = set()
    for field, expected_role in (
        ("selected_04_content_assets", "peer_content_asset"),
        ("selected_04_method_assets", "oral_method_asset"),
    ):
        items = value[field]
        if not isinstance(items, list):
            _fail(code, f"{field} must be a list", workflow_stage=stage)
        for item in items:
            if not isinstance(item, dict) or set(item) - {"source_metadata"} != {
                "asset_id",
                "relative_path",
                "source_role",
                "approved_usage",
                "writer_context",
                "transfer_boundary",
            }:
                _fail(code, "04 context fields are invalid", workflow_stage=stage)
            asset_id = _nonempty(item["asset_id"], "asset_id", code=code)
            offered = selected_by_id.get(asset_id)
            if offered is None or asset_id in actual_ids or offered["asset_role"] != expected_role:
                _fail(code, "04 context changed the frozen selection or role", workflow_stage=stage)
            actual_ids.add(asset_id)
            if item.get("source_metadata") != offered.get("source_metadata"):
                _fail(code, "04 context changed source restrictions", workflow_stage=stage)
            if (
                item["relative_path"] != offered["relative_path"]
                or item["source_role"] != expected_role
                or item["approved_usage"] != offered["approved_usage"]
                or item["transfer_boundary"] != approved["generalization_boundary"]
            ):
                _fail(code, "04 context changed path, usage, role, or transfer boundary", workflow_stage=stage)
            writer_context = _nonempty(item["writer_context"], "writer_context", code=code)
            normalized_writer = _normalized_phrase(writer_context)
            if any(phrase in normalized_writer for phrase in _source_phrases(offered["source_excerpt"])):
                _fail(code, "04 context copied an identifiable source phrase", workflow_stage=stage)
    if actual_ids != set(selected_by_id):
        _fail(code, "content context omitted or added a frozen 04 asset", workflow_stage=stage)

    candidate_by_path = {
        item["relative_path"]: item for item in context_input["knowledge_candidates"]
    }
    selected_paths: set[str] = set()
    business_items = value["selected_03_business_assets"]
    if not isinstance(business_items, list) or len(business_items) > 5:
        _fail(code, "selected 03 assets exceed the limit", workflow_stage=stage)
    for item in business_items:
        if not isinstance(item, dict) or set(item) != {
            "relative_path",
            "source_role",
            "excerpt",
            "usage",
        }:
            _fail(code, "03 context fields are invalid", workflow_stage=stage)
        candidate = candidate_by_path.get(item["relative_path"])
        if candidate is None or item["relative_path"] in selected_paths:
            _fail(code, "03 context selected an unavailable or duplicate candidate", workflow_stage=stage)
        selected_paths.add(item["relative_path"])
        if item["source_role"] != "client_business" or item["excerpt"] != candidate["excerpt"]:
            _fail(code, "03 context changed source role or excerpt", workflow_stage=stage)
        _nonempty(item["usage"], "03 usage", code=code)

    profile = value["profile_context"]
    candidate_profile = context_input["profile_candidate"]
    if context_input["speaker_mode"] == "personal_ip":
        if not isinstance(profile, dict) or set(profile) != {
            "relative_path",
            "source_role",
            "selected_passages",
            "usage",
        }:
            _fail(code, "personal_ip context lacks profile_context", workflow_stage=stage)
        if profile["relative_path"] != candidate_profile["relative_path"] or profile["source_role"] != "client_profile":
            _fail(code, "profile context changed source binding", workflow_stage=stage)
        passages = _string_list(profile["selected_passages"], "selected_passages", code=code)
        if not 1 <= len(passages) <= 8:
            _fail(code, "profile selected_passages must contain 1 to 8 items", workflow_stage=stage)
        source_profile = _normalized_phrase(candidate_profile["content"])
        if any(_normalized_phrase(item) not in source_profile for item in passages):
            _fail(code, "profile context contains a passage not found in the selected Profile", workflow_stage=stage)
        _nonempty(profile["usage"], "profile usage", code=code)
    elif profile is not None:
        _fail(code, "non-personal context must not include profile_context", workflow_stage=stage)

    if value["source_role_policy"] != SOURCE_ROLE_POLICY:
        _fail(code, "source_role_policy changed the frozen source boundaries", workflow_stage=stage)
    for text in _walk_strings(value):
        if re.fullmatch(r"[0-9a-f]{64}", text) or text.startswith(("/", "~", "file://")):
            _fail(code, "Writer context contains an internal hash or absolute path", workflow_stage=stage)
    return value


def validate_writer_context(
    value: Any,
    *,
    frozen_task: dict[str, Any],
    approved_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Recheck the fixed P3 pack without reopening Vault assets."""

    code = "SLIM_CONTEXT_OUTPUT_INVALID"
    stage = "正在生成正文"
    if not isinstance(value, dict) or set(value) != CONTEXT_OUTPUT_FIELDS:
        _fail(code, "Writer input is not the single Content Context Pack", workflow_stage=stage)
    expected = {
        "context_version": "slim-1.0",
        "client_id": frozen_task.get("client_id"),
        "speaker_mode": frozen_task.get("speaker_mode"),
        "topic_original": frozen_task.get("topic_original"),
        "approved_direction": approved_snapshot.get("approved_direction"),
        "writer_mode": approved_snapshot.get("writer_mode"),
        "secondary_tactics": approved_snapshot.get("secondary_tactics"),
    }
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            _fail(code, f"Writer input changed frozen field {field}", workflow_stage=stage)
    boundaries = value["approved_direction"].get("user_boundaries")
    if boundaries != {
        "user_thoughts": value["user_thoughts"],
        "must_keep": value["must_keep"],
        "must_avoid": value["must_avoid"],
    }:
        _fail(code, "Writer input changed approved user boundaries", workflow_stage=stage)
    if value["source_role_policy"] != SOURCE_ROLE_POLICY:
        _fail(code, "Writer input changed source role policy", workflow_stage=stage)
    return value


def validate_writer_result(value: Any) -> tuple[dict[str, Any], str]:
    """Accept only natural spoken paragraphs; program owns every machine field."""

    code = "SLIM_WRITER_OUTPUT_INVALID"
    stage = "正在生成正文"
    if not isinstance(value, dict) or set(value) != WRITER_RESULT_FIELDS:
        _fail(code, "Writer output must contain only paragraphs", workflow_stage=stage)
    paragraphs = value["paragraphs"]
    if not isinstance(paragraphs, list) or not paragraphs:
        _fail(code, "Writer output has no paragraphs", workflow_stage=stage)
    normalized: list[dict[str, str]] = []
    for item in paragraphs:
        if not isinstance(item, dict) or set(item) != {"text"}:
            _fail(code, "Each paragraph must contain only text", workflow_stage=stage)
        text = item["text"]
        if not isinstance(text, str):
            _fail(code, "Paragraph text must be a string", workflow_stage=stage)
        text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text or "\x00" in text or "\n\n" in text:
            _fail(code, "Paragraph text is empty or contains a hidden paragraph", workflow_stage=stage)
        if re.search(r"(?m)^\s*#{1,6}\s+", text) or "```" in text:
            _fail(code, "Draft contains Markdown or code-fence packaging", workflow_stage=stage)
        normalized.append({"text": text})
    body = "\n\n".join(item["text"] for item in normalized)
    return {"paragraphs": normalized}, body


def validate_publish_pack_result(value: Any) -> dict[str, Any]:
    """Accept the one P5 package object and no body or machine-owned fields."""

    code = "SLIM_PACKAGE_OUTPUT_INVALID"
    stage = "正在生成配套文案"
    if not isinstance(value, dict) or set(value) != PUBLISH_PACK_RESULT_FIELDS:
        _fail(code, "publish pack output fields do not match the single contract", workflow_stage=stage)

    cover_titles = _string_list(value["cover_titles"], "cover_titles", code=code)
    publish_titles = _string_list(value["publish_titles"], "publish_titles", code=code)
    if len(cover_titles) != 2 or len(publish_titles) != 3:
        _fail(code, "publish pack must contain 2 cover and 3 publish titles", workflow_stage=stage)

    normalized_titles: set[str] = set()
    title_limits = [(item, 18) for item in cover_titles] + [
        (item, 30) for item in publish_titles
    ]
    for title, limit in title_limits:
        if "\n" in title or "\x00" in title or "/" in title or "\\" in title:
            _fail(code, "title contains an unsafe separator", workflow_stage=stage)
        normalized = _normalized_phrase(title)
        if not 4 <= len(normalized) <= limit or normalized in normalized_titles:
            _fail(code, "title length or uniqueness is invalid", workflow_stage=stage)
        normalized_titles.add(normalized)

    recommended_cover = _nonempty(
        value["recommended_cover_title"], "recommended_cover_title", code=code
    )
    recommended_publish = _nonempty(
        value["recommended_publish_title"], "recommended_publish_title", code=code
    )
    if recommended_cover not in cover_titles or recommended_publish not in publish_titles:
        _fail(code, "recommended titles must come from current candidates", workflow_stage=stage)

    publish_copy = _nonempty(value["publish_copy"], "publish_copy", code=code)
    if "\x00" in publish_copy or not 50 <= len(re.sub(r"\s+", "", publish_copy)) <= 100:
        _fail(code, "publish_copy must contain 50 to 100 non-whitespace characters", workflow_stage=stage)

    tags = _string_list(value["tags"], "tags", code=code)
    if len(tags) != 5 or any(
        not tag.startswith("#")
        or len(tag) < 2
        or tag.count("#") != 1
        or any(character.isspace() for character in tag)
        for tag in tags
    ):
        _fail(code, "tags must contain 5 unique # labels without whitespace", workflow_stage=stage)

    return {
        "cover_titles": cover_titles,
        "publish_titles": publish_titles,
        "recommended_cover_title": recommended_cover,
        "recommended_publish_title": recommended_publish,
        "publish_copy": publish_copy,
        "tags": tags,
    }
