"""Create or reuse one explicit local Content Slim binding safely."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Any

from .client_manifest import SUPPORTED_SPEAKER_MODES, validate_manifest
from .client_registry import CLIENT_ID_PATTERN, load_registry
from .vault_reader import (
    ASSET_ROLE_BY_TYPE,
    AUDIENCE_SCOPES,
    _frontmatter,
    _string_list,
)


ZSK_ASSET_ROOTS = {
    "knowledge": "03-业务知识库",
    "method": "04-内容方法库",
    "profile": "05-IP-Profile",
    "output": "07-生产与反馈",
}
ZSK_MANIFEST_RELATIVE_PATH = (
    "06-Agent与Workflow/content-v2-client-manifest.json"
)
DEFAULT_OUTPUT_TEMPLATE = "content-slim/{profile_or_brand}/weekly"
MAX_FRONTMATTER_BYTES = 64 * 1024


class BindingSetupError(ValueError):
    """Stop before changing a binding when any path or contract is unclear."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class BindingPlan:
    registry_path: Path
    runs_root: Path
    vault_root: Path
    manifest_path: Path
    manifest_relative_path: str
    client_id: str
    speaker_mode: str
    registry_action: str
    manifest_action: str
    runs_action: str
    method_asset_count: int
    primary_profile_count: int

    @property
    def needs_write(self) -> bool:
        return any(
            action == "create"
            for action in (
                self.registry_action,
                self.manifest_action,
                self.runs_action,
            )
        )


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise BindingSetupError(
            "path_unreadable", f"无法检查路径：{path}"
        ) from exc


def _check_existing_chain(path: Path, label: str) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        info = _lstat(current)
        if info is None:
            break
        if stat.S_ISLNK(info.st_mode):
            raise BindingSetupError(
                "symlink_rejected", f"{label}路径包含软链接：{current}"
            )
        if current != path and not stat.S_ISDIR(info.st_mode):
            raise BindingSetupError(
                "path_conflict", f"{label}路径经过非目录对象：{current}"
            )


def _absolute_path(value: str | Path, label: str) -> Path:
    path = Path(value)
    if (
        not path.is_absolute()
        or ".." in path.parts
        or path == Path(path.anchor)
    ):
        raise BindingSetupError(
            "unsafe_path", f"{label}必须是明确、安全的绝对路径。"
        )
    _check_existing_chain(path, label)
    return path


def _existing_directory(value: str | Path, label: str) -> Path:
    path = _absolute_path(value, label)
    info = _lstat(path)
    if info is None or not stat.S_ISDIR(info.st_mode):
        raise BindingSetupError(
            "directory_missing", f"{label}不存在或不是目录：{path}"
        )
    return path


def _file_target(value: str | Path, label: str) -> Path:
    path = _absolute_path(value, label)
    if path.suffix.casefold() != ".json":
        raise BindingSetupError(
            "unsafe_path", f"{label}必须是 JSON 文件路径。"
        )
    _check_existing_chain(path.parent, label)
    info = _lstat(path)
    if info is not None and not stat.S_ISREG(info.st_mode):
        raise BindingSetupError(
            "path_conflict", f"{label}已被非普通文件占用：{path}"
        )
    return path


