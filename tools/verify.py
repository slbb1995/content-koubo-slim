#!/usr/bin/env python3
"""Verify the standalone Content Slim release."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTENT_SKILLS = {
    "content-slim",
    "content-analyzer",
    "content-context-retriever",
    "content-writer",
    "content-publish-pack",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_tree_sha256(files: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for item in sorted(files, key=lambda value: value["path"]):
        digest.update(
            f"{item['path']}\0{item['sha256']}\n".encode("utf-8")
        )
    return digest.hexdigest()


def checksum_map() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (ROOT / "SHA256SUMS").read_text(
        encoding="utf-8"
    ).splitlines():
        expected, relative = line.split(maxsplit=1)
        normalized = relative.lstrip("* ")
        if normalized in values:
            raise RuntimeError(f"duplicate checksum path: {normalized}")
        values[normalized] = expected
    return values


def runtime_paths() -> set[str]:
    paths: set[str] = set()
    for skill in CONTENT_SKILLS:
        root = ROOT / "Skills" / skill
        for path in root.rglob("*"):
            if path.is_symlink():
                raise RuntimeError(f"runtime symlink is forbidden: {path}")
            if not path.is_file():
                continue
            if path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}:
                raise RuntimeError(f"generated runtime file found: {path}")
            paths.add(path.relative_to(ROOT).as_posix())
    return paths


def verify_content() -> tuple[str, int]:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    manifest = json.loads(
        (ROOT / "release-manifest.json").read_text(encoding="utf-8")
    )
    if manifest.get("package") != {
        "id": "content-v2-slim",
        "version": version,
    }:
        raise RuntimeError("release manifest and VERSION differ")

    runtime = manifest.get("runtime", {})
    files = runtime.get("files", [])
    if not isinstance(files, list) or not files:
        raise RuntimeError("runtime file list is missing")
    if runtime.get("file_count") != len(files):
        raise RuntimeError("runtime file count is inconsistent")
    if runtime.get("skill_count") != len(CONTENT_SKILLS):
        raise RuntimeError("Content Slim must contain exactly five skills")
    if set(runtime.get("skills", [])) != CONTENT_SKILLS:
        raise RuntimeError("unexpected Content Slim skill set")
    if {item.get("skill") for item in files} != CONTENT_SKILLS:
        raise RuntimeError("runtime files contain an unexpected skill")

    actual_skills = {
        path.parent.name for path in (ROOT / "Skills").glob("*/SKILL.md")
    }
    if actual_skills != CONTENT_SKILLS:
        raise RuntimeError(
            "repository must contain only the five Content Slim skills"
        )
    manifest_paths = {item["path"] for item in files}
    actual_paths = runtime_paths()
    if len(manifest_paths) != len(files) or manifest_paths != actual_paths:
        raise RuntimeError("runtime files and release manifest differ")
    sums = checksum_map()
    if set(sums) != actual_paths:
        raise RuntimeError("SHA256SUMS does not match runtime paths")

    for item in files:
        path = ROOT / item["path"]
        digest = sha256(path) if path.is_file() else ""
        if (
            not path.is_file()
            or path.is_symlink()
            or item.get("mode") != "0644"
            or path.stat().st_size != item["bytes"]
            or digest != item["sha256"]
            or sums[item["path"]] != digest
        ):
            raise RuntimeError(
                f"Content Slim manifest mismatch: {item['path']}"
            )

    packages = ROOT / "Packages"
    if packages.exists() and any(packages.rglob("*")):
        raise RuntimeError(
            "standalone Content Slim must not contain bundled packages"
        )
    tree = runtime_tree_sha256(files)
    if runtime.get("tree_sha256") != tree:
        raise RuntimeError("runtime tree hash is inconsistent")
    source = manifest.get("source", {})
    if (
        source.get("selection_path") != "Skills/"
        or source.get("tree_sha256") != tree
    ):
        raise RuntimeError("release source metadata is inconsistent")
    return version, len(files)


def verify_examples_and_cli() -> None:
    sys.dont_write_bytecode = True
    content_root = ROOT / "Skills" / "content-slim"
    sys.path.insert(0, str(content_root))

    from runtime.client_manifest import validate_manifest
    from runtime.client_registry import load_registry

    manifest_data = json.loads(
        (
            ROOT / "examples" / "content-client-manifest.example.json"
        ).read_text(encoding="utf-8")
    )
    validate_manifest(manifest_data, expected_client_id="my-content")
    load_registry(ROOT / "examples" / "client-registry.example.json")

    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    checks = (
        (
            content_root / "scripts" / "content_slim.py",
            "Content V2 Slim runtime entry",
        ),
        (
            content_root / "scripts" / "configure_client.py",
            "Content Slim 一次持久绑定",
        ),
    )
    for script, expected in checks:
        result = subprocess.run(
            [sys.executable, "-B", str(script), "--help"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or expected not in result.stdout:
            raise RuntimeError(f"CLI smoke test failed: {script}")


def verify_tests() -> None:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-v",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        output = (result.stdout + "\n" + result.stderr).strip()
        raise RuntimeError(f"Content Slim tests failed:\n{output}")


def verify_no_generated_files() -> None:
    forbidden = [
        path
        for path in ROOT.rglob("*")
        if path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}
    ]
    if forbidden:
        raise RuntimeError(f"generated Python files found: {forbidden}")


def main() -> int:
    version, file_count = verify_content()
    verify_examples_and_cli()
    verify_tests()
    verify_no_generated_files()
    print(
        f"PASS: standalone Content Slim {version}, "
        f"5 skills / {file_count} runtime files verified."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
