"""Resolve a client id without carrying client rules in the local Registry."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .error_model import SlimRuntimeError


CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
REGISTRY_FIELDS = {"vault_root", "manifest_relative_path"}


@dataclass(frozen=True)
class ClientLocation:
    client_id: str
    vault_root: Path
    manifest_path: Path


def default_config_root() -> Path:
    """Return the current Codex host's persistent Content Slim config root."""
    configured = os.environ.get("CODEX_HOME")
    host_root = Path(configured).expanduser() if configured else Path.home() / ".codex"
    return host_root / ".content-v2-slim"


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
        data = json.loads(Path(path).read_text(encoding="utf-8"))
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


def select_client_id(
    registry: dict[str, Any], requested_client_id: str | None = None
) -> str:
    """Use an explicit client or the only configured client; never guess."""
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
