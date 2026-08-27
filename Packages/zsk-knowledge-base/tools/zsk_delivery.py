#!/usr/bin/env python3
"""ZSK 的最小本地交付器：构建、安装、诊断、升级与回退。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
from typing import Any


PACKAGE_ID = "zsk-knowledge-base"
SKILLS = ("zsk-router", "zsk-ruku", "zsk-zhishi", "zsk-duibiao", "zsk-profile")
SUPPORT = ("shared",)
STATE_DIR = ".zsk-knowledge-base"
STATE_FILE = "state.json"


class DeliveryError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_dir(path: Path, *, exists: bool = True) -> Path:
    if not path.is_absolute() or ".." in path.parts or path == Path(path.anchor):
        raise DeliveryError("路径必须是明确的非根绝对目录")
    if exists:
        try:
            info = os.lstat(path)
        except OSError as exc:
            raise DeliveryError("目录不存在或不可读") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise DeliveryError("目录不能是软链接或非普通目录")
    return path


def _copy_tree(source: Path, target: Path) -> None:
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if "__pycache__" in relative.parts:
            continue
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode):
            raise DeliveryError(f"不允许软链接：{relative}")
        destination = target / relative
        if stat.S_ISDIR(info.st_mode):
            destination.mkdir(parents=True, exist_ok=True)
        elif stat.S_ISREG(info.st_mode):
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
        else:
            raise DeliveryError(f"不允许特殊文件：{relative}")


def _records(root: Path) -> list[dict[str, str]]:
    return [
        {"path": path.relative_to(root).as_posix(), "sha256": _sha(path)}
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file() and "__pycache__" not in path.relative_to(root).parts
    ]


def _manifest(package: Path) -> dict[str, Any]:
    manifest_path = package / "zsk-manifest.json"
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeliveryError("交付包缺少可读 manifest") from exc
    if value.get("package_id") != PACKAGE_ID or value.get("skills") != list(SKILLS) or value.get("support") != list(SUPPORT):
        raise DeliveryError("交付包身份或内容不匹配")
    records = value.get("files")
    if not isinstance(records, list) or not records or _canonical(value) != manifest_path.read_bytes():
        raise DeliveryError("manifest 必须是稳定 JSON")
    if records != _records(package / "Skills"):
        raise DeliveryError("交付包文件哈希不匹配")
    return value


def build(source_root: Path, out: Path, version: str) -> dict[str, Any]:
    _safe_dir(source_root)
    if out.exists():
        raise DeliveryError("交付输出目录必须不存在")
    runtime = source_root / "skills" / "knowledge-base"
    if not runtime.is_dir() or not version.strip():
        raise DeliveryError("运行时目录或版本号无效")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir(mode=0o700)
    skills_root = out / "Skills"
    skills_root.mkdir()
    for name in (*SKILLS, *SUPPORT):
        source = runtime / name
        if not source.is_dir() or (name in SKILLS and not (source / "SKILL.md").is_file()):
            raise DeliveryError(f"运行时缺少：{name}")
        _copy_tree(source, skills_root / name)
    manifest = {
        "schema_version": "zsk-delivery-v1",
        "package_id": PACKAGE_ID,
        "version": version.strip(),
        "skills": list(SKILLS),
        "support": list(SUPPORT),
        "files": _records(skills_root),
        "workbuddy_status": "folder_import_instructions_only",
        "dependencies": {"feishu_cli": "required_only_for_feishu"},
    }
    (out / "zsk-manifest.json").write_bytes(_canonical(manifest))
    return {"status": "built", "package_id": PACKAGE_ID, "version": manifest["version"], "skill_count": len(SKILLS), "file_count": len(manifest["files"])}


def _state_path(host: Path) -> Path:
    return host / STATE_DIR / STATE_FILE


def _load_state(host: Path) -> dict[str, Any] | None:
    path = _state_path(host)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeliveryError("宿主管理状态不可读") from exc
    if value.get("package_id") != PACKAGE_ID or not isinstance(value.get("manifest"), dict) or not isinstance(value.get("history"), list):
        raise DeliveryError("宿主管理状态不属于 ZSK")
    return value


def _write_state(host: Path, state: dict[str, Any]) -> None:
    folder = host / STATE_DIR
    folder.mkdir(mode=0o700, exist_ok=True)
    _state_path(host).write_bytes(_canonical(state))


def _target_names() -> tuple[str, ...]:
    return (*SKILLS, *SUPPORT)


def _host_skills(host: Path) -> Path:
    folder = host / "skills"
    if folder.exists():
        _safe_dir(folder)
    else:
        folder.mkdir(mode=0o700)
    return folder


def _doctor(host: Path, state: dict[str, Any] | None) -> dict[str, Any]:
    if state is None:
        return {"status": "unmanaged", "package_id": PACKAGE_ID}
    skills = _host_skills(host)
    for record in state["manifest"]["files"]:
        path = skills / record["path"]
        if not path.is_file() or path.is_symlink() or _sha(path) != record["sha256"]:
            raise DeliveryError("已安装文件缺失、被改写或不安全")
    return {
        "status": "healthy",
        "package_id": PACKAGE_ID,
        "version": state["manifest"]["version"],
        "skill_count": len(SKILLS),
        "file_count": len(state["manifest"]["files"]),
        "feishu_cli": "available" if shutil.which("lark-cli") else "missing_for_feishu_only",
    }


def _stage_package(host: Path, package: Path) -> Path:
    stage = Path(tempfile.mkdtemp(prefix=".zsk-stage-", dir=host))
    try:
        _copy_tree(package / "Skills", stage / "Skills")
        return stage
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def _move_current(skills: Path, backup: Path) -> None:
    backup.mkdir(parents=True, exist_ok=False)
    for name in _target_names():
        path = skills / name
        if path.exists():
            os.replace(path, backup / name)


def _activate_stage(skills: Path, stage: Path) -> None:
    for name in _target_names():
        source = stage / "Skills" / name
        if not source.is_dir():
            raise DeliveryError("交付包缺少目标目录")
        os.replace(source, skills / name)
    shutil.rmtree(stage, ignore_errors=True)


def install_or_upgrade(host: Path, package: Path, *, upgrade: bool) -> dict[str, Any]:
    _safe_dir(host)
    manifest = _manifest(package)
    skills = _host_skills(host)
    state = _load_state(host)
    if state is None:
        if any((skills / name).exists() for name in _target_names()):
            raise DeliveryError("发现同名未托管目录，拒绝覆盖")
        if upgrade:
            raise DeliveryError("当前宿主没有已安装 ZSK，不能升级")
        _activate_stage(skills, _stage_package(host, package))
        _write_state(host, {"package_id": PACKAGE_ID, "manifest": manifest, "history": []})
        return {"status": "installed", "version": manifest["version"], "skill_count": len(SKILLS)}
    _doctor(host, state)
    if state["manifest"] == manifest:
        return {"status": "reused", "version": manifest["version"], "skill_count": len(SKILLS)}
    if not upgrade:
        raise DeliveryError("已安装不同版本，请明确执行 upgrade")
    stage = _stage_package(host, package)
    backup = host / STATE_DIR / "backups" / hashlib.sha256(_canonical(state["manifest"])).hexdigest()[:16]
    _move_current(skills, backup)
    _activate_stage(skills, stage)
    history = [*state["history"], {"path": str(backup.relative_to(host)), "manifest": state["manifest"]}]
    _write_state(host, {"package_id": PACKAGE_ID, "manifest": manifest, "history": history})
    return {"status": "upgraded", "version": manifest["version"], "skill_count": len(SKILLS)}


def rollback(host: Path) -> dict[str, Any]:
    _safe_dir(host)
    state = _load_state(host)
    if state is None or not state["history"]:
        raise DeliveryError("没有可用的 ZSK 回退快照")
    _doctor(host, state)
    previous = state["history"][-1]
    backup = host / previous["path"]
    if not backup.is_dir():
        raise DeliveryError("回退快照缺失")
    skills = _host_skills(host)
    current_backup = host / STATE_DIR / "backups" / hashlib.sha256(_canonical(state["manifest"])).hexdigest()[:16]
    _move_current(skills, current_backup)
    for name in _target_names():
        os.replace(backup / name, skills / name)
    history = [*state["history"][:-1], {"path": str(current_backup.relative_to(host)), "manifest": state["manifest"]}]
    _write_state(host, {"package_id": PACKAGE_ID, "manifest": previous["manifest"], "history": history})
    return {"status": "rolled_back", "version": previous["manifest"]["version"], "skill_count": len(SKILLS)}


def main() -> int:
    parser = argparse.ArgumentParser(description="ZSK 本地交付与 WorkBuddy 文件夹导入准备")
    commands = parser.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--source-root", type=Path, required=True)
    build_parser.add_argument("--out", type=Path, required=True)
    build_parser.add_argument("--version", required=True)
    for name in ("install", "upgrade"):
        command = commands.add_parser(name)
        command.add_argument("--host-root", type=Path, required=True)
        command.add_argument("--package", type=Path, required=True)
    for name in ("doctor", "rollback"):
        command = commands.add_parser(name)
        command.add_argument("--host-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "build":
            result = build(args.source_root, args.out, args.version)
        elif args.command == "doctor":
            result = _doctor(_safe_dir(args.host_root), _load_state(args.host_root))
        elif args.command == "rollback":
            result = rollback(args.host_root)
        else:
            result = install_or_upgrade(_safe_dir(args.host_root), _safe_dir(args.package), upgrade=args.command == "upgrade")
    except DeliveryError as exc:
        print(json.dumps({"status": "blocked", "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
