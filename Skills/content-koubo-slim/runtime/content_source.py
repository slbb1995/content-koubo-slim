"""Compatible reader/configurator for the ZSK-owned content-source-v1 contract."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .error_model import SlimRuntimeError


CONTRACT_VERSION = "content-source-v1"
WORKFLOW = "content-koubo-slim"
MANIFEST_RELATIVE = "06-Agent与Workflow/content-source-manifest.json"
PROFILE_INDEX_RELATIVE = "06-Agent与Workflow/content-profile-index.json"
PROFILE_ID = re.compile(r"^PRF-[A-F0-9]{16}$")
BINDING_ID = re.compile(r"^BND-[A-F0-9]{16}$")
KNOWLEDGE_BASE_ID = re.compile(r"^KB-[A-F0-9]{16}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CREDENTIAL_KEYS = {"token", "cookie", "password", "access_token", "refresh_token", "secret", "api_key", "apikey", "authorization", "credential", "session"}


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def json_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def stable_id(prefix: str, *values: str) -> str:
    digest = hashlib.sha256("\n".join(value.strip() for value in values).encode()).hexdigest()[:16].upper()
    return f"{prefix}-{digest}"


def default_common_registry_path() -> Path:
    configured = os.environ.get("CODEX_HOME")
    root = Path(configured).expanduser() if configured else Path.home() / ".codex"
    return root / ".content-workflows" / "knowledge-base-registry.json"


def _relative(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"{field} must be a relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field} must stay below the knowledge-base root")
    return path.as_posix()


def _no_credentials(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold().replace("-", "_") in _CREDENTIAL_KEYS:
                raise ValueError("locator must not contain credentials")
            _no_credentials(child)
    elif isinstance(value, list):
        for child in value:
            _no_credentials(child)
    elif isinstance(value, str):
        parsed = urlsplit(value)
        pairs = (*parse_qsl(parsed.query, keep_blank_values=True), *parse_qsl(parsed.fragment, keep_blank_values=True))
        if any(key.casefold().replace("-", "_") in _CREDENTIAL_KEYS for key, _ in pairs):
            raise ValueError("locator URL must not contain credentials")


def _read_json(path: Path, code: str) -> tuple[dict[str, Any], str]:
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError("path is not a regular file")
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON root must be an object")
        return value, hashlib.sha256(raw).hexdigest()
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise SlimRuntimeError(code, "content_source", detail=str(exc)) from exc


def validate_common_registry(value: Any) -> dict[str, Any]:
    try:
        if not isinstance(value, dict) or set(value) != {"contract_version", "bindings", "workflow_defaults", "revision"}:
            raise ValueError("common Registry fields are invalid")
        if value["contract_version"] != CONTRACT_VERSION or not isinstance(value["bindings"], dict):
            raise ValueError("common Registry version or bindings are invalid")
        for binding_id, binding in value["bindings"].items():
            fields = {"binding_id", "client_id", "knowledge_base_id", "backend", "locator", "manifest_ref", "profile_index_ref", "supported_workflows", "workflow_defaults", "status"}
            if not BINDING_ID.fullmatch(str(binding_id)) or not isinstance(binding, dict) or set(binding) != fields or binding.get("binding_id") != binding_id:
                raise ValueError("common Registry binding is invalid")
            if not KNOWLEDGE_BASE_ID.fullmatch(str(binding["knowledge_base_id"])):
                raise ValueError("knowledge_base_id is invalid")
            if binding["backend"] not in {"obsidian", "feishu"} or binding["status"] not in {"active", "disabled"}:
                raise ValueError("binding backend or status is invalid")
            if not isinstance(binding["locator"], dict) or not binding["locator"]:
                raise ValueError("binding locator is invalid")
            _no_credentials(binding["locator"])
            workflows = binding["supported_workflows"]
            if not isinstance(workflows, list) or len(workflows) != len(set(workflows)):
                raise ValueError("binding workflows are invalid")
            defaults = binding["workflow_defaults"]
            if not isinstance(defaults, dict) or set(defaults) - set(workflows):
                raise ValueError("binding workflow defaults are invalid")
            for default in defaults.values():
                if not isinstance(default, dict) or set(default) != {"profile_id", "use_no_ip"}:
                    raise ValueError("binding workflow default entry is invalid")
                if not isinstance(default["use_no_ip"], bool) or default["use_no_ip"] and default["profile_id"] is not None:
                    raise ValueError("binding workflow default IP policy is invalid")
        defaults = value["workflow_defaults"]
        if not isinstance(defaults, dict):
            raise ValueError("workflow defaults are invalid")
        for workflow, binding_id in defaults.items():
            if binding_id not in value["bindings"] or workflow not in value["bindings"][binding_id]["supported_workflows"]:
                raise ValueError("workflow default points to an incompatible binding")
        if not isinstance(value["revision"], int) or value["revision"] < 1:
            raise ValueError("Registry revision is invalid")
        return value
    except (KeyError, TypeError, ValueError) as exc:
        raise SlimRuntimeError("SLIM_REGISTRY_NOT_READABLE", "content_source", detail=str(exc)) from exc


def load_common_registry(path: str | Path) -> tuple[dict[str, Any], str]:
    value, digest = _read_json(Path(path), "SLIM_REGISTRY_NOT_READABLE")
    return validate_common_registry(value), digest


def select_common_binding(
    registry: dict[str, Any], *, requested_binding_id: str | None = None, requested_client_id: str | None = None
) -> str:
    active = {
        key: value
        for key, value in registry["bindings"].items()
        if value.get("status") == "active" and WORKFLOW in value.get("supported_workflows", [])
    }
    if requested_binding_id is not None:
        if requested_binding_id not in active:
            raise SlimRuntimeError("SLIM_CLIENT_NOT_CONFIGURED", "content_source", detail="requested binding is unavailable")
        return requested_binding_id
    if requested_client_id is not None:
        matches = [key for key, value in active.items() if value.get("client_id") == requested_client_id]
        if len(matches) != 1:
            raise SlimRuntimeError("SLIM_CLIENT_NOT_CONFIGURED", "content_source", detail="client must resolve to one compatible binding")
        return matches[0]
    default = registry.get("workflow_defaults", {}).get(WORKFLOW)
    if default in active:
        return default
    if len(active) == 1:
        return next(iter(active))
    raise SlimRuntimeError(
        "SLIM_CLIENT_NOT_CONFIGURED",
        "content_source",
        detail="multiple or zero compatible bindings are available",
        recovery_action="请明确选择一个知识库 binding 后重试。",
    )


def validate_common_manifest(value: Any, *, expected: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        fields = {"contract_version", "knowledge_base_id", "client_id", "knowledge_base_name", "backend", "locator", "asset_roots", "profile_index_ref", "workflow_outputs", "supported_workflows", "revision"}
        if not isinstance(value, dict) or set(value) != fields or value["contract_version"] != CONTRACT_VERSION:
            raise ValueError("common Manifest fields or version are invalid")
        if not KNOWLEDGE_BASE_ID.fullmatch(str(value["knowledge_base_id"])):
            raise ValueError("Manifest knowledge_base_id is invalid")
        if value["backend"] not in {"obsidian", "feishu"} or WORKFLOW not in value["supported_workflows"]:
            raise ValueError("Manifest does not support this workflow")
        _no_credentials(value["locator"])
        roots = value["asset_roots"]
        if not isinstance(roots, dict) or set(roots) != {"knowledge", "content", "profiles", "workflow", "output"}:
            raise ValueError("Manifest roots are invalid")
        if value["backend"] == "obsidian":
            for key, child in roots.items():
                _relative(child, key)
            _relative(value["profile_index_ref"], "profile_index_ref")
        outputs = value["workflow_outputs"]
        if not isinstance(outputs, dict) or WORKFLOW not in outputs:
            raise ValueError("Manifest has no Koubo output template")
        _relative(outputs[WORKFLOW], "workflow output")
        if expected and any(value.get(key) != expected.get(key) for key in ("client_id", "knowledge_base_id", "backend")):
            raise ValueError("Registry and Manifest identities differ")
        return value
    except (KeyError, TypeError, ValueError) as exc:
        raise SlimRuntimeError("SLIM_MANIFEST_INVALID", "content_source", detail=str(exc)) from exc


def validate_profile_index(value: Any, *, knowledge_base_id: str) -> dict[str, Any]:
    try:
        if not isinstance(value, dict) or set(value) != {"contract_version", "knowledge_base_id", "profiles", "revision"}:
            raise ValueError("Profile index fields are invalid")
        if value["contract_version"] != CONTRACT_VERSION or value["knowledge_base_id"] != knowledge_base_id:
            raise ValueError("Profile index belongs to another knowledge base")
        if not isinstance(value["profiles"], list):
            raise ValueError("profiles must be a list")
        active_primary = 0
        names: dict[str, str] = {}
        seen: set[str] = set()
        for item in value["profiles"]:
            fields = {"profile_id", "display_name", "aliases", "object_ref", "status", "is_primary", "content_sha256"}
            if not isinstance(item, dict) or set(item) != fields:
                raise ValueError("Profile entry fields are invalid")
            profile_id = item["profile_id"]
            if not isinstance(profile_id, str) or not PROFILE_ID.fullmatch(profile_id) or profile_id in seen:
                raise ValueError("profile_id is invalid or duplicated")
            seen.add(profile_id)
            if item["status"] not in {"active", "disabled"} or not isinstance(item["is_primary"], bool):
                raise ValueError("Profile status is invalid")
            if not isinstance(item["display_name"], str) or not item["display_name"].strip():
                raise ValueError("Profile display name is invalid")
            if not isinstance(item["aliases"], list) or any(not isinstance(alias, str) or not alias.strip() for alias in item["aliases"]):
                raise ValueError("Profile aliases are invalid")
            if not isinstance(item["object_ref"], str) or not item["object_ref"].strip() or not HEX64.fullmatch(str(item["content_sha256"])):
                raise ValueError("Profile ref or hash is invalid")
            if item["status"] == "active":
                active_primary += int(item["is_primary"])
                for candidate in (item["display_name"], *item["aliases"]):
                    folded = candidate.casefold()
                    if folded in names and names[folded] != profile_id:
                        raise ValueError("active Profile alias is ambiguous")
                    names[folded] = profile_id
        if active_primary > 1:
            raise ValueError("more than one active Profile is primary")
        return value
    except (KeyError, TypeError, ValueError) as exc:
        raise SlimRuntimeError("SLIM_PROFILE_INVALID", "content_source", detail=str(exc)) from exc


def load_profile_index(path: Path, *, knowledge_base_id: str) -> tuple[dict[str, Any], str]:
    value, digest = _read_json(path, "SLIM_PROFILE_INVALID")
    return validate_profile_index(value, knowledge_base_id=knowledge_base_id), digest


def select_profile(index: dict[str, Any], *, requested: str | None, configured_default: str | None) -> dict[str, Any]:
    active = [item for item in index["profiles"] if item["status"] == "active"]
    if requested is not None:
        folded = requested.strip().casefold()
        matches = [item for item in active if folded in {item["profile_id"].casefold(), item["display_name"].casefold(), *(alias.casefold() for alias in item["aliases"])}]
        if len(matches) != 1:
            raise SlimRuntimeError("SLIM_PROFILE_INVALID", "content_source", detail="requested Profile is missing or ambiguous", recovery_action="请从当前知识库明确选择一个 active IP。")
        return matches[0]
    if configured_default is not None:
        matches = [item for item in active if item["profile_id"] == configured_default]
        if len(matches) == 1:
            return matches[0]
        raise SlimRuntimeError("SLIM_PROFILE_INVALID", "content_source", detail="configured default Profile is unavailable")
    primary = [item for item in active if item["is_primary"]]
    if len(primary) == 1:
        return primary[0]
    if len(active) == 1:
        return active[0]
    raise SlimRuntimeError("SLIM_PROFILE_INVALID", "content_source", detail="multiple Profiles require a selection", recovery_action="当前知识库有多个 IP，请明确选择本次使用哪一个。")


def _frontmatter(text: str) -> tuple[dict[str, Any], str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("---\n"):
        raise ValueError("Profile has no frontmatter")
    end = normalized.find("\n---\n", 4)
    if end < 0:
        raise ValueError("Profile frontmatter is not closed")
    values: dict[str, Any] = {}
    for line in normalized[4:end].splitlines():
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_-]*):\s*(.*?)\s*", line)
        if not match:
            continue
        key, raw = match.groups()
        if raw in {"true", "false"}:
            values[key] = raw == "true"
        elif raw.startswith(("[", '"')):
            try:
                values[key] = json.loads(raw)
            except json.JSONDecodeError:
                values[key] = raw
        else:
            values[key] = raw
    return values, normalized[end + 5 :]


def _scan_profiles(vault: Path, client_id: str) -> list[dict[str, Any]]:
    root = vault / "05-IP-Profile"
    profiles: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.md")):
        if path.is_symlink() or not path.is_file():
            raise SlimRuntimeError("SLIM_PROFILE_INVALID", "content_source", detail="Profile path is unsafe")
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        # These are the compatible layout's control/index documents, not people.
        # Do not catch parse errors for arbitrary pages: a damaged Profile must stop.
        support_document = path.name in {"AGENTS.md", "README.md", "00-IP-Profile索引.md"}
        if support_document and not text.replace("\r\n", "\n").startswith("---\n"):
            continue
        metadata, body = _frontmatter(text)
        if support_document and not (metadata.get("profile_id") or metadata.get("type") == "ip_profile" or metadata.get("profile_schema")):
            continue
        title = re.search(r"(?m)^#\s+(.+?)\s*$", body)
        display = metadata.get("display_name") or metadata.get("subject_name") or (title.group(1).removesuffix(" Profile").strip() if title else path.stem)
        profile_id = metadata.get("profile_id") or stable_id("PRF", client_id, str(display).casefold())
        aliases = metadata.get("aliases", [])
        if not isinstance(aliases, list):
            aliases = []
        profiles.append(
            {
                "profile_id": profile_id,
                "display_name": str(display),
                "aliases": aliases,
                "object_ref": path.relative_to(vault).as_posix(),
                "status": metadata.get("status", "active"),
                "is_primary": metadata.get("is_primary") is True,
                "content_sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return profiles


def plan_obsidian_configuration(
    vault_root: str | Path,
    *,
    registry_path: str | Path | None = None,
    client_id: str | None = None,
) -> dict[str, Any]:
    try:
        vault = Path(vault_root)
        if not vault.is_absolute() or vault.is_symlink() or not vault.is_dir():
            raise ValueError("vault root must be an existing absolute directory")
        vault = vault.resolve(strict=True)
        for name in ("03-业务知识库", "04-内容方法库", "05-IP-Profile", "06-Agent与Workflow", "07-生产与反馈"):
            child = vault / name
            if child.is_symlink() or not child.is_dir():
                raise ValueError(f"compatible root is missing: {name}")
        manifest_path = vault / MANIFEST_RELATIVE
        index_path = vault / PROFILE_INDEX_RELATIVE
        if manifest_path.exists():
            manifest, _ = _read_json(manifest_path, "SLIM_MANIFEST_INVALID")
            validate_common_manifest(manifest)
            if manifest["backend"] != "obsidian" or manifest["locator"] != str(vault):
                raise ValueError("existing Manifest belongs to another knowledge base")
            if client_id is not None and client_id != manifest["client_id"]:
                raise ValueError("requested client_id differs from the existing Manifest")
            resolved_client = manifest["client_id"]
            knowledge_base_id = manifest["knowledge_base_id"]
            configured_index = vault / manifest["profile_index_ref"]
            if configured_index != index_path:
                index_path = configured_index
            index, _ = _read_json(index_path, "SLIM_PROFILE_INVALID")
            validate_profile_index(index, knowledge_base_id=knowledge_base_id)
            profiles = index["profiles"]
        else:
            resolved_client = client_id or stable_id("CLT", str(vault))
            knowledge_base_id = stable_id("KB", "obsidian", str(vault))
            profiles = _scan_profiles(vault, resolved_client)
            index = {"contract_version": CONTRACT_VERSION, "knowledge_base_id": knowledge_base_id, "profiles": profiles, "revision": 1}
            validate_profile_index(index, knowledge_base_id=knowledge_base_id)
            manifest = {
                "contract_version": CONTRACT_VERSION,
                "knowledge_base_id": knowledge_base_id,
                "client_id": resolved_client,
                "knowledge_base_name": vault.name,
                "backend": "obsidian",
                "locator": str(vault),
                "asset_roots": {"knowledge": "03-业务知识库", "content": "04-内容方法库", "profiles": "05-IP-Profile", "workflow": "06-Agent与Workflow", "output": "07-生产与反馈"},
                "profile_index_ref": PROFILE_INDEX_RELATIVE,
                "workflow_outputs": {
                    "content-koubo-slim": "content-koubo-slim/{profile_id}/weekly",
                    "content-gzh-slim": "content-gzh-slim/{profile_id}/articles",
                },
                "supported_workflows": ["content-gzh-slim", "content-koubo-slim"],
                "revision": 1,
            }
            validate_common_manifest(manifest)
        registry = Path(registry_path) if registry_path else default_common_registry_path()
        if not registry.is_absolute() or registry == vault or vault in registry.parents:
            raise ValueError("Registry must be an absolute path outside the vault")
        current = {"contract_version": CONTRACT_VERSION, "bindings": {}, "workflow_defaults": {}, "revision": 1}
        if registry.exists():
            current, _ = load_common_registry(registry)
        binding_id = stable_id("BND", resolved_client, knowledge_base_id)
        primary = [item for item in profiles if item["status"] == "active" and item["is_primary"]]
        binding = {
            "binding_id": binding_id,
            "client_id": resolved_client,
            "knowledge_base_id": knowledge_base_id,
            "backend": "obsidian",
            "locator": {"vault_root": str(vault)},
            "manifest_ref": MANIFEST_RELATIVE,
            "profile_index_ref": manifest["profile_index_ref"],
            "supported_workflows": sorted(set(current.get("bindings", {}).get(binding_id, {}).get("supported_workflows", [])) | {WORKFLOW}),
            "workflow_defaults": dict(current.get("bindings", {}).get(binding_id, {}).get("workflow_defaults", {})),
            "status": "active",
        }
        binding["workflow_defaults"][WORKFLOW] = {
            "profile_id": primary[0]["profile_id"] if len(primary) == 1 else None,
            "use_no_ip": False,
        }
        updated = json.loads(json.dumps(current))
        updated["bindings"][binding_id] = binding
        updated["workflow_defaults"].setdefault(WORKFLOW, binding_id)
        if updated != current:
            updated["revision"] = current.get("revision", 0) + 1
        validate_common_registry(updated)
        for path, value in ((manifest_path, manifest), (index_path, index)):
            if path.exists():
                existing, _ = _read_json(path, "SLIM_MANIFEST_INVALID" if path == manifest_path else "SLIM_PROFILE_INVALID")
                if existing != value:
                    raise ValueError(f"existing {path.name} differs; migration will not overwrite it")
        preview = {
            "contract_version": CONTRACT_VERSION,
            "workflow": WORKFLOW,
            "vault_root": str(vault),
            "registry_path": str(registry),
            "manifest_action": "reuse" if manifest_path.exists() else "create",
            "profile_index_action": "reuse" if index_path.exists() else "create",
            "registry_action": "reuse" if updated == current else "merge",
            "binding_id": binding_id,
            "profile_count": len(profiles),
            "wrote": False,
        }
        token = hashlib.sha256(("content-koubo-config\0" + json_sha256({"preview": preview, "manifest": manifest, "index": index, "registry": updated})).encode()).hexdigest()[:24]
        return {"preview": preview, "confirmation": token, "manifest": manifest, "profile_index": index, "registry": updated}
    except SlimRuntimeError:
        raise
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise SlimRuntimeError("SLIM_MANIFEST_INVALID", "content_source", detail=str(exc)) from exc


def apply_obsidian_configuration(
    vault_root: str | Path,
    *,
    confirmation: str,
    registry_path: str | Path | None = None,
    client_id: str | None = None,
) -> dict[str, Any]:
    plan = plan_obsidian_configuration(vault_root, registry_path=registry_path, client_id=client_id)
    if confirmation != plan["confirmation"]:
        raise SlimRuntimeError("SLIM_MANIFEST_INVALID", "content_source", detail="confirmation does not match the current zero-write preview")
    vault = Path(plan["preview"]["vault_root"])
    targets = ((vault / MANIFEST_RELATIVE, plan["manifest"]), (vault / PROFILE_INDEX_RELATIVE, plan["profile_index"]))
    for path, value in targets:
        if path.exists():
            continue
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical(value))
        if path.read_bytes() != _canonical(value):
            raise SlimRuntimeError("SLIM_MANIFEST_INVALID", "content_source", detail=f"{path.name} readback mismatch")
    registry = Path(plan["preview"]["registry_path"])
    registry.parent.mkdir(parents=True, exist_ok=True)
    if registry.parent.is_symlink():
        raise SlimRuntimeError("SLIM_REGISTRY_NOT_READABLE", "content_source", detail="Registry parent is a symlink")
    payload = _canonical(plan["registry"])
    temporary = registry.with_name(f".{registry.name}.{secrets.token_hex(4)}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, registry)
        if registry.read_bytes() != payload:
            raise SlimRuntimeError("SLIM_REGISTRY_NOT_READABLE", "content_source", detail="Registry readback mismatch")
    finally:
        if temporary.exists():
            temporary.unlink()
    return {"status": "configured", **plan["preview"], "wrote": True, "readback": "verified"}
