"""Validate the generic client manifest and speaker-mode policy."""

from __future__ import annotations

import json
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .client_registry import CLIENT_ID_PATTERN
from .content_source import CONTRACT_VERSION as COMMON_CONTRACT_VERSION, WORKFLOW, validate_common_manifest
from .error_model import SlimRuntimeError


SUPPORTED_SPEAKER_MODES = ("personal_ip", "company_brand", "neutral")
MANIFEST_FIELDS = {
    "contract_version",
    "client_id",
    "asset_roots",
    "default_speaker_mode",
    "allowed_speaker_modes",
    "profile_policy",
    "default_platform",
    "output_template",
}
ASSET_ROOT_FIELDS = {"knowledge", "method", "profile", "output"}


@dataclass(frozen=True)
class ClientManifest:
    client_id: str
    asset_roots: dict[str, str]
    default_speaker_mode: str
    allowed_speaker_modes: tuple[str, ...]
    profile_required_when: tuple[str, ...]
    profile_selector: dict[str, Any]
    default_platform: str
    output_template: str
    knowledge_base_id: str | None = None
    profile_index_ref: str | None = None
    common_contract: bool = False
    manifest_sha256: str | None = None

    def requires_profile(self, speaker_mode: str) -> bool:
        return speaker_mode in self.profile_required_when


def _relative_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"{field} must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if not path.parts or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field} must stay below its configured root")
    return path.as_posix()