def _is_below(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _safe_manifest_relative(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.suffix.casefold() != ".json"
        or not path.parts
        or path.parts[0] != "06-Agent与Workflow"
    ):
        raise BindingSetupError(
            "manifest_path_invalid",
            "Manifest 必须是 06-Agent与Workflow 下的安全 JSON 相对路径。",
        )
    return path.as_posix()


def default_client_id(vault_root: str | Path) -> str:
    root = _existing_directory(vault_root, "知识库")
    digest = hashlib.sha256(f"obsidian:{root}".encode("utf-8")).hexdigest()
    return "CLT-" + digest[:14].upper()


def _expected_manifest(client_id: str, speaker_mode: str) -> dict[str, Any]:
    data = {
        "contract_version": "2.0",
        "client_id": client_id,
        "asset_roots": dict(ZSK_ASSET_ROOTS),
        "default_speaker_mode": speaker_mode,
        "allowed_speaker_modes": list(SUPPORTED_SPEAKER_MODES),
        "profile_policy": {
            "required_when": ["personal_ip"],
            "selector": {"status": "active", "is_primary": True},
        },
        "default_platform": "short_video",
        "output_template": DEFAULT_OUTPUT_TEMPLATE,
    }
    validate_manifest(data, expected_client_id=client_id)
    return data


def _expected_registry(
    client_id: str, vault_root: Path, manifest_relative_path: str
) -> dict[str, Any]:
    return {
        "registry_version": "2.0",
        "clients": {
            client_id: {
                "vault_root": str(vault_root),
                "manifest_relative_path": manifest_relative_path,
            }
        },
    }


def _read_json(path: Path, label: str) -> dict[str, Any]:
    info = _lstat(path)
    if info is None or not stat.S_ISREG(info.st_mode):
        raise BindingSetupError(
            "file_missing", f"{label}不存在或不是普通文件：{path}"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BindingSetupError(
            "file_invalid", f"{label}无法安全读取：{path}"
        ) from exc
    if not isinstance(value, dict):
        raise BindingSetupError(
            "file_invalid", f"{label}必须是 JSON 对象：{path}"
        )
    return value


def _json_action(
    path: Path, expected: dict[str, Any], label: str
) -> str:
    if _lstat(path) is None:
        return "create"
    actual = _read_json(path, label)
    if actual != expected:
        raise BindingSetupError(
            "binding_conflict",
            f"{label}已存在但与本次绑定不一致，未覆盖：{path}",
        )
    return "reuse"


def _safe_markdown_candidates(root: Path, label: str) -> list[Path]:
    candidates: list[Path] = []
    try:
        for candidate in sorted(root.rglob("*.md")):
            relative = candidate.relative_to(root)
            current = root
            for part in relative.parts:
                current /= part
                info = _lstat(current)
                if info is None:
                    raise BindingSetupError(
                        "asset_unreadable", f"{label}文件在检查时消失：{current}"
                    )
                if stat.S_ISLNK(info.st_mode):
                    raise BindingSetupError(
                        "symlink_rejected", f"{label}包含软链接：{current}"
                    )
            if not stat.S_ISREG(os.lstat(candidate).st_mode):
                raise BindingSetupError(
                    "asset_invalid", f"{label}包含非普通 Markdown：{candidate}"
                )
            candidates.append(candidate)
    except OSError as exc:
        raise BindingSetupError(
            "asset_unreadable", f"{label}无法安全检查：{root}"
        ) from exc
    return candidates


def _frontmatter_only(path: Path, label: str) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8", newline=None) as handle:
            first = handle.readline()
            if first.rstrip("\n") != "---":
                raise BindingSetupError(
                    "frontmatter_missing", f"{label}缺少 frontmatter：{path}"
                )
            lines: list[str] = []
            total = len(first.encode("utf-8"))
            for line in handle:
                total += len(line.encode("utf-8"))
                if total > MAX_FRONTMATTER_BYTES:
                    raise BindingSetupError(
                        "frontmatter_invalid",
                        f"{label} frontmatter 过大：{path}",
                    )
                normalized = line.rstrip("\n")
                if normalized == "---":
                    return _frontmatter(lines)
                lines.append(normalized)
    except BindingSetupError:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise BindingSetupError(
            "frontmatter_invalid", f"{label} frontmatter 无法读取：{path}"
        ) from exc
    raise BindingSetupError(
        "frontmatter_invalid", f"{label} frontmatter 未闭合：{path}"
    )


def _validate_method_assets(method_root: Path) -> int:
    candidates = _safe_markdown_candidates(method_root, "04 方法卡")
    for candidate in candidates:
        metadata = _frontmatter_only(candidate, "04 方法卡")
        asset_id = metadata.get("asset_id")
        if not isinstance(asset_id, str) or not asset_id.strip():
            raise BindingSetupError(
                "method_contract_invalid",
                f"04 方法卡缺少 asset_id：{candidate}",
            )
        if metadata.get("type") not in ASSET_ROLE_BY_TYPE:
            raise BindingSetupError(
                "method_contract_invalid",
                f"04 方法卡 type 不可选择：{candidate}",
            )
        if metadata.get("status") != "active":
            raise BindingSetupError(
                "method_contract_invalid",
                f"04 方法卡不是 active：{candidate}",
            )
        if metadata.get("audience_scope") not in AUDIENCE_SCOPES:
            raise BindingSetupError(
                "method_contract_invalid",
                f"04 方法卡 audience_scope 无效：{candidate}",
            )
        try:
            _string_list(metadata.get("keywords"), "keywords")
            _string_list(metadata.get("use_when"), "use_when")
        except ValueError as exc:
            raise BindingSetupError(
                "method_contract_invalid",
                f"04 方法卡 keywords 或 use_when 无效：{candidate}",
            ) from exc
    return len(candidates)


def _count_primary_profiles(profile_root: Path) -> int:
    count = 0
    for candidate in _safe_markdown_candidates(profile_root, "05 Profile"):
        try:
            metadata = _frontmatter_only(candidate, "05 Profile")
        except BindingSetupError as exc:
            if exc.code in {"frontmatter_missing", "frontmatter_invalid"}:
                continue
            raise
        if (
            metadata.get("status") == "active"
            and metadata.get("is_primary") is True
        ):
            count += 1
    return count


def plan_zsk_binding(
    *,
    registry_path: str | Path,
    runs_root: str | Path,
    vault_root: str | Path,
    speaker_mode: str = "neutral",
    client_id: str | None = None,
    manifest_relative_path: str = ZSK_MANIFEST_RELATIVE_PATH,
) -> BindingPlan:
    vault = _existing_directory(vault_root, "知识库")
    registry = _file_target(registry_path, "Registry")
    runs = _absolute_path(runs_root, "Runs 目录")
    runs_info = _lstat(runs)
    if runs_info is not None and not stat.S_ISDIR(runs_info.st_mode):
        raise BindingSetupError(
            "path_conflict", f"Runs 路径已被非目录对象占用：{runs}"
        )
    if _is_below(registry, vault) or _is_below(runs, vault):
        raise BindingSetupError(
            "binding_conflict",
            "Registry 和 Runs 必须保存在知识库外，不能写入客户资料目录。",
        )

    if speaker_mode not in SUPPORTED_SPEAKER_MODES:
        raise BindingSetupError(
            "speaker_mode_invalid", "讲述者模式不受 Content Slim 支持。"
        )
    resolved_client_id = client_id or default_client_id(vault)
    if not CLIENT_ID_PATTERN.fullmatch(resolved_client_id):
        raise BindingSetupError(
            "client_id_invalid", "client_id 不符合 Content Slim 合同。"
        )

    relative_manifest = _safe_manifest_relative(manifest_relative_path)
    manifest = vault.joinpath(*PurePosixPath(relative_manifest).parts)
    _check_existing_chain(manifest, "Manifest")
    manifest_parent = _existing_directory(manifest.parent, "06 配置目录")

    roots = {
        key: _existing_directory(vault / relative, f"{key} 授权目录")
        for key, relative in ZSK_ASSET_ROOTS.items()
    }
    if manifest_parent != vault / "06-Agent与Workflow":
        raise BindingSetupError(
            "manifest_path_invalid", "Manifest 必须位于标准 06 配置目录。"
        )

    method_count = _validate_method_assets(roots["method"])
    primary_count = _count_primary_profiles(roots["profile"])
    if speaker_mode == "personal_ip" and primary_count != 1:
        raise BindingSetupError(
            "profile_contract_invalid",
            "personal_ip 模式必须且只能有一份 active primary Profile。",
        )

    expected_manifest = _expected_manifest(
        resolved_client_id, speaker_mode
    )
    expected_registry = _expected_registry(
        resolved_client_id, vault, relative_manifest
    )
    manifest_action = _json_action(
        manifest, expected_manifest, "Manifest"
    )
    registry_action = _json_action(
        registry, expected_registry, "Registry"
    )

    return BindingPlan(
        registry_path=registry,
        runs_root=runs,
        vault_root=vault,
        manifest_path=manifest,
        manifest_relative_path=relative_manifest,
        client_id=resolved_client_id,
        speaker_mode=speaker_mode,
        registry_action=registry_action,
        manifest_action=manifest_action,
        runs_action="reuse" if runs_info is not None else "create",
        method_asset_count=method_count,
        primary_profile_count=primary_count,
    )


def _ensure_directory(path: Path, created: list[Path]) -> None:
    info = _lstat(path)
    if info is not None:
        if not stat.S_ISDIR(info.st_mode):
            raise BindingSetupError(
                "path_conflict", f"目标不是目录：{path}"
            )
        return
    missing: list[Path] = []
    current = path
    while _lstat(current) is None:
        missing.append(current)
        if current.parent == current:
            raise BindingSetupError(
                "unsafe_path", f"无法确定安全父目录：{path}"
            )
        current = current.parent
    parent_info = _lstat(current)
    if parent_info is None or not stat.S_ISDIR(parent_info.st_mode):
        raise BindingSetupError(
            "path_conflict", f"父路径不是目录：{current}"
        )
    for directory in reversed(missing):
        try:
            os.mkdir(directory, 0o700)
        except OSError as exc:
            raise BindingSetupError(
                "write_failed", f"无法创建目录：{directory}"
            ) from exc
        created.append(directory)


def _write_json_exclusive(
    path: Path, value: dict[str, Any], created_files: list[Path]
) -> None:
    payload = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        created_files.append(path)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if path.read_bytes() != payload:
            raise BindingSetupError(
                "readback_failed", f"写后回读不一致：{path}"
            )
    except BindingSetupError:
        raise
    except OSError as exc:
        raise BindingSetupError(
            "write_failed", f"无法 create-only 写入：{path}"
        ) from exc


def _rollback(
    created_files: list[Path], created_directories: list[Path]
) -> None:
    for path in reversed(created_files):
        try:
            info = _lstat(path)
            if info is not None and stat.S_ISREG(info.st_mode):
                os.unlink(path)
        except (OSError, BindingSetupError):
            pass
    for path in reversed(created_directories):
        try:
            os.rmdir(path)
        except OSError:
            pass


def _response(plan: BindingPlan, *, status: str, reused: bool) -> dict[str, Any]:
    if status == "waiting":
        message = (
            "已完成只读预检，等待你确认这个本地知识库后再创建持久绑定。"
        )
        next_action = (
            "确认预览中的知识库绝对路径，或取消本次绑定。"
        )
        label = "等待你确认知识库绑定"
    else:
        message = (
            "知识库绑定已回读并可复用。"
            if reused
            else "知识库已完成一次持久绑定并通过回读。"
        )
        next_action = "重新打开任务后，可直接使用 content-slim。"
        label = "知识库绑定已完成"
    return {
        "status": status,
        "status_label": label,
        "workflow_stage": "绑定本地知识库",
        "message": message,
        "next_action": next_action,
        "run_exists": False,
        "run_created_now": False,
        "artifacts_exist": False,
        "artifacts_preserved": False,
        "binding": {
            "client_id": plan.client_id,
            "vault_root": str(plan.vault_root),
            "registry_path": str(plan.registry_path),
            "manifest_relative_path": plan.manifest_relative_path,
            "runs_root": str(plan.runs_root),
            "speaker_mode": plan.speaker_mode,
            "registry_action": plan.registry_action,
            "manifest_action": plan.manifest_action,
            "runs_action": plan.runs_action,
            "method_asset_count": plan.method_asset_count,
            "primary_profile_count": plan.primary_profile_count,
        },
    }


def configure_zsk_binding(
    *,
    registry_path: str | Path,
    runs_root: str | Path,
    vault_root: str | Path,
    speaker_mode: str = "neutral",
    client_id: str | None = None,
    manifest_relative_path: str = ZSK_MANIFEST_RELATIVE_PATH,
    confirmed_vault_root: str | Path | None = None,
) -> dict[str, Any]:
    plan = plan_zsk_binding(
        registry_path=registry_path,
        runs_root=runs_root,
        vault_root=vault_root,
        speaker_mode=speaker_mode,
        client_id=client_id,
        manifest_relative_path=manifest_relative_path,
    )
    if not plan.needs_write:
        load_registry(plan.registry_path)
        return _response(plan, status="completed", reused=True)
    if confirmed_vault_root is None:
        return _response(plan, status="waiting", reused=False)
    if str(confirmed_vault_root) != str(plan.vault_root):
        raise BindingSetupError(
            "confirmation_mismatch",
            "确认路径与预检知识库不一致，未写入。",
        )

    expected_manifest = _expected_manifest(
        plan.client_id, plan.speaker_mode
    )
    expected_registry = _expected_registry(
        plan.client_id, plan.vault_root, plan.manifest_relative_path
    )
    created_files: list[Path] = []
    created_directories: list[Path] = []
    try:
        _ensure_directory(plan.registry_path.parent, created_directories)
        _ensure_directory(plan.runs_root, created_directories)
        if plan.manifest_action == "create":
            _write_json_exclusive(
                plan.manifest_path, expected_manifest, created_files
            )
        if plan.registry_action == "create":
            _write_json_exclusive(
                plan.registry_path, expected_registry, created_files
            )
        if _read_json(plan.manifest_path, "Manifest") != expected_manifest:
            raise BindingSetupError(
                "readback_failed", "Manifest 写后回读不一致。"
            )
        if _read_json(plan.registry_path, "Registry") != expected_registry:
            raise BindingSetupError(
                "readback_failed", "Registry 写后回读不一致。"
            )
        load_registry(plan.registry_path)
        validate_manifest(
            _read_json(plan.manifest_path, "Manifest"),
            expected_client_id=plan.client_id,
        )
        if not plan.runs_root.is_dir() or plan.runs_root.is_symlink():
            raise BindingSetupError(
                "readback_failed", "Runs 目录写后回读失败。"
            )
    except Exception:
        _rollback(created_files, created_directories)
        raise
    return _response(plan, status="completed", reused=False)
