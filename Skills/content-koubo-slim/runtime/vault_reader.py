"""Read one Markdown method asset strictly below an authorized method_root."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .error_model import SlimRuntimeError


ASSET_ROLE_BY_TYPE = {
    "benchmark_deconstruction": "peer_content_asset",
    "peer_content_asset": "peer_content_asset",
    "oral_structure": "oral_method_asset",
    "oral_method_asset": "oral_method_asset",
    "content_method_asset": "oral_method_asset",
}
AUDIENCE_SCOPES = {"consumer", "internal_sales_training", "both"}


@dataclass(frozen=True)
class MethodAsset:
    asset_id: str
    asset_role: str
    relative_path: str
    page_sha256: str
    audience_scope: str
    title: str
    keywords: tuple[str, ...]
    use_when: tuple[str, ...]
    body: str


@dataclass(frozen=True)
class KnowledgeAsset:
    relative_path: str
    page_sha256: str
    title: str
    body: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ProfileAsset:
    relative_path: str
    page_sha256: str
    title: str
    body: str
    profile_id: str | None = None
    display_name: str | None = None


def safe_method_root(value: str | Path) -> Path:
    try:
        lexical = Path(os.path.abspath(Path(value)))
        if lexical.is_symlink() or not lexical.is_dir():
            raise ValueError("method_root must be an existing real directory")
        return lexical.resolve(strict=True)
    except (OSError, TypeError, ValueError) as exc:
        raise SlimRuntimeError(
            "SLIM_METHOD_ROOT_INVALID",
            "vault_reader",
            detail=str(exc),
            workflow_stage="正在拆解并匹配客户内容方向",
        ) from exc


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.suffix.casefold() != ".md"
    ):
        raise ValueError("method asset must be a Markdown path below method_root")
    return path


def _split_frontmatter(text: str) -> tuple[list[str], str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("---\n"):
        raise ValueError("method asset has no frontmatter")
    end = normalized.find("\n---\n", 4)
    if end < 0:
        raise ValueError("method asset frontmatter is not closed")
    return normalized[4:end].splitlines(), normalized[end + 5 :]


def _scalar(value: str) -> Any:
    stripped = value.strip()
    if not stripped:
        return None
    if stripped in {"true", "false", "null"}:
        return {"true": True, "false": False, "null": None}[stripped]
    if stripped[0] in {'"', "'", "[", "{"}:
        candidate = stripped
        if stripped.startswith("'") and stripped.endswith("'"):
            return stripped[1:-1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    return stripped


def _frontmatter(lines: list[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    active_list: str | None = None
    for raw_line in lines:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        list_match = re.fullmatch(r"\s*-\s+(.+?)\s*", raw_line)
        if list_match and active_list is not None:
            value = _scalar(list_match.group(1))
            if value is None or (isinstance(value, str) and not value.strip()):
                raise ValueError("frontmatter list item must be non-empty")
            metadata[active_list].append(value.strip() if isinstance(value, str) else value)
            continue
        key_match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_-]*):\s*(.*?)\s*", raw_line)
        if not key_match:
            active_list = None
            continue
        key, raw_value = key_match.groups()
        if key in metadata:
            raise ValueError(f"duplicate frontmatter key: {key}")
        value = _scalar(raw_value)
        if value is None:
            metadata[key] = []
            active_list = key
        else:
            metadata[key] = value
            active_list = None
    return metadata


def _string_list(value: Any, field: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise ValueError(f"{field} must be a non-empty string list")
    normalized = tuple(item.strip() for item in value)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field} must not contain duplicates")
    return normalized


def read_method_asset(
    method_root: str | Path,
    relative_path: str,
    *,
    expected_sha256: str | None = None,
) -> MethodAsset:
    root = safe_method_root(method_root)
    try:
        relative = _safe_relative_path(relative_path)
        lexical = root.joinpath(*relative.parts)
        current = root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ValueError("method asset path contains a symlink")
        if not lexical.is_file() or lexical.is_symlink():
            raise ValueError("method asset must be a regular file")
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(root)
        raw = resolved.read_bytes()
        page_sha256 = hashlib.sha256(raw).hexdigest()
        if expected_sha256 is not None and page_sha256 != expected_sha256:
            raise ValueError("method asset changed after selection")
        text = raw.decode("utf-8")
        frontmatter_lines, body = _split_frontmatter(text)
        metadata = _frontmatter(frontmatter_lines)
        asset_id = metadata.get("asset_id")
        asset_type = metadata.get("type")
        audience_scope = metadata.get("audience_scope")
        if not isinstance(asset_id, str) or not asset_id.strip():
            raise ValueError("method asset_id is missing")
        if asset_type not in ASSET_ROLE_BY_TYPE:
            raise ValueError("method asset type is not selectable")
        if asset_type == "content_method_asset":
            workflows = _string_list(metadata.get("applicable_workflows"), "applicable_workflows")
            if "content-koubo-slim" not in workflows:
                raise ValueError("method asset is not applicable to content-koubo-slim")
        if metadata.get("status") != "active":
            raise ValueError("method asset is not active")
        if audience_scope not in AUDIENCE_SCOPES:
            raise ValueError("method asset audience_scope is invalid")
        keywords = _string_list(metadata.get("keywords"), "keywords")
        use_when = _string_list(metadata.get("use_when"), "use_when")
        title_match = re.search(r"(?m)^#\s+(.+?)\s*$", body)
        if not title_match:
            raise ValueError("method asset has no H1 title")
        return MethodAsset(
            asset_id=asset_id.strip(),
            asset_role=ASSET_ROLE_BY_TYPE[asset_type],
            relative_path=relative.as_posix(),
            page_sha256=page_sha256,
            audience_scope=audience_scope,
            title=title_match.group(1).strip(),
            keywords=keywords,
            use_when=use_when,
            body=body.strip(),
        )
    except SlimRuntimeError:
        raise
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise SlimRuntimeError(
            "SLIM_METHOD_ASSET_INVALID",
            "vault_reader",
            detail=str(exc),
            workflow_stage="正在拆解并匹配客户内容方向",
        ) from exc


def _safe_authorized_root(
    value: str | Path, *, error_code: str, logical_name: str
) -> Path:
    try:
        lexical = Path(os.path.abspath(Path(value)))
        if lexical.is_symlink() or not lexical.is_dir():
            raise ValueError(f"{logical_name} must be an existing real directory")
        return lexical.resolve(strict=True)
    except (OSError, TypeError, ValueError) as exc:
        raise SlimRuntimeError(
            error_code,
            "vault_reader",
            detail=str(exc),
            workflow_stage="正在准备客户内容资料",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        ) from exc


def safe_knowledge_root(value: str | Path) -> Path:
    return _safe_authorized_root(
        value,
        error_code="SLIM_KNOWLEDGE_ASSET_INVALID",
        logical_name="knowledge_root",
    )


def _read_markdown_below(
    root: Path,
    relative_path: str,
    *,
    error_code: str,
    expected_sha256: str | None = None,
) -> tuple[str, str, str]:
    try:
        relative = _safe_relative_path(relative_path)
        lexical = root.joinpath(*relative.parts)
        current = root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ValueError("asset path contains a symlink")
        if not lexical.is_file() or lexical.is_symlink():
            raise ValueError("asset must be a regular Markdown file")
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(root)
        raw = resolved.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise ValueError("asset changed after selection")
        text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        body = text
        if text.startswith("---\n"):
            _, body = _split_frontmatter(text)
        title_match = re.search(r"(?m)^#\s+(.+?)\s*$", body)
        title = title_match.group(1).strip() if title_match else relative.stem
        if not body.strip():
            raise ValueError("asset body is empty")
        return digest, title, body.strip()
    except SlimRuntimeError:
        raise
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise SlimRuntimeError(
            error_code,
            "vault_reader",
            detail=str(exc),
            workflow_stage="正在准备客户内容资料",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        ) from exc


def read_knowledge_asset(
    knowledge_root: str | Path,
    relative_path: str,
    *,
    expected_sha256: str | None = None,
) -> KnowledgeAsset:
    root = _safe_authorized_root(
        knowledge_root,
        error_code="SLIM_KNOWLEDGE_ASSET_INVALID",
        logical_name="knowledge_root",
    )
    digest, title, body = _read_markdown_below(
        root,
        relative_path,
        error_code="SLIM_KNOWLEDGE_ASSET_INVALID",
        expected_sha256=expected_sha256,
    )
    try:
        raw_bytes = (root / _safe_relative_path(relative_path).as_posix()).read_bytes()
        if hashlib.sha256(raw_bytes).hexdigest() != digest:
            raise ValueError("knowledge asset changed while reading metadata")
        raw = raw_bytes.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        metadata = _frontmatter(_split_frontmatter(raw)[0]) if raw.startswith("---\n") else {}
    except (OSError, UnicodeError, ValueError) as exc:
        raise SlimRuntimeError(
            "SLIM_KNOWLEDGE_ASSET_INVALID",
            "vault_reader",
            detail=str(exc),
            workflow_stage="正在准备客户内容资料",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        ) from exc
    return KnowledgeAsset(
        relative_path=_safe_relative_path(relative_path).as_posix(),
        page_sha256=digest,
        title=title,
        body=body,
        metadata=metadata,
    )


def read_primary_profile(
    profile_root: str | Path, selector: dict[str, Any]
) -> ProfileAsset:
    root = _safe_authorized_root(
        profile_root,
        error_code="SLIM_PROFILE_INVALID",
        logical_name="profile_root",
    )
    matches: list[ProfileAsset] = []
    for candidate in sorted(root.rglob("*.md")):
        relative = candidate.relative_to(root).as_posix()
        try:
            current = root
            for part in PurePosixPath(relative).parts:
                current /= part
                if current.is_symlink():
                    raise ValueError("profile path contains a symlink")
            if not candidate.is_file() or candidate.is_symlink():
                raise ValueError("profile must be a regular Markdown file")
            candidate.resolve(strict=True).relative_to(root)
            raw = candidate.read_bytes()
            text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
            frontmatter_lines, body = _split_frontmatter(text)
            metadata = _frontmatter(frontmatter_lines)
            if any(metadata.get(key) != expected for key, expected in selector.items()):
                continue
            asset = _read_markdown_below(
                root,
                relative,
                error_code="SLIM_PROFILE_INVALID",
            )
            digest, title, normalized_body = asset
            matches.append(
                ProfileAsset(
                    relative_path=relative,
                    page_sha256=digest,
                    title=title,
                    body=normalized_body,
                )
            )
        except SlimRuntimeError as exc:
            if "symlink" in exc.detail.casefold():
                raise
            continue
        except (OSError, UnicodeError, TypeError, ValueError) as exc:
            if "symlink" in str(exc).casefold():
                raise SlimRuntimeError(
                    "SLIM_PROFILE_INVALID",
                    "vault_reader",
                    detail=str(exc),
                    workflow_stage="正在准备客户内容资料",
                    run_exists=True,
                    artifacts_exist=True,
                    artifacts_preserved=True,
                ) from exc
            continue
    if len(matches) != 1:
        raise SlimRuntimeError(
            "SLIM_PROFILE_INVALID",
            "vault_reader",
            detail=f"expected one active primary profile, found {len(matches)}",
            workflow_stage="正在准备客户内容资料",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        )
    return matches[0]


def read_selected_profile(
    profile_root: str | Path, profile_record: dict[str, Any]
) -> ProfileAsset:
    """Read exactly the Profile selected from content-profile-index.json."""

    root = _safe_authorized_root(
        profile_root,
        error_code="SLIM_PROFILE_INVALID",
        logical_name="profile_root",
    )
    try:
        object_ref = profile_record["object_ref"]
        if not isinstance(object_ref, str):
            raise ValueError("Profile object_ref is invalid")
        relative = PurePosixPath(object_ref)
        if relative.parts and relative.parts[0] == root.name:
            relative = PurePosixPath(*relative.parts[1:])
        if not relative.parts:
            raise ValueError("Profile object_ref does not name a file")
        digest, title, body = _read_markdown_below(
            root,
            relative.as_posix(),
            error_code="SLIM_PROFILE_INVALID",
            expected_sha256=profile_record.get("content_sha256"),
        )
        raw = root.joinpath(*relative.parts).read_text(encoding="utf-8")
        metadata = _frontmatter(_split_frontmatter(raw)[0])
        if metadata.get("status") != "active":
            raise ValueError("selected Profile is no longer active")
        profile_id = metadata.get("profile_id")
        if profile_id != profile_record.get("profile_id"):
            raise ValueError("selected Profile identity changed")
        display_name = metadata.get("display_name") or profile_record.get("display_name")
        if display_name != profile_record.get("display_name"):
            raise ValueError("selected Profile display name changed")
        return ProfileAsset(
            relative_path=relative.as_posix(),
            page_sha256=digest,
            title=title,
            body=body,
            profile_id=profile_id,
            display_name=display_name,
        )
    except SlimRuntimeError:
        raise
    except (KeyError, OSError, UnicodeError, TypeError, ValueError) as exc:
        raise SlimRuntimeError(
            "SLIM_PROFILE_INVALID",
            "vault_reader",
            detail=str(exc),
            workflow_stage="正在准备客户内容资料",
            run_exists=True,
            artifacts_exist=True,
            artifacts_preserved=True,
        ) from exc
