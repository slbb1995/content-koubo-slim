"""Return a small set of relevant 04 assets from one authorized method_root."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .error_model import SlimRuntimeError
from .feishu_source import FeishuRoot, iter_documents
from .vault_reader import (
    MethodAsset,
    read_knowledge_asset,
    read_method_asset,
    safe_knowledge_root,
    safe_method_root,
)


ROLE_LIMITS = {"peer_content_asset": 3, "oral_method_asset": 2}
MAX_MATERIAL_CHARACTERS = 12000


def method_kind(asset: MethodAsset) -> str:
    explicit = asset.metadata.get("method_kind") or asset.metadata.get("structure_layer")
    if explicit:
        return str(explicit)
    if asset.metadata.get("type") in {"oral_method", "oral_structure_index"}:
        return "selection_guide"
    if asset.asset_id.startswith("ORAL-ENH-"):
        return "enhancement"
    return "peer_deconstruction" if asset.asset_role == "peer_content_asset" else "structure"


def method_is_usable(asset: MethodAsset, audience_scope: str | None, allow_experimental: bool) -> bool:
    if audience_scope is not None and asset.audience_scope not in {audience_scope, "both"}:
        return False
    if not allow_experimental and asset.metadata.get("maturity") == "experimental_reference":
        return False
    if asset.metadata.get("usage_scope") in {"do_not_use", "counterexample_only", "blocked"}:
        return False
    return True


def complete_method_text(asset: MethodAsset) -> str:
    """Never silently chop off the reasoning, adaptation or forbidden-transfer sections."""
    if len(asset.body) > MAX_MATERIAL_CHARACTERS:
        raise SlimRuntimeError("SLIM_METHOD_ASSET_INVALID", "vault_search", detail="selected material exceeds 12000 characters; prepare a source-linked bounded asset")
    return asset.body


def method_source_metadata(asset: MethodAsset) -> dict[str, Any]:
    return {key: asset.metadata[key] for key in (
        "type", "status", "audience_scope", "method_kind", "structure_layer", "maturity",
        "usage_scope", "source_verification", "claim_scope", "applicable_workflows",
        "source_id", "source_section") if key in asset.metadata}


def discover_method_assets(method_root: str | Path | FeishuRoot, *, offset: int = 0, limit: int = 40,
                           audience_scope: str | None = None, allow_experimental: bool = False) -> dict[str, Any]:
    """Page metadata for Agent semantic selection; does not create a Run or choose a structure."""
    if offset < 0 or not 1 <= limit <= 50:
        raise SlimRuntimeError("SLIM_ANALYZER_INPUT_INVALID", "vault_search", detail="invalid discovery page")
    root = safe_method_root(method_root)
    if isinstance(root, FeishuRoot):
        # Remote discovery enumerates bounded titles only. Explicit read-path
        # requests fetch selected bodies; never scan all remote bodies for metadata.
        documents = list(iter_documents(root))
        items = [{"relative_path": "feishu:" + item.token, "title": item.title,
                  "metadata_only": True, "requires_read_path": True} for item in documents]
        return {"items": items[offset:offset+limit], "total": len(items),
                "next_offset": offset+limit if offset+limit < len(items) else None,
                "excluded": [], "excluded_total": 0, "wrote": False}
    items, excluded, ids = [], [], set()
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root).as_posix()
        try:
            asset = read_method_asset(root, relative, include_guidance=True)
        except SlimRuntimeError as exc:
            if "symlink" in exc.detail.casefold():
                raise
            excluded.append({"relative_path": relative, "reason": exc.detail})
            continue
        if asset.asset_id in ids:
            raise SlimRuntimeError("SLIM_METHOD_ASSET_INVALID", "vault_search", detail="duplicate asset id")
        ids.add(asset.asset_id)
        if not method_is_usable(asset, audience_scope, allow_experimental):
            excluded.append({"relative_path": relative, "reason": "audience, usage or experimental scope does not permit this task"})
            continue
        items.append({"asset_id": asset.asset_id, "relative_path": relative, "page_sha256": asset.page_sha256,
                      "asset_role": asset.asset_role, "title": asset.title, "method_kind": method_kind(asset),
                      "audience_scope": asset.audience_scope, "keywords": list(asset.keywords),
                      "use_when": list(asset.use_when), "content_purposes": asset.metadata.get("content_purposes", []),
                      "maturity": asset.metadata.get("maturity"), "usage_scope": asset.metadata.get("usage_scope"),
                      "source_verification": asset.metadata.get("source_verification")})
    return {"items": items[offset:offset+limit], "total": len(items),
            "next_offset": offset+limit if offset+limit < len(items) else None,
            "excluded": excluded[offset:offset+limit], "excluded_total": len(excluded), "wrote": False}


def select_method_assets(method_root: str | Path | FeishuRoot, selections: list[dict[str, Any]], *,
                         audience_scope: str | None = None, allow_experimental: bool = False) -> list[dict[str, Any]]:
    """Validate the Agent's semantic choice against real paths, bytes, roles and budget."""
    if not isinstance(selections, list) or len(selections) > 5:
        raise SlimRuntimeError("SLIM_ANALYZER_INPUT_INVALID", "vault_search", detail="select at most five 04 materials")
    counts = {role: 0 for role in ROLE_LIMITS}
    result, ids = [], set()
    for item in selections:
        if not isinstance(item, dict) or set(item) != {"relative_path", "page_sha256", "reason"} or not isinstance(item["reason"], str) or not item["reason"].strip():
            raise SlimRuntimeError("SLIM_ANALYZER_INPUT_INVALID", "vault_search", detail="semantic selection requires path, snapshot hash and reason")
        if not isinstance(item["page_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["page_sha256"]):
            raise SlimRuntimeError("SLIM_ANALYZER_INPUT_INVALID", "vault_search", detail="semantic selection requires valid snapshot hash")
        asset = read_method_asset(method_root, item["relative_path"], expected_sha256=item["page_sha256"])
        if asset.asset_id in ids or not method_is_usable(asset, audience_scope, allow_experimental):
            raise SlimRuntimeError("SLIM_METHOD_ASSET_INVALID", "vault_search", detail="duplicate or out-of-scope selected material")
        ids.add(asset.asset_id)
        counts[asset.asset_role] += 1
        if counts[asset.asset_role] > ROLE_LIMITS[asset.asset_role]:
            raise SlimRuntimeError("SLIM_ANALYZER_INPUT_INVALID", "vault_search", detail="selected material role budget exceeded")
        result.append({"asset_id": asset.asset_id, "asset_role": asset.asset_role,
                       "source_metadata": method_source_metadata(asset),
                       "relative_path": asset.relative_path, "page_sha256": asset.page_sha256,
                       "audience_scope": asset.audience_scope, "excerpt": complete_method_text(asset),
                       "relevance_evidence": ["语义选择："+item["reason"], "资料用途："+method_kind(asset),
                           "使用范围："+str(asset.metadata.get("usage_scope", "method_reference_only")),
                           "来源核验："+str(asset.metadata.get("source_verification", "not_declared"))]})
    return result
REMOTE_BODY_CANDIDATE_LIMIT = 12
STOP_TERMS = {
    "一个", "这个", "怎样", "怎么", "什么", "是否", "到底", "可以", "内容", "口播",
    "边界", "资料", "当前", "可核验", "公开使用", "表达边界", "产品或", "具体",
}
LOW_SIGNAL_TERMS = STOP_TERMS | {"观点", "结构", "方法", "表达", "问题", "主题"}
LOW_SIGNAL_SUBSTRINGS = {"边界", "核验", "表达", "公开使用", "使用的", "当前可"}
INDEX_TITLE_TERMS = {"index", "目录", "索引", "导航", "汇总"}
def _is_low_signal(term: str) -> bool:
    compact = term.casefold()
    return compact in LOW_SIGNAL_TERMS or any(
        fragment in compact for fragment in LOW_SIGNAL_SUBSTRINGS
    )


def _query_terms(query: str) -> tuple[str, ...]:
    compact = re.sub(r"\s+", "", query.casefold())
    terms = {
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9]{2,}|[\u4e00-\u9fff]{2,8}", query)
        if len(token) >= 2 and not _is_low_signal(token)
    }
    for chinese in re.findall(r"[\u4e00-\u9fff]+", compact):
        for width in (2, 3, 4):
            for start in range(max(0, len(chinese) - width + 1)):
                term = chinese[start : start + width]
                if not _is_low_signal(term):
                    terms.add(term)
    return tuple(sorted(terms, key=lambda item: (-len(item), item)))


def _score(asset: MethodAsset, query: str) -> tuple[int, list[str]]:
    compact_query = re.sub(r"\s+", "", query.casefold())
    evidence: list[str] = []
    score = 0
    for keyword in asset.keywords:
        normalized = re.sub(r"\s+", "", keyword.casefold())
        if (
            normalized
            and not _is_low_signal(normalized)
            and (normalized in compact_query or compact_query in normalized)
        ):
            evidence.append(f"关键词：{keyword}")
            score += 8
    for use_when in asset.use_when:
        normalized = re.sub(r"\s+", "", use_when.casefold())
        if (
            normalized
            and not _is_low_signal(normalized)
            and (normalized in compact_query or compact_query in normalized)
        ):
            evidence.append(f"适用场景：{use_when}")
            score += 6
    compact_title = re.sub(r"\s+", "", asset.title.casefold())
    if compact_title and (compact_title in compact_query or compact_query in compact_title):
        evidence.append(f"标题：{asset.title}")
        score += 6
    searchable = "\n".join((*asset.keywords, *asset.use_when, asset.title, asset.body)).casefold()
    supporting = [
        term
        for term in _query_terms(query)
        if len(term) >= 3 and term in searchable and not _is_low_signal(term)
    ]
    for term in supporting[:4]:
        evidence.append(f"相关线索：{term}")
        score += 4 if len(term) >= 5 else 2
    return score, evidence


def _excerpt(asset: MethodAsset, terms: tuple[str, ...], limit: int = 1200) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", asset.body) if part.strip()]
    selected = [
        paragraph
        for paragraph in paragraphs
        if any(term.casefold() in paragraph.casefold() for term in terms)
    ]
    if not selected:
        selected = paragraphs[:2]
    value = "\n\n".join(selected)
    return value[:limit].rstrip()


def search_method_assets(
    method_root: str | Path | FeishuRoot,
    *,
    query: str,
    audience_scope: str | None = None,
    allow_experimental: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(query, str) or not query.strip():
        raise SlimRuntimeError(
            "SLIM_ANALYZER_INPUT_INVALID",
            "vault_search",
            detail="method query is empty",
            workflow_stage="正在拆解并匹配客户内容方向",
        )
    root = safe_method_root(method_root)
    ranked: dict[str, list[tuple[int, MethodAsset, list[str]]]] = {
        role: [] for role in ROLE_LIMITS
    }
    seen_ids: set[str] = set()
    for relative in _candidate_refs(root, query):
        try:
            asset = read_method_asset(root, relative)
        except SlimRuntimeError as exc:
            if (isinstance(root, FeishuRoot) and exc.component != 'vault_reader') or "symlink" in exc.detail.casefold():
                raise
            continue
        if asset.asset_id in seen_ids:
            raise SlimRuntimeError(
                "SLIM_METHOD_ASSET_INVALID",
                "vault_search",
                detail=f"duplicate asset_id={asset.asset_id}",
                workflow_stage="正在拆解并匹配客户内容方向",
            )
        seen_ids.add(asset.asset_id)
        if not method_is_usable(asset, audience_scope, allow_experimental):
            continue
        score, evidence = _score(asset, query)
        if score < 6:
            continue
        ranked[asset.asset_role].append((score, asset, evidence))

    terms = _query_terms(query)
    output: list[dict[str, Any]] = []
    for role in ("peer_content_asset", "oral_method_asset"):
        items = sorted(ranked[role], key=lambda item: (-item[0], item[1].asset_id))
        for _, asset, evidence in items[: ROLE_LIMITS[role]]:
            output.append(
                {
                    "asset_id": asset.asset_id,
                    "asset_role": role,
                    "source_metadata": method_source_metadata(asset),
                    "relative_path": asset.relative_path,
                    "page_sha256": asset.page_sha256,
                    "audience_scope": asset.audience_scope,
                    "excerpt": complete_method_text(asset),
                    "relevance_evidence": [*evidence, "资料用途："+method_kind(asset),
                        "使用范围："+str(asset.metadata.get("usage_scope", "method_reference_only")),
                        "来源核验："+str(asset.metadata.get("source_verification", "not_declared"))],
                }
            )
    return output


def _is_index_page_title(title: str) -> bool:
    compact = re.sub(r"\s+", "", title.casefold())
    return any(term in compact for term in INDEX_TITLE_TERMS)


def _metadata_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        output: list[str] = []
        for item in value:
            output.extend(_metadata_strings(item))
        return output
    if isinstance(value, dict):
        output = []
        for key, item in value.items():
            output.extend(_metadata_strings(key))
            output.extend(_metadata_strings(item))
        return output
    return []


def _metadata_values(asset: Any) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for key in ("topics", "keywords", "use_when", "applicability", "product_names"):
        for value in _metadata_strings(asset.metadata.get(key)):
            values.append((key, value))
    return values


def _retrieval_scope_allows(asset: Any, needs: list[str]) -> bool:
    scope = asset.metadata.get("retrieval_scope")
    if scope is None:
        return True
    if scope != "explicit_product_name_only":
        return False
    names = _metadata_strings(asset.metadata.get("product_names"))
    query = re.sub(r"\s+", "", "\n".join(needs).casefold())
    return bool(names) and any(
        re.sub(r"\s+", "", name.casefold()) in query for name in names
    )


def _distinct_terms(
    terms: tuple[str, ...], searchable: str, *, limit: int = 6, min_length: int = 3
) -> list[str]:
    matched: list[str] = []
    for term in terms:
        if len(term) < min_length or term not in searchable:
            continue
        if any(term in existing or existing in term for existing in matched):
            continue
        matched.append(term)
        if len(matched) >= limit:
            break
    return matched


def _knowledge_score(asset: Any, needs: list[str]) -> tuple[int, list[str]]:
    if not _retrieval_scope_allows(asset, needs):
        return 0, []
    title = asset.title.casefold()
    body = asset.body.casefold()
    metadata = _metadata_values(asset)
    metadata_text = "\n".join(value for _, value in metadata).casefold()
    score = 0
    evidence: list[str] = []
    for need in needs:
        terms = _query_terms(need)
        if not terms:
            continue
        title_matches = _distinct_terms(terms, title, min_length=2)
        metadata_matches = _distinct_terms(terms, metadata_text, min_length=2)
        body_matches = _distinct_terms(terms, body)
        if not title_matches and not metadata_matches:
            continue
        score += 8 * len(title_matches)
        score += 5 * len(metadata_matches)
        score += min(6, len(body_matches))
        for term in (*title_matches, *metadata_matches, *body_matches):
            if term not in evidence:
                evidence.append(term)
    return score, evidence


def search_knowledge_assets(
    knowledge_root: str | Path | FeishuRoot, *, needs: list[str]
) -> list[dict[str, Any]]:
    """Return at most five relevant local excerpts from one authorized 03 root."""

    if not isinstance(needs, list) or any(
        not isinstance(item, str) or not item.strip() for item in needs
    ):
        raise SlimRuntimeError(
            "SLIM_CONTEXT_INPUT_INVALID",
            "vault_search",
            detail="business_context_needs must be a string list",
            workflow_stage="正在准备客户内容资料",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    if not needs:
        return []
    root = safe_knowledge_root(knowledge_root)
    ranked: list[tuple[int, str, Any, list[str]]] = []
    for relative in _candidate_refs(root, '\n'.join(needs)):
        try:
            asset = read_knowledge_asset(root, relative)
        except SlimRuntimeError as exc:
            if (isinstance(root, FeishuRoot) and exc.component != 'vault_reader') or "symlink" in exc.detail.casefold():
                raise
            continue
        if _is_index_page_title(asset.title):
            continue
        score, evidence = _knowledge_score(asset, needs)
        if score:
            ranked.append((score, relative, asset, evidence))
    output: list[dict[str, Any]] = []
    for _, _, asset, evidence in sorted(ranked, key=lambda item: (-item[0], item[1]))[:5]:
        paragraphs = [
            part.strip()
            for part in re.split(r"\n\s*\n", asset.body)
            if part.strip()
        ]
        selected = [
            part
            for part in paragraphs
            if any(term.casefold() in part.casefold() for term in evidence)
        ] or paragraphs[:2]
        output.append(
            {
                "relative_path": asset.relative_path,
                "page_sha256": asset.page_sha256,
                "title": asset.title,
                "excerpt": "\n\n".join(selected)[:1600].rstrip(),
                "relevance_evidence": [f"业务需求线索：{term}" for term in evidence],
            }
        )
    return output


def _candidate_refs(root: Path | FeishuRoot, query: str):
    if isinstance(root, FeishuRoot):
        # Fully validate the bounded metadata enumeration before reading bodies.
        # No title evidence means no candidate: never fall back to a body scan.
        terms = _query_terms(query)
        ranked = []
        for document in iter_documents(root):
            title = re.sub(r'\s+', '', (document.title or '').casefold())
            score = sum(len(term) for term in terms if term in title)
            if score:
                ranked.append((score, document.token))
        for _, token in sorted(ranked, key=lambda item: (-item[0], item[1]))[:REMOTE_BODY_CANDIDATE_LIMIT]:
            yield 'feishu:' + token
    else:
        for path in sorted(root.rglob('*.md')):
            yield path.relative_to(root).as_posix()
