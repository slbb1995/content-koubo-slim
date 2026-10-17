#!/usr/bin/env python3
"""Deterministic build and reversible overlay installation for Content 口播 Slim.

This maintenance tool deliberately leaves the managed Legacy V1 package and
its state untouched.  It installs only the five Content 口播 Slim Skill directories and
requires a create-only pre-install snapshot before changing a Host.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any, Iterable


PACKAGE_ID = "content-koubo-slim"
PACKAGE_SCHEMA = "content-koubo-slim-release-v1"
SELECTION_PATH = "packages/content-koubo-slim.json"
BACKUP_SCHEMA = "content-koubo-slim-host-backup-v1"
EXPECTED_SKILLS = (
    "content-koubo-analyzer",
    "content-koubo-context-retriever",
    "content-koubo-publish-pack",
    "content-koubo-slim",
    "content-koubo-writer",
)
FORBIDDEN_PARTS = {
    ".git",
    "__pycache__",
    "backups",
    "evals",
    "examples",
    "tests",
    "audits",
}
FORBIDDEN_SUFFIXES = {".bak", ".orig", ".tmp", ".pyc", ".pyo"}
PORTABLE_MARKERS = (
    re.compile(rb"/Users/[A-Za-z0-9._-]+/"),
    re.compile(rb"/home/[A-Za-z0-9._-]+/"),
    re.compile(rb"[A-Za-z]:\\\\Users\\\\"),
)
CUSTOMER_MARKERS = tuple(
    item.encode("utf-8")
    for item in ("朱梅燕", "山东行致远", "BAOXIAN-CLIENT-DELIVERY-20260805")
)
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-rc\.[0-9]+)?$")
META_FILES = ("VERSION", "release-manifest.json", "SHA256SUMS")
CONTROL_FILES = (".content-workflow-host.json", ".content-workflow/state.json")


class SlimReleaseError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def fail(code: str, message: str) -> None:
    raise SlimReleaseError(code, message)


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def safe_relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        fail("PATH_INVALID", "路径必须是非空 POSIX 相对路径")
    path = PurePosixPath(value)
    if path.is_absolute() or value != path.as_posix() or any(part in {"", ".", ".."} for part in path.parts):
        fail("PATH_INVALID", "路径不得绝对、跳级或漂移")
    return value


def run_git(root: Path, *args: str, text: bool = False) -> bytes | str:
    completed = subprocess.run(
        ["git", "-C", os.fspath(root), *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        fail("GIT_INVALID", "Factory Git 对象或状态不可读")
    if text:
        try:
            return completed.stdout.decode("utf-8").strip()
        except UnicodeDecodeError:
            fail("GIT_INVALID", "Factory Git 元数据不是 UTF-8")
    return completed.stdout


def assert_clean_head(root: Path, source_commit: str) -> tuple[str, int]:
    if not HEX40.fullmatch(source_commit):
        fail("SOURCE_COMMIT_INVALID", "source commit 必须是 40 位 SHA")
    status = run_git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    head = run_git(root, "rev-parse", "HEAD", text=True)
    tree = run_git(root, "rev-parse", "HEAD^{tree}", text=True)
    epoch = run_git(root, "show", "-s", "--format=%ct", "HEAD", text=True)
    if status or head != source_commit or not isinstance(tree, str) or not HEX40.fullmatch(tree):
        fail("FACTORY_NOT_FIXED", "构建必须来自当前干净 HEAD")
    if not isinstance(epoch, str) or not epoch.isdecimal():
        fail("GIT_INVALID", "commit 时间不可读")
    return tree, int(epoch)


def git_blob(root: Path, commit: str, relative: str) -> bytes:
    safe_relative(relative)
    result = run_git(root, "show", f"{commit}:{relative}")
    assert isinstance(result, bytes)
    return result


def load_selection(root: Path, commit: str) -> dict[str, Any]:
    try:
        value = json.loads(git_blob(root, commit, SELECTION_PATH).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail("SELECTION_INVALID", "Slim package selection 不可读")
    expected = {
        "schema_version": "workflow-skill-selection-v1",
        "package_id": PACKAGE_ID,
        "source_root": "Skills",
        "expected_skill_count": 5,
        "skills": list(EXPECTED_SKILLS),
    }
    if value != expected:
        fail("SELECTION_INVALID", "Slim package selection 必须精确选择五个新 Skill")
    return value


def git_skill_records(root: Path, commit: str, skill: str) -> list[dict[str, Any]]:
    source_root = f"Skills/{skill}"
    raw = run_git(root, "ls-tree", "-r", "-z", commit, "--", source_root)
    assert isinstance(raw, bytes)
    records: list[dict[str, Any]] = []
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        try:
            header, path_raw = entry.split(b"\t", 1)
            mode, kind, _oid = header.decode("ascii").split(" ")
            source_path = path_raw.decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            fail("SOURCE_TREE_INVALID", "Skill Git tree 记录非法")
        if kind != "blob" or mode not in {"100644", "100755"}:
            fail("SOURCE_TREE_INVALID", "运行包只允许普通 Git 文件")
        relative = PurePosixPath(source_path).relative_to("Skills").as_posix()
        safe_relative(relative)
        path = PurePosixPath(relative)
        if any(part in FORBIDDEN_PARTS for part in path.parts) or path.suffix in FORBIDDEN_SUFFIXES:
            fail("SOURCE_TREE_INVALID", f"运行包含禁止路径：{relative}")
        body = git_blob(root, commit, source_path)
        if any(pattern.search(body) for pattern in PORTABLE_MARKERS) or any(marker in body for marker in CUSTOMER_MARKERS):
            fail("SOURCE_NOT_PORTABLE", f"运行文件含客户或本机标记：{relative}")
        records.append(
            {
                "path": f"Skills/{relative}",
                "skill": skill,
                "mode": "0755" if mode == "100755" else "0644",
                "bytes": len(body),
                "sha256": sha256(body),
                "body": body,
            }
        )
    records.sort(key=lambda item: item["path"].encode("utf-8"))
    if not records or not any(item["path"] == f"Skills/{skill}/SKILL.md" for item in records):
        fail("SOURCE_TREE_INVALID", f"{skill} 缺少 SKILL.md")
    return records


def tree_sha(records: Iterable[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for item in sorted(records, key=lambda row: row["path"].encode("utf-8")):
        digest.update(
            b"F\0"
            + item["path"].encode("utf-8")
            + b"\0"
            + item["mode"].encode("ascii")
            + b"\0"
            + item["sha256"].encode("ascii")
            + b"\0"
        )
    return digest.hexdigest()


def chmod_plain(path: Path, mode: int) -> None:
    if path.is_symlink():
        fail("TREE_UNSAFE", "chmod target must be a plain path")
    if os.name == 'nt':
        os.chmod(path, mode)
    else:
        os.chmod(path, mode, follow_symlinks=False)


def mode_matches(observed: int, expected: int) -> bool:
    # Windows exposes a read-only attribute, not POSIX execute/group bits.
    if os.name == 'nt':
        return bool(observed & stat.S_IWUSR) == bool(expected & stat.S_IWUSR)
    return observed == expected


def write_file(path: Path, body: bytes, mode: int, epoch: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    chmod_plain(path, mode)
    os.utime(path, (epoch, epoch), **({} if os.name == "nt" else {"follow_symlinks": False}))


def normalize_directories(root: Path, epoch: int, mode: int = 0o755) -> None:
    directories = [root] + [item for item in root.rglob("*") if item.is_dir() and not item.is_symlink()]
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        chmod_plain(directory, mode)
        os.utime(directory, (epoch, epoch), **({} if os.name == "nt" else {"follow_symlinks": False}))


def checksum_body(records: list[dict[str, Any]]) -> bytes:
    return "".join(
        f"{item['sha256']}  {item['path']}\n"
        for item in sorted(records, key=lambda row: row["path"].encode("utf-8"))
    ).encode("utf-8")


def build(root: Path, source_commit: str, version: str, out: Path) -> dict[str, Any]:
    root = root.resolve(strict=True)
    if not VERSION.fullmatch(version):
        fail("VERSION_INVALID", "版本必须是 x.y.z 或 x.y.z-rc.n")
    if not out.is_absolute() or out.exists() or not out.parent.is_dir():
        fail("OUTPUT_INVALID", "输出必须是父目录已存在的全新绝对路径")
    tree, epoch = assert_clean_head(root, source_commit)
    selection = load_selection(root, source_commit)
    records: list[dict[str, Any]] = []
    for skill in EXPECTED_SKILLS:
        records.extend(git_skill_records(root, source_commit, skill))
    manifest_records = [{key: item[key] for key in ("path", "skill", "mode", "bytes", "sha256")} for item in records]
    manifest = {
        "schema_version": PACKAGE_SCHEMA,
        "package": {"id": PACKAGE_ID, "version": version},
        "source": {"commit": source_commit, "tree": tree, "selection_path": SELECTION_PATH},
        "runtime": {
            "skill_count": 5,
            "skills": list(EXPECTED_SKILLS),
            "file_count": len(records),
            "tree_sha256": tree_sha(records),
            "legacy_v1_runtime_dependency_count": 0,
            "files": manifest_records,
        },
        "integrity": {"normalized_mtime_epoch": epoch, "hash_algorithm": "sha256"},
    }
    stage = Path(tempfile.mkdtemp(prefix=".content-koubo-slim-build-", dir=out.parent))
    published = False
    try:
        for item in records:
            write_file(stage / item["path"], item["body"], int(item["mode"], 8), epoch)
        version_body = (version + "\n").encode("utf-8")
        manifest_body = canonical_json(manifest)
        meta = [
            {"path": "VERSION", "mode": "0644", "bytes": len(version_body), "sha256": sha256(version_body), "body": version_body},
            {"path": "release-manifest.json", "mode": "0644", "bytes": len(manifest_body), "sha256": sha256(manifest_body), "body": manifest_body},
        ]
        for item in meta:
            write_file(stage / item["path"], item["body"], 0o644, epoch)
        sums = checksum_body(meta + records)
        write_file(stage / "SHA256SUMS", sums, 0o644, epoch)
        normalize_directories(stage, epoch)
        verify(stage, expected_commit=source_commit, expected_version=version)
        if run_git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all"):
            fail("BUILD_SOURCE_DRIFT", "构建期间 Factory 发生漂移")
        os.rename(stage, out)
        published = True
        result = verify(out, expected_commit=source_commit, expected_version=version)
        result["status"] = "local_candidate_not_published"
        return result
    finally:
        if not published:
            shutil.rmtree(stage, ignore_errors=True)


def ordinary_files(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in list(dirs):
            child = current_path / name
            mode = child.stat(follow_symlinks=False).st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                fail("TREE_UNSAFE", "目录树含符号链接或特殊目录")
        for name in files:
            child = current_path / name
            info = child.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                fail("TREE_UNSAFE", "目录树含符号链接、硬链接或特殊文件")
            result[child.relative_to(root).as_posix()] = child
    return result


def verify(package: Path, *, expected_commit: str | None = None, expected_version: str | None = None) -> dict[str, Any]:
    if not package.is_absolute() or not package.is_dir() or package.is_symlink():
        fail("PACKAGE_INVALID", "package 必须是普通绝对目录")
    files = ordinary_files(package)
    try:
        manifest_raw = files["release-manifest.json"].read_bytes()
        manifest = json.loads(manifest_raw.decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
        fail("PACKAGE_INVALID", "release manifest 不可读")
    if canonical_json(manifest) != manifest_raw or manifest.get("schema_version") != PACKAGE_SCHEMA:
        fail("PACKAGE_INVALID", "release manifest 不是规范 Content 口播 Slim manifest")
    if manifest.get("package", {}).get("id") != PACKAGE_ID or manifest.get("runtime", {}).get("skills") != list(EXPECTED_SKILLS):
        fail("PACKAGE_SCOPE_INVALID", "package 必须精确包含五个新 Skill")
    if manifest["runtime"].get("skill_count") != 5 or manifest["runtime"].get("legacy_v1_runtime_dependency_count") != 0:
        fail("PACKAGE_SCOPE_INVALID", "Skill 数或旧 V1 依赖声明非法")
    if expected_commit is not None and manifest.get("source", {}).get("commit") != expected_commit:
        fail("PACKAGE_BINDING_INVALID", "package source commit 不匹配")
    if expected_version is not None and manifest.get("package", {}).get("version") != expected_version:
        fail("PACKAGE_BINDING_INVALID", "package version 不匹配")
    epoch = manifest.get("integrity", {}).get("normalized_mtime_epoch")
    if not isinstance(epoch, int) or epoch < 1:
        fail("PACKAGE_INVALID", "package mtime 绑定非法")
    runtime = manifest["runtime"].get("files")
    if not isinstance(runtime, list) or len(runtime) != manifest["runtime"].get("file_count"):
        fail("PACKAGE_INVALID", "runtime 文件清单非法")
    expected_paths = set(META_FILES)
    checked: list[dict[str, Any]] = []
    for item in runtime:
        if not isinstance(item, dict) or set(item) != {"path", "skill", "mode", "bytes", "sha256"}:
            fail("PACKAGE_INVALID", "runtime 清单字段非法")
        path = safe_relative(item["path"])
        if item["skill"] not in EXPECTED_SKILLS or not path.startswith(f"Skills/{item['skill']}/"):
            fail("PACKAGE_SCOPE_INVALID", "runtime 路径跨 Skill")
        target = files.get(path)
        if target is None:
            fail("PACKAGE_INVALID", "runtime 文件缺失")
        body = target.read_bytes()
        mode = f"{stat.S_IMODE(target.stat(follow_symlinks=False).st_mode):04o}"
        if len(body) != item["bytes"] or sha256(body) != item["sha256"] or not mode_matches(int(mode, 8), int(item["mode"], 8)):
            fail("PACKAGE_DRIFT", f"runtime 文件漂移：{path}")
        if int(target.stat(follow_symlinks=False).st_mtime) != epoch:
            fail("PACKAGE_DRIFT", f"runtime mtime 漂移：{path}")
        expected_paths.add(path)
        checked.append(dict(item))
    if set(files) != expected_paths:
        fail("PACKAGE_EXTRA_ENTRY", "package 含未登记文件")
    if tree_sha(checked) != manifest["runtime"].get("tree_sha256"):
        fail("PACKAGE_DRIFT", "runtime tree hash 不匹配")
    version_body = files["VERSION"].read_bytes()
    if version_body != (manifest["package"]["version"] + "\n").encode("utf-8"):
        fail("PACKAGE_DRIFT", "VERSION 与 manifest 不一致")
    meta_records = [
        {"path": "VERSION", "mode": "0644", "bytes": len(version_body), "sha256": sha256(version_body)},
        {"path": "release-manifest.json", "mode": "0644", "bytes": len(manifest_raw), "sha256": sha256(manifest_raw)},
    ]
    if files["SHA256SUMS"].read_bytes() != checksum_body(meta_records + checked):
        fail("PACKAGE_DRIFT", "SHA256SUMS 不匹配")
    for relative, path in files.items():
        if int(path.stat(follow_symlinks=False).st_mtime) != epoch:
            fail("PACKAGE_DRIFT", f"package mtime 漂移：{relative}")
    release_records = [
        {"path": relative, "mode": next((item["mode"] for item in checked if item["path"] == relative), "0644"), "sha256": sha256(path.read_bytes())}
        for relative, path in files.items()
    ]
    return {
        "status": "verified",
        "package_id": PACKAGE_ID,
        "version": manifest["package"]["version"],
        "source_commit": manifest["source"]["commit"],
        "skill_count": 5,
        "skills": list(EXPECTED_SKILLS),
        "file_count": len(runtime),
        "runtime_tree_sha256": manifest["runtime"]["tree_sha256"],
        "release_tree_sha256": tree_sha(release_records),
        "manifest_sha256": sha256(manifest_raw),
    }


def target_snapshot(path: Path) -> dict[str, Any]:
    if not os.path.lexists(path):
        return {"exists": False, "file_count": 0, "tree_sha256": None}
    if path.is_symlink() or not path.is_dir():
        fail("HOST_TARGET_UNSAFE", f"Host target 不是普通目录：{path.name}")
    files = ordinary_files(path)
    records = []
    for relative, item in files.items():
        info = item.stat(follow_symlinks=False)
        records.append({"path": relative, "mode": f"{stat.S_IMODE(info.st_mode):04o}", "sha256": sha256(item.read_bytes())})
    return {"exists": True, "file_count": len(files), "tree_sha256": tree_sha(records)}


def untouched_skills_sha(skills_root: Path) -> str:
    digest = hashlib.sha256()
    for entry in sorted(skills_root.iterdir(), key=lambda item: item.name.encode("utf-8")):
        if entry.name in EXPECTED_SKILLS:
            continue
        mode = entry.stat(follow_symlinks=False).st_mode
        if stat.S_ISLNK(mode):
            digest.update(b"L\0" + entry.name.encode("utf-8") + b"\0" + os.readlink(entry).encode("utf-8") + b"\0")
            continue
        if stat.S_ISREG(mode):
            digest.update(
                b"F\0" + entry.name.encode("utf-8") + b"\0"
                + f"{stat.S_IMODE(mode):04o}".encode("ascii") + b"\0"
                + sha256(entry.read_bytes()).encode("ascii") + b"\0"
            )
            continue
        if not stat.S_ISDIR(mode):
            fail("HOST_TREE_UNSAFE", "skills 根含特殊条目")
        for current, dirs, files in os.walk(entry, followlinks=False):
            current_path = Path(current)
            relative_root = current_path.relative_to(skills_root).as_posix()
            current_mode = current_path.stat(follow_symlinks=False).st_mode
            digest.update(
                b"D\0" + relative_root.encode("utf-8") + b"\0"
                + f"{stat.S_IMODE(current_mode):04o}".encode("ascii") + b"\0"
            )
            for name in list(dirs):
                child = current_path / name
                child_mode = child.stat(follow_symlinks=False).st_mode
                if stat.S_ISLNK(child_mode):
                    relative = child.relative_to(skills_root).as_posix()
                    digest.update(
                        b"L\0" + relative.encode("utf-8") + b"\0"
                        + os.readlink(child).encode("utf-8") + b"\0"
                    )
                    dirs.remove(name)
                elif not stat.S_ISDIR(child_mode):
                    fail("HOST_TREE_UNSAFE", "skills 子树含特殊目录条目")
            for name in files:
                child = current_path / name
                relative = child.relative_to(skills_root).as_posix()
                child_mode = child.stat(follow_symlinks=False).st_mode
                if stat.S_ISLNK(child_mode):
                    digest.update(
                        b"L\0" + relative.encode("utf-8") + b"\0"
                        + os.readlink(child).encode("utf-8") + b"\0"
                    )
                elif stat.S_ISREG(child_mode):
                    digest.update(
                        b"F\0" + relative.encode("utf-8") + b"\0"
                        + f"{stat.S_IMODE(child_mode):04o}".encode("ascii") + b"\0"
                        + sha256(child.read_bytes()).encode("ascii") + b"\0"
                    )
                else:
                    fail("HOST_TREE_UNSAFE", "skills 子树含特殊文件")
    return digest.hexdigest()


def control_snapshot(host: Path) -> list[dict[str, Any]]:
    result = []
    for relative in CONTROL_FILES:
        path = host / relative
        if not path.is_file() or path.is_symlink():
            fail("HOST_STATE_INVALID", f"Host 控制文件缺失：{relative}")
        body = path.read_bytes()
        result.append({"path": relative, "bytes": len(body), "sha256": sha256(body)})
    return result


def backup_host(host: Path, package: Path, out: Path) -> dict[str, Any]:
    package_receipt = verify(package)
    if not host.is_absolute() or not host.is_dir() or host.is_symlink() or not (host / "skills").is_dir():
        fail("HOST_INVALID", "Host 必须是含普通 skills 目录的绝对路径")
    if not out.is_absolute() or out.exists() or not out.parent.is_dir():
        fail("BACKUP_INVALID", "backup 必须是父目录已存在的全新绝对路径")
    out.mkdir(mode=0o700)
    targets = []
    try:
        for skill in EXPECTED_SKILLS:
            source = host / "skills" / skill
            snapshot = target_snapshot(source)
            targets.append({"skill": skill, **snapshot})
            if snapshot["exists"]:
                shutil.copytree(source, out / "before-skills" / skill, copy_function=shutil.copy2, symlinks=False)
        controls = control_snapshot(host)
        for item in controls:
            destination = out / "before-control" / item["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(host / item["path"], destination)
        manifest = {
            "schema_version": BACKUP_SCHEMA,
            "host_root": os.fspath(host),
            "package_release_tree_sha256": package_receipt["release_tree_sha256"],
            "targets": targets,
            "control_files": controls,
            "untouched_skills_sha256": untouched_skills_sha(host / "skills"),
        }
        (out / "backup-manifest.json").write_bytes(canonical_json(manifest))
        os.chmod(out / "backup-manifest.json", 0o400)
        return {
            "status": "backed_up",
            "backup": os.fspath(out),
            "target_count": 5,
            "preexisting_target_count": sum(1 for item in targets if item["exists"]),
            "untouched_skills_sha256": manifest["untouched_skills_sha256"],
            "control_file_count": len(controls),
        }
    except Exception:
        shutil.rmtree(out, ignore_errors=True)
        raise


def load_backup(path: Path, host: Path, package_receipt: dict[str, Any]) -> dict[str, Any]:
    try:
        raw = (path / "backup-manifest.json").read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        fail("BACKUP_INVALID", "backup manifest 不可读")
    if canonical_json(value) != raw or value.get("schema_version") != BACKUP_SCHEMA:
        fail("BACKUP_INVALID", "backup manifest 非规范")
    if value.get("host_root") != os.fspath(host) or value.get("package_release_tree_sha256") != package_receipt["release_tree_sha256"]:
        fail("BACKUP_INVALID", "backup 与 Host 或 package 不匹配")
    if [item.get("skill") for item in value.get("targets", [])] != list(EXPECTED_SKILLS):
        fail("BACKUP_INVALID", "backup target 清单非法")
    return value


def assert_control_unchanged(host: Path, backup: dict[str, Any]) -> None:
    if control_snapshot(host) != backup["control_files"]:
        fail("HOST_CONTROL_DRIFT", "Legacy Host 控制状态在 P7 操作中发生变化")


def unrelated_host_drift(host: Path, backup: dict[str, Any]) -> tuple[bool, str]:
    current = untouched_skills_sha(host / "skills")
    return current != backup["untouched_skills_sha256"], current


def set_installed_permissions(root: Path) -> None:
    for path in ordinary_files(root).values():
        current = stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
        chmod_plain(path, 0o555 if current & 0o111 else 0o444)
    directories = [root] + [item for item in root.rglob("*") if item.is_dir() and not item.is_symlink()]
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        chmod_plain(directory, 0o555)


def install(host: Path, package: Path, backup_path: Path) -> dict[str, Any]:
    receipt = verify(package)
    backup = load_backup(backup_path, host, receipt)
    assert_control_unchanged(host, backup)
    for target in backup["targets"]:
        if target_snapshot(host / "skills" / target["skill"]) != {key: target[key] for key in ("exists", "file_count", "tree_sha256")}:
            fail("HOST_TARGET_DRIFT", "Host target 已偏离安装前快照")
        if target["exists"]:
            fail("HOST_TARGET_CONFLICT", "Content 口播 Slim overlay 不覆盖已存在的同名 Skill")
    stage = Path(tempfile.mkdtemp(prefix=".content-koubo-slim-install-", dir=host / "skills"))
    moved: list[Path] = []
    try:
        for skill in EXPECTED_SKILLS:
            shutil.copytree(package / "Skills" / skill, stage / skill, copy_function=shutil.copy2, symlinks=False)
        for skill in EXPECTED_SKILLS:
            destination = host / "skills" / skill
            os.rename(stage / skill, destination)
            moved.append(destination)
        stage.rmdir()
        for destination in moved:
            set_installed_permissions(destination)
        healthy = doctor(host, package)
        assert_control_unchanged(host, backup)
        return {**healthy, "status": "installed"}
    except Exception:
        for destination in reversed(moved):
            if destination.exists() and not destination.is_symlink():
                make_writable_tree(destination)
                shutil.rmtree(destination)
        shutil.rmtree(stage, ignore_errors=True)
        raise


def doctor(host: Path, package: Path) -> dict[str, Any]:
    receipt = verify(package)
    manifest = json.loads((package / "release-manifest.json").read_text(encoding="utf-8"))
    expected_by_skill: dict[str, dict[str, dict[str, Any]]] = {skill: {} for skill in EXPECTED_SKILLS}
    for item in manifest["runtime"]["files"]:
        relative = PurePosixPath(item["path"]).relative_to(
            PurePosixPath("Skills") / item["skill"]
        ).as_posix()
        expected_by_skill[item["skill"]][relative] = item
    for skill in EXPECTED_SKILLS:
        root = host / "skills" / skill
        if not root.is_dir() or root.is_symlink():
            fail("INSTALLED_TREE_DRIFT", f"缺少已安装 Skill：{skill}")
        actual = ordinary_files(root)
        if set(actual) != set(expected_by_skill[skill]):
            fail("INSTALLED_TREE_DRIFT", f"已安装 Skill 文件集合漂移：{skill}")
        for relative, item in expected_by_skill[skill].items():
            path = actual[relative]
            body = path.read_bytes()
            installed_mode = stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
            expected_mode = 0o555 if int(item["mode"], 8) & 0o111 else 0o444
            if sha256(body) != item["sha256"] or len(body) != item["bytes"] or not mode_matches(installed_mode, expected_mode):
                fail("INSTALLED_TREE_DRIFT", f"已安装 Skill 内容或 mode 漂移：{skill}/{relative}")
    return {
        "status": "healthy",
        "version": receipt["version"],
        "source_commit": receipt["source_commit"],
        "skill_count": 5,
        "file_count": receipt["file_count"],
        "runtime_tree_sha256": receipt["runtime_tree_sha256"],
    }


def make_writable_tree(root: Path) -> None:
    if not root.exists():
        return
    if os.name == "nt":
        for path in ordinary_files(root).values():
            chmod_plain(path, 0o644)
    for directory in [root] + [item for item in root.rglob("*") if item.is_dir() and not item.is_symlink()]:
        chmod_plain(directory, 0o755)


def rollback(host: Path, package: Path, backup_path: Path) -> dict[str, Any]:
    receipt = verify(package)
    backup = load_backup(backup_path, host, receipt)
    doctor(host, package)
    assert_control_unchanged(host, backup)
    for skill in EXPECTED_SKILLS:
        target = host / "skills" / skill
        make_writable_tree(target)
        shutil.rmtree(target)
    for target in backup["targets"]:
        if target["exists"]:
            source = backup_path / "before-skills" / target["skill"]
            shutil.copytree(source, host / "skills" / target["skill"], copy_function=shutil.copy2, symlinks=False)
    for target in backup["targets"]:
        expected = {key: target[key] for key in ("exists", "file_count", "tree_sha256")}
        if target_snapshot(host / "skills" / target["skill"]) != expected:
            fail("ROLLBACK_FAILED", f"回滚后 target 不等于备份：{target['skill']}")
    assert_control_unchanged(host, backup)
    drifted, current_untouched_sha = unrelated_host_drift(host, backup)
    return {
        "status": "rolled_back",
        "restored_target_count": 5,
        "legacy_control_state_preserved": True,
        "unrelated_host_drift_observed": drifted,
        "unrelated_skills_before_sha256": backup["untouched_skills_sha256"],
        "unrelated_skills_current_sha256": current_untouched_sha,
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Content 口播 Slim P7 build/install/rollback maintenance tool")
    commands = root.add_subparsers(dest="operation", required=True)
    build_cmd = commands.add_parser("build")
    build_cmd.add_argument("--root", required=True, type=Path)
    build_cmd.add_argument("--source-commit", required=True)
    build_cmd.add_argument("--version", required=True)
    build_cmd.add_argument("--out", required=True, type=Path)
    verify_cmd = commands.add_parser("verify")
    verify_cmd.add_argument("--package", required=True, type=Path)
    backup_cmd = commands.add_parser("backup")
    backup_cmd.add_argument("--host-root", required=True, type=Path)
    backup_cmd.add_argument("--package", required=True, type=Path)
    backup_cmd.add_argument("--out", required=True, type=Path)
    for name in ("install", "rollback"):
        command = commands.add_parser(name)
        command.add_argument("--host-root", required=True, type=Path)
        command.add_argument("--package", required=True, type=Path)
        command.add_argument("--backup", required=True, type=Path)
    doctor_cmd = commands.add_parser("doctor")
    doctor_cmd.add_argument("--host-root", required=True, type=Path)
    doctor_cmd.add_argument("--package", required=True, type=Path)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.operation == "build":
            result = build(args.root, args.source_commit, args.version, args.out)
        elif args.operation == "verify":
            result = verify(args.package)
        elif args.operation == "backup":
            result = backup_host(args.host_root, args.package, args.out)
        elif args.operation == "install":
            result = install(args.host_root, args.package, args.backup)
        elif args.operation == "doctor":
            result = doctor(args.host_root, args.package)
        else:
            result = rollback(args.host_root, args.package, args.backup)
    except SlimReleaseError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