def validate_manifest(data: Any, expected_client_id: str | None = None) -> ClientManifest:
    try:
        if isinstance(data, dict) and data.get("contract_version") == COMMON_CONTRACT_VERSION:
            value = validate_common_manifest(data)
            client_id = value["client_id"]
            if expected_client_id is not None and client_id != expected_client_id:
                raise ValueError("registry and manifest client ids differ")
            roots = value["asset_roots"]
            return ClientManifest(
                client_id=client_id,
                asset_roots={
                    "knowledge": roots["knowledge"],
                    "method": roots["content"],
                    "profile": roots["profiles"],
                    "output": roots["output"],
                },
                default_speaker_mode="personal_ip",
                allowed_speaker_modes=SUPPORTED_SPEAKER_MODES,
                profile_required_when=("personal_ip",),
                profile_selector={"status": "active"},
                default_platform="short_video",
                output_template=value["workflow_outputs"][WORKFLOW],
                knowledge_base_id=value["knowledge_base_id"],
                profile_index_ref=value["profile_index_ref"],
                common_contract=True,
            )
        if not isinstance(data, dict) or set(data) != MANIFEST_FIELDS:
            raise ValueError("unexpected manifest fields")
        if data["contract_version"] != "2.0":
            raise ValueError("unsupported manifest version")
        client_id = data["client_id"]
        if not isinstance(client_id, str) or not CLIENT_ID_PATTERN.fullmatch(client_id):
            raise ValueError("invalid client id")
        if expected_client_id is not None and client_id != expected_client_id:
            raise ValueError("registry and manifest client ids differ")

        roots = data["asset_roots"]
        if not isinstance(roots, dict) or set(roots) != ASSET_ROOT_FIELDS:
            raise ValueError("asset_roots must contain the four logical roots")
        normalized_roots = {key: _relative_path(value, key) for key, value in roots.items()}
        if len(set(normalized_roots.values())) != len(normalized_roots):
            raise ValueError("logical asset roots must be distinct")

        modes = data["allowed_speaker_modes"]
        if not isinstance(modes, list) or not modes or len(set(modes)) != len(modes):
            raise ValueError("allowed_speaker_modes must be a unique non-empty list")
        if any(mode not in SUPPORTED_SPEAKER_MODES for mode in modes):
            raise ValueError("unsupported speaker mode")
        default_mode = data["default_speaker_mode"]
        if default_mode not in modes:
            raise ValueError("default speaker mode is not allowed")

        policy = data["profile_policy"]
        if not isinstance(policy, dict) or set(policy) != {"required_when", "selector"}:
            raise ValueError("invalid profile policy")
        required_when = policy["required_when"]
        selector = policy["selector"]
        if required_when != ["personal_ip"]:
            raise ValueError("only personal_ip may require a profile")
        if not isinstance(selector, dict) or set(selector) != {"status", "is_primary"}:
            raise ValueError("profile selector must identify one active primary profile")
        if selector["status"] != "active" or selector["is_primary"] is not True:
            raise ValueError("profile selector must identify one active primary profile")

        platform = data["default_platform"]
        if not isinstance(platform, str) or not platform.strip():
            raise ValueError("default_platform must be a non-empty string")
        output_template = _relative_path(data["output_template"], "output_template")

        return ClientManifest(
            client_id=client_id,
            asset_roots=normalized_roots,
            default_speaker_mode=default_mode,
            allowed_speaker_modes=tuple(modes),
            profile_required_when=tuple(required_when),
            profile_selector=dict(selector),
            default_platform=platform,
            output_template=output_template,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SlimRuntimeError(
            "SLIM_MANIFEST_INVALID", "client_manifest", detail=str(exc)
        ) from exc


def load_manifest(path: str | Path, expected_client_id: str | None = None) -> ClientManifest:
    try:
        raw = Path(path).read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SlimRuntimeError(
            "SLIM_MANIFEST_INVALID", "client_manifest", detail=str(exc)
        ) from exc
    manifest = validate_manifest(data, expected_client_id)
    return ClientManifest(
        **{**manifest.__dict__, "manifest_sha256": hashlib.sha256(raw).hexdigest()}
    )


def resolve_speaker_mode(requested: str | None, manifest: ClientManifest) -> str:
    mode = requested or manifest.default_speaker_mode
    if mode not in manifest.allowed_speaker_modes:
        raise SlimRuntimeError(
            "SLIM_SPEAKER_MODE_INVALID", "client_manifest", detail=f"mode={mode!r}"
        )
    return mode


def resolve_asset_root(
    vault_root: str | Path, manifest: ClientManifest, logical_name: str
) -> Path:
    """Resolve one Manifest-authorized logical root without following symlinks."""

    try:
        if logical_name not in ASSET_ROOT_FIELDS:
            raise ValueError("unknown logical asset root")
        root = Path(vault_root)
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise ValueError("vault root must be an existing real directory")
        root_resolved = root.resolve(strict=True)
        relative = PurePosixPath(manifest.asset_roots[logical_name])
        current = root_resolved
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ValueError("asset root path contains a symlink")
        lexical = Path(os.path.abspath(current))
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(root_resolved)
        if not resolved.is_dir() or resolved.is_symlink():
            raise ValueError("asset root must be an existing real directory")
        return resolved
    except (KeyError, OSError, TypeError, ValueError) as exc:
        error_code = {
            "method": "SLIM_METHOD_ROOT_INVALID",
            "knowledge": "SLIM_KNOWLEDGE_ASSET_INVALID",
            "profile": "SLIM_PROFILE_INVALID",
            "output": "SLIM_MANIFEST_INVALID",
        }.get(logical_name, "SLIM_MANIFEST_INVALID")
        raise SlimRuntimeError(
            error_code,
            "client_manifest",
            detail=str(exc),
            workflow_stage=(
                "正在拆解并匹配客户内容方向"
                if logical_name == "method"
                else "正在准备客户内容资料"
            ),
        ) from exc


def build_migration_candidate(
    v1_config: dict[str, Any], *, default_speaker_mode: str
) -> dict[str, Any]:
    """Project a legacy client config into the smaller V2 manifest contract."""

    try:
        roots = v1_config["asset_roots"]
        output_root = _relative_path(v1_config["output_root"], "output_root")
        save_template = _relative_path(
            v1_config["save_directory_template"], "save_directory_template"
        )
        prefix = f"{output_root}/"
        if not save_template.startswith(prefix):
            raise ValueError("save template is outside output_root")
        relative_template = save_template[len(prefix) :].replace(
            "{profile_display_name}", "{profile_or_brand}"
        )
        candidate = {
            "contract_version": "2.0",
            "client_id": v1_config["client_id"],
            "asset_roots": {
                "knowledge": roots["knowledge"],
                "method": roots["method"],
                "profile": roots["profile"],
                "output": output_root,
            },
            "default_speaker_mode": default_speaker_mode,
            "allowed_speaker_modes": list(SUPPORTED_SPEAKER_MODES),
            "profile_policy": {
                "required_when": ["personal_ip"],
                "selector": {"status": "active", "is_primary": True},
            },
            "default_platform": v1_config["default_platform"],
            "output_template": relative_template,
        }
        validate_manifest(candidate, expected_client_id=candidate["client_id"])
        return candidate
    except SlimRuntimeError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise SlimRuntimeError(
            "SLIM_MANIFEST_INVALID", "client_manifest", detail=str(exc)
        ) from exc
