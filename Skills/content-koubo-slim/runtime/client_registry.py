"""Resolve a client id without carrying client rules in the local Registry."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .content_source import (
    CONTRACT_VERSION,
    WORKFLOW,
    default_common_registry_path,
    select_common_binding,
    validate_common_registry,
)
from .error_model import SlimRuntimeError


CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
REGISTRY_FIELDS = {"vault_root", "manifest_relative_path"}


@dataclass(frozen=True)
class ClientLocation:
    client_id: str
    vault_root: Path
    manifest_path: Path
    binding_id: str | None = None
    knowledge_base_id: str | None = None
    backend_type: str = "obsidian"
    profile_index_path: Path | None = None
    default_profile_id: str | None = None
    registry_sha256: str | None = None
    common_contract: bool = False


def default_config_root() -> Path:
    """Return the current Codex host's persistent Content 口播 Slim config root."""
    configured = os.environ.get("CONTENT_KOUBO_HOME") or os.environ.get("CODEX_HOME")
    host_root = Path(configured).expanduser() if configured else Path.home() / ".codex"
    return host_root / ".content-koubo-slim"


def default_registry_path() -> Path:
    return default_config_root() / "client-registry.json"


def default_runs_root() -> Path:
    return default_config_root() / "runs"


def _safe_relative_path(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("path must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if not path.parts or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("path must stay below the configured root")
    return path


def load_registry(path: str | Path) -> dict[str, Any]:
    try:
        raw = Path(path).read_bytes()
        data = json.loads(raw.decode("utf-8"))
        if isinstance(data, dict) and data.get("contract_version") == CONTRACT_VERSION:
            validated = validate_common_registry(data)
            validated["_registry_sha256"] = __import__("hashlib").sha256(raw).hexdigest()
            return validated
        if not isinstance(data, dict) or set(data) != {"registry_version", "clients"}:
            raise ValueError("unexpected registry fields")
        if (
            data["registry_version"] != "2.0"
            or not isinstance(data["clients"], dict)
            or not data["clients"]
        ):
            raise ValueError("unsupported registry version or clients value")
        for client_id, record in data["clients"].items():
            if not isinstance(client_id, str) or not CLIENT_ID_PATTERN.fullmatch(client_id):
                raise ValueError("invalid client id")
            if not isinstance(record, dict) or set(record) != REGISTRY_FIELDS:
                raise ValueError("registry records may only locate vault and manifest")
            vault_root = Path(record["vault_root"])
            if not vault_root.is_absolute():
                raise ValueError("vault_root must be supplied as an absolute local path")
            _safe_relative_path(record["manifest_relative_path"])
        return data
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SlimRuntimeError(
            "SLIM_REGISTRY_NOT_READABLE", "client_registry", detail=str(exc)
        ) from exc


def load_effective_registry(path: str | Path | None = None) -> dict[str, Any]:
    """Prefer the common Registry, with an exact legacy conflict guard."""

    if path is not None:
        return load_registry(path)
    common_path = default_common_registry_path()
    legacy_path = default_registry_path()
    common = load_registry(common_path) if common_path.exists() else None
    legacy = load_registry(legacy_path) if legacy_path.exists() else None
    if common is not None and legacy is not None:
        for binding in common["bindings"].values():
            if binding.get("backend") != "obsidian":
                continue
            legacy_record = legacy["clients"].get(binding.get("client_id"))
            if legacy_record is None:
                continue
            common_root = binding.get("locator", {}).get("vault_root")
            if common_root != legacy_record.get("vault_root"):
                raise SlimRuntimeError(
                    "SLIM_REGISTRY_NOT_READABLE",
                    "client_registry",
                    detail="common and legacy registries bind the same client to different vaults",
                    recovery_action="通用与旧口播客户索引指向不一致，请先人工确认正确知识库。",
                )
        return common
    if common is not None:
        return common
    if legacy is not None:
        return legacy
    raise SlimRuntimeError(
        "SLIM_CLIENT_NOT_CONFIGURED",
        "client_registry",
        detail="neither common nor legacy Registry exists",
        recovery_action="请先运行口播的 configure，对明确的 Obsidian 知识库做零写入预览并确认。",
    )


def select_client_id(
    registry: dict[str, Any], requested_client_id: str | None = None,
    *,
    requested_binding_id: str | None = None,
) -> str:
    """Use an explicit client or the only configured client; never guess."""
    if registry.get("contract_version") == CONTRACT_VERSION:
        return select_common_binding(
            registry,
            requested_binding_id=requested_binding_id,
            requested_client_id=requested_client_id,
        )
    clients = registry.get("clients") if isinstance(registry, dict) else None
    if not isinstance(clients, dict) or not clients:
        raise SlimRuntimeError(
            "SLIM_CLIENT_NOT_CONFIGURED",
            "client_registry",
            detail="registry has no configured clients",
        )
    if requested_client_id is not None:
        if (
            not isinstance(requested_client_id, str)
            or not CLIENT_ID_PATTERN.fullmatch(requested_client_id)
            or requested_client_id not in clients
        ):
            raise SlimRuntimeError(
                "SLIM_CLIENT_NOT_CONFIGURED",
                "client_registry",
                detail="requested client is not present in the registry",
            )
        return requested_client_id
    if len(clients) == 1:
        return next(iter(clients))
    raise SlimRuntimeError(
        "SLIM_CLIENT_NOT_CONFIGURED",
        "client_registry",
        detail="multiple clients are configured and none was selected",
        recovery_action="当前有多个客户配置，请明确选择一个客户后重试。",
    )


def resolve_client(registry: dict[str, Any], client_id: str) -> ClientLocation:
    if registry.get("contract_version") == CONTRACT_VERSION:
        try:
            binding = registry["bindings"][client_id]
            backend = binding["backend"]
            if backend != "obsidian":
                raise SlimRuntimeError(
                    "SLIM_BACKEND_UNSUPPORTED",
                    "client_registry",
                    detail="Feishu binding cannot be read by Content Koubo Slim",
                )
            vault_root = Path(binding["locator"]["vault_root"])
            if not vault_root.is_dir() or vault_root.is_symlink():
                raise ValueError("vault root is missing or is a symlink")
            root_resolved = vault_root.resolve(strict=True)
            manifest_relative = _safe_relative_path(binding["manifest_ref"])
            profile_relative = _safe_relative_path(binding["profile_index_ref"])
            manifest_path = root_resolved.joinpath(*manifest_relative.parts).resolve(strict=True)
            profile_path = root_resolved.joinpath(*profile_relative.parts).resolve(strict=True)
            manifest_path.relative_to(root_resolved)
            profile_path.relative_to(root_resolved)
            if manifest_path.is_symlink() or not manifest_path.is_file() or profile_path.is_symlink() or not profile_path.is_file():
                raise ValueError("common Manifest or Profile index is missing")
            default = binding.get("workflow_defaults", {}).get(WORKFLOW, {})
            return ClientLocation(
                client_id=binding["client_id"],
                vault_root=root_resolved,
                manifest_path=manifest_path,
                binding_id=binding["binding_id"],
                knowledge_base_id=binding["knowledge_base_id"],
                backend_type=backend,
                profile_index_path=profile_path,
                default_profile_id=default.get("profile_id") if isinstance(default, dict) else None,
                registry_sha256=registry.get("_registry_sha256"),
                common_contract=True,
            )
        except SlimRuntimeError:
            raise
        except (KeyError, OSError, TypeError, ValueError) as exc:
            raise SlimRuntimeError("SLIM_CLIENT_NOT_CONFIGURED", "client_registry", detail=str(exc)) from exc
    try:
        record = registry["clients"][client_id]
        vault_root = Path(record["vault_root"])
        if not vault_root.is_dir() or vault_root.is_symlink():
            raise ValueError("vault root is missing or is a symlink")
        root_resolved = vault_root.resolve(strict=True)
        relative = _safe_relative_path(record["manifest_relative_path"])
        manifest_path = root_resolved.joinpath(*relative.parts)
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("manifest is missing or is a symlink")
        manifest_resolved = manifest_path.resolve(strict=True)
        manifest_resolved.relative_to(root_resolved)
        return ClientLocation(client_id, root_resolved, manifest_resolved)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise SlimRuntimeError(
            "SLIM_CLIENT_NOT_CONFIGURED", "client_registry", detail=str(exc)
        ) from exc
