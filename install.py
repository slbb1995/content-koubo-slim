#!/usr/bin/env python3
"""Install the five Content Slim skills without overwriting existing data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any


ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = ROOT / "Skills"
COMPONENTS = (
    "content-slim",
    "content-analyzer",
    "content-context-retriever",
    "content-writer",
    "content-publish-pack",
)


def default_destination() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home).expanduser() / "skills"
    return Path.home() / ".codex" / "skills"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def release_manifest() -> dict[str, Any]:
    try:
        manifest = json.loads(
            (ROOT / "release-manifest.json").read_text(encoding="utf-8")
        )
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("发布清单或版本文件无法读取") from exc
    if manifest.get("package") != {
        "id": "content-v2-slim",
        "version": version,
    }:
        raise ValueError("发布清单与 VERSION 不一致")
    runtime = manifest.get("runtime", {})
    if set(runtime.get("skills", [])) != set(COMPONENTS):
        raise ValueError("发布清单中的 Skill 集合不正确")
    files = runtime.get("files")
    if (
        not isinstance(files, list)
        or runtime.get("file_count") != len(files)
        or not files
    ):
        raise ValueError("发布清单文件数量不正确")
    return manifest


def validate_source() -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    try:
        manifest = release_manifest()
    except ValueError as exc:
        return None, [str(exc)]
    for name in COMPONENTS:
        component = SOURCE_ROOT / name
        if not component.is_dir() or component.is_symlink():
            errors.append(f"缺少或拒绝组件目录：{component}")
        if not (component / "SKILL.md").is_file():
            errors.append(f"缺少 Skill 入口：{component / 'SKILL.md'}")
    for item in manifest["runtime"]["files"]:
        path = ROOT / item["path"]
        if not path.is_file() or path.is_symlink():
            errors.append(f"缺少或拒绝运行文件：{item['path']}")
            continue
        if (
            path.stat().st_size != item["bytes"]
            or sha256(path) != item["sha256"]
        ):
            errors.append(f"运行文件校验失败：{item['path']}")
    expected_paths = {
        item["path"] for item in manifest["runtime"]["files"]
    }
    actual_paths: set[str] = set()
    for name in COMPONENTS:
        for path in (SOURCE_ROOT / name).rglob("*"):
            if path.is_symlink():
                errors.append(f"运行目录包含软链接：{path}")
            elif path.is_file():
                if path.name == "__pycache__" or path.suffix in {
                    ".pyc",
                    ".pyo",
                }:
                    errors.append(f"运行目录包含生成文件：{path}")
                else:
                    actual_paths.add(path.relative_to(ROOT).as_posix())
    if actual_paths != expected_paths:
        errors.append("发布清单没有精确覆盖全部运行文件")
    return manifest, errors


def installed_state(destination: Path) -> tuple[list[str], list[str]]:
    present: list[str] = []
    missing: list[str] = []
    for name in COMPONENTS:
        target = destination / name
        valid = (
            target.is_dir()
            and not target.is_symlink()
            and (target / "SKILL.md").is_file()
        )
        (present if valid else missing).append(name)
    return present, missing


def verify_installed(
    destination: Path, manifest: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    expected_paths = {
        Path(item["path"]).relative_to("Skills").as_posix()
        for item in manifest["runtime"]["files"]
    }
    actual_paths: set[str] = set()
    for name in COMPONENTS:
        for path in (destination / name).rglob("*"):
            if path.is_symlink():
                errors.append(f"安装目录包含软链接：{path}")
            elif path.is_file():
                if path.name == "__pycache__" or path.suffix in {
                    ".pyc",
                    ".pyo",
                }:
                    errors.append(f"安装目录包含生成文件：{path}")
                else:
                    actual_paths.add(
                        path.relative_to(destination).as_posix()
                    )
    if actual_paths != expected_paths:
        errors.append("安装目录与发布清单文件集合不一致")
    for item in manifest["runtime"]["files"]:
        relative = Path(item["path"])
        if not relative.parts or relative.parts[0] != "Skills":
            errors.append(f"发布路径不属于 Skills：{item['path']}")
            continue
        target = destination.joinpath(*relative.parts[1:])
        if not target.is_file() or target.is_symlink():
            errors.append(f"安装后缺少文件：{target}")
            continue
        if (
            target.stat().st_size != item["bytes"]
            or sha256(target) != item["sha256"]
        ):
            errors.append(f"安装后校验失败：{target}")
    return errors


def safe_destination(value: Path) -> Path:
    path = value.expanduser()
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("目标 Skills 目录必须是安全绝对路径")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            os.lstat(current)
        except FileNotFoundError:
            break
        if os.path.islink(current):
            raise ValueError(f"目标 Skills 路径包含软链接：{current}")
        if current != path and not Path(current).is_dir():
            raise ValueError(f"目标 Skills 路径经过非目录对象：{current}")
        if current == path and not Path(current).is_dir():
            raise ValueError(f"目标 Skills 路径不是目录：{current}")
    return path


def install(destination: Path) -> int:
    try:
        destination = safe_destination(destination)
    except ValueError as exc:
        print(f"安装目标不安全，已停止：{exc}", file=sys.stderr)
        return 5
    manifest, source_errors = validate_source()
    if source_errors or manifest is None:
        print("安装包不完整，已停止：", file=sys.stderr)
        for error in source_errors:
            print(f"- {error}", file=sys.stderr)
        return 2

    conflicts = [
        destination / name
        for name in COMPONENTS
        if (destination / name).exists()
        or (destination / name).is_symlink()
    ]
    if conflicts:
        print("发现已有同名目录。为避免覆盖，安装已停止：", file=sys.stderr)
        for conflict in conflicts:
            print(f"- {conflict}", file=sys.stderr)
        return 3

    destination.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    try:
        for name in COMPONENTS:
            target = destination / name
            shutil.copytree(SOURCE_ROOT / name, target)
            created.append(target)
        installed_errors = verify_installed(destination, manifest)
        if installed_errors:
            raise ValueError("；".join(installed_errors))
    except Exception as exc:
        for target in reversed(created):
            shutil.rmtree(target, ignore_errors=True)
        print(f"安装失败，已回滚本次新增目录：{exc}", file=sys.stderr)
        return 4
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="安装 Content Slim 的 5 个 Skill"
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=default_destination(),
        help="目标 Skills 目录",
    )
    parser.add_argument(
        "--check", action="store_true", help="只检查目标目录，不写入"
    )
    args = parser.parse_args()

    try:
        destination = safe_destination(args.dest)
    except ValueError as exc:
        print(f"安装目标不安全，已停止：{exc}", file=sys.stderr)
        return 5
    if args.check:
        present, missing = installed_state(destination)
        print(f"检查目录：{destination}")
        print("已存在：" + ("、".join(present) if present else "无"))
        print("缺少：" + ("、".join(missing) if missing else "无"))
        return 0 if not missing else 1

    result = install(destination)
    if result != 0:
        return result
    present, _ = installed_state(destination)
    print(f"安装完成：{destination}")
    print("已安装：" + "、".join(present))
    print("请重新打开任务；首次使用先完成一次明确的本地知识库绑定。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
