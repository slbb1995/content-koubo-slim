"""Return a small set of relevant 04 assets from one authorized method_root."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .error_model import SlimRuntimeError
from .vault_reader import (
    MethodAsset,
    read_knowledge_asset,
    read_method_asset,
    safe_knowledge_root,
    safe_method_root,
)


ROLE_LIMITS = {"peer_content_asset": 3, "oral_method_asset": 2}
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
    method_root: str | Path,
    *,
    query: str,
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
    for candidate_path in sorted(root.rglob("*.md")):
        relative = candidate_path.relative_to(root).as_posix()
        try:
            asset = read_method_asset(root, relative)
        except SlimRuntimeError as exc:
            if "symlink" in exc.detail.casefold():
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
                    "relative_path": asset.relative_path,
                    "page_sha256": asset.page_sha256,
                    "audience_scope": asset.audience_scope,
                    "excerpt": _excerpt(asset, terms),
                    "relevance_evidence": evidence,
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
    knowledge_root: str | Path, *, needs: list[str]
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
    for candidate_path in sorted(root.rglob("*.md")):
        relative = candidate_path.relative_to(root).as_posix()
        try:
            asset = read_knowledge_asset(root, relative)
        except SlimRuntimeError as exc:
            if "symlink" in exc.detail.casefold():
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
