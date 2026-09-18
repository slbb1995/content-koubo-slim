#!/usr/bin/env python3
"""Verify the standalone Content 口播 Slim release."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
CONTENT_SKILLS = {
    "content-koubo-slim",
    "content-koubo-analyzer",
    "content-koubo-context-retriever",
    "content-koubo-writer",
    "content-koubo-publish-pack",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def verify_content() -> None:
    for line in (ROOT / "SHA256SUMS").read_text(
        encoding="utf-8"
    ).splitlines():
        expected, relative = line.split(maxsplit=1)
        path = ROOT / relative.lstrip("* ")
        if not path.is_file() or path.is_symlink() or sha256(path) != expected:
            raise RuntimeError(f"Content 口播 Slim checksum mismatch: {relative}")

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    manifest = json.loads(
        (ROOT / "release-manifest.json").read_text(encoding="utf-8")
    )
    if manifest.get("schema_version") != "content-koubo-slim-release-v1":
        raise RuntimeError("unexpected release manifest schema")
    if manifest.get("package") != {
        "id": "content-koubo-slim",
        "version": version,
    }:
        raise RuntimeError("release manifest and VERSION differ")

    source = manifest.get("source", {})
    if source != {"repository": "https://github.com/slbb1995/content-koubo-slim"}:
        raise RuntimeError("release manifest source repository is invalid")

    runtime = manifest.get("runtime", {})
    files = runtime.get("files", [])
    if runtime.get("file_count") != len(files) or len(files) < 34:
        raise RuntimeError("Content 口播 Slim runtime file count is invalid")
    if runtime.get("skill_count") != 5:
        raise RuntimeError("Content 口播 Slim must contain exactly five skills")
    if set(runtime.get("skills", [])) != CONTENT_SKILLS:
        raise RuntimeError("unexpected Content 口播 Slim skill set")
    if {item.get("skill") for item in files} != CONTENT_SKILLS:
        raise RuntimeError("runtime files contain an unexpected skill")

    actual_skills = {
        path.parent.name for path in (ROOT / "Skills").glob("*/SKILL.md")
    }
    if actual_skills != CONTENT_SKILLS:
        raise RuntimeError(
            "repository must contain only the five Content 口播 Slim skills"
        )
    manifest_paths = {item["path"] for item in files}
    if len(manifest_paths) != len(files) or manifest_paths != runtime_paths():
        raise RuntimeError("runtime files and release manifest differ")

    for item in files:
        path = ROOT / item["path"]
        if (
            not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != item["bytes"]
            or sha256(path) != item["sha256"]
        ):
            raise RuntimeError(
                f"Content 口播 Slim manifest mismatch: {item['path']}"
            )

    packages = ROOT / "Packages"
    if packages.exists() and any(packages.rglob("*")):
        raise RuntimeError(
            "standalone Content 口播 Slim must not contain bundled packages"
        )


def verify_examples_and_cli() -> None:
    sys.dont_write_bytecode = True
    content_root = ROOT / "Skills" / "content-koubo-slim"
    sys.path.insert(0, str(content_root))

    from runtime.client_manifest import validate_manifest
    from runtime.client_registry import load_registry
    from runtime.content_source import validate_common_manifest, validate_common_registry, validate_profile_index

    manifest_data = json.loads(
        (
            ROOT / "examples" / "content-koubo-client-manifest.example.json"
        ).read_text(encoding="utf-8")
    )
    validate_manifest(manifest_data, expected_client_id="my-content")
    legacy_registry = json.loads(
        (ROOT / "examples" / "client-registry.example.json").read_text(encoding="utf-8")
    )
    legacy_registry["clients"]["my-content"]["vault_root"] = str(ROOT.resolve())
    with tempfile.TemporaryDirectory(prefix=".content-koubo-verify-", dir=ROOT) as directory:
        registry_path = Path(directory) / "client-registry.json"
        registry_path.write_text(
            json.dumps(legacy_registry, ensure_ascii=False), encoding="utf-8"
        )
        load_registry(registry_path)
    common_manifest = json.loads((ROOT / "examples" / "content-source-manifest.example.json").read_text(encoding="utf-8"))
    common_profiles = json.loads((ROOT / "examples" / "content-profile-index.example.json").read_text(encoding="utf-8"))
    common_registry = json.loads((ROOT / "examples" / "knowledge-base-registry.example.json").read_text(encoding="utf-8"))
    validate_common_manifest(common_manifest)
    validate_profile_index(common_profiles, knowledge_base_id=common_manifest["knowledge_base_id"])
    validate_common_registry(common_registry)

    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-B",
            str(content_root / "scripts" / "content_koubo_slim.py"),
            "--help",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
    )
    if (
        result.returncode != 0
        or "Content 口播 Slim runtime entry" not in result.stdout
    ):
        raise RuntimeError("Content 口播 Slim CLI smoke test failed")


def verify_no_generated_files() -> None:
    forbidden = [
        path
        for path in ROOT.rglob("*")
        if path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}
    ]
    if forbidden:
        raise RuntimeError(f"generated Python files found: {forbidden}")


def verify_tests() -> None:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-B",
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Content 口播 Slim tests failed:\n" + result.stdout + result.stderr
        )


def main() -> int:
    verify_content()
    verify_examples_and_cli()
    verify_tests()
    verify_no_generated_files()
    count = json.loads((ROOT / "release-manifest.json").read_text(encoding="utf-8"))["runtime"]["file_count"]
    print(f"PASS: standalone Content 口播 Slim 5 skills / {count} runtime files verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
