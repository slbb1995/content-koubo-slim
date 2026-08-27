#!/usr/bin/env python3
"""Verify the public Content Slim package without external dependencies."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SKILLS = {
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


def verify_checksums() -> None:
    lines = (ROOT / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    if not lines:
        raise RuntimeError("SHA256SUMS is empty")
    for line in lines:
        expected, relative = line.split(maxsplit=1)
        relative = relative.lstrip("* ")
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"missing or unsafe checksum target: {relative}")
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(f"checksum mismatch: {relative}")


def verify_release_manifest() -> None:
    manifest = json.loads((ROOT / "release-manifest.json").read_text(encoding="utf-8"))
    package = manifest.get("package", {})
    runtime = manifest.get("runtime", {})
    if package != {"id": "content-v2-slim", "version": "0.11.0-rc.4"}:
        raise RuntimeError("unexpected package identity")
    files = runtime.get("files", [])
    if runtime.get("file_count") != 34 or len(files) != 34:
        raise RuntimeError("release manifest must contain exactly 34 runtime files")
    skills = {item.get("skill") for item in files}
    if skills != EXPECTED_SKILLS:
        raise RuntimeError(f"unexpected skill set: {sorted(skills)}")
    for item in files:
        relative = item["path"]
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"missing or unsafe runtime file: {relative}")
        if path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
            raise RuntimeError(f"release manifest mismatch: {relative}")


def verify_examples_and_cli() -> None:
    sys.dont_write_bytecode = True
    skill_root = ROOT / "Skills" / "content-slim"
    sys.path.insert(0, str(skill_root))
    from runtime.client_manifest import validate_manifest
    from runtime.client_registry import load_registry

    example_manifest = json.loads(
        (ROOT / "examples" / "content-client-manifest.example.json").read_text(
            encoding="utf-8"
        )
    )
    validate_manifest(example_manifest, expected_client_id="my-content")
    registry_path = ROOT / "examples" / "client-registry.example.json"
    registry = load_registry(registry_path)
    if set(registry["clients"]) != {"my-content"}:
        raise RuntimeError("registry example must contain one generic client")

    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(skill_root / "scripts" / "content_slim.py"),
            "--help",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or "Content V2 Slim runtime entry" not in result.stdout:
        raise RuntimeError("content-slim CLI smoke test failed")


def verify_no_generated_files() -> None:
    forbidden = [
        path
        for path in ROOT.rglob("*")
        if path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}
    ]
    if forbidden:
        raise RuntimeError(f"generated Python files found: {forbidden}")


def main() -> int:
    verify_checksums()
    verify_release_manifest()
    verify_examples_and_cli()
    verify_no_generated_files()
    print("PASS: Content Slim 0.11.0-rc.4, 5 Skills, 34 runtime files verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
