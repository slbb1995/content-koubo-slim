#!/usr/bin/env python3
"""Verify Content Slim, ZSK, and their Obsidian bridge."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ZSK_PACKAGE = ROOT / "Packages" / "zsk-knowledge-base"
CONTENT_SKILLS = {
    "content-slim", "content-analyzer", "content-context-retriever",
    "content-writer", "content-publish-pack",
}
ZSK_SKILLS = {"zsk-router", "zsk-ruku", "zsk-zhishi", "zsk-duibiao", "zsk-profile"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_content() -> None:
    for line in (ROOT / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        expected, relative = line.split(maxsplit=1)
        path = ROOT / relative.lstrip("* ")
        if not path.is_file() or path.is_symlink() or sha256(path) != expected:
            raise RuntimeError(f"Content Slim checksum mismatch: {relative}")
    manifest = json.loads((ROOT / "release-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("package") != {"id": "content-v2-slim", "version": "0.11.0-rc.4"}:
        raise RuntimeError("unexpected Content Slim package identity")
    runtime = manifest.get("runtime", {})
    files = runtime.get("files", [])
    if runtime.get("file_count") != 34 or len(files) != 34:
        raise RuntimeError("Content Slim must contain exactly 34 runtime files")
    if {item.get("skill") for item in files} != CONTENT_SKILLS:
        raise RuntimeError("unexpected Content Slim skill set")
    for item in files:
        path = ROOT / item["path"]
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"missing Content Slim runtime file: {item['path']}")
        if path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
            raise RuntimeError(f"Content Slim manifest mismatch: {item['path']}")


def verify_zsk() -> None:
    manifest = json.loads((ZSK_PACKAGE / "zsk-manifest.json").read_text(encoding="utf-8"))
    expected = {
        "package_id": "zsk-knowledge-base",
        "version": "0.2.2-stage11-preview",
        "skills": ["zsk-router", "zsk-ruku", "zsk-zhishi", "zsk-duibiao", "zsk-profile"],
        "support": ["shared"],
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise RuntimeError(f"unexpected ZSK {key}")
    files = manifest.get("files", [])
    if len(files) != 28:
        raise RuntimeError("ZSK must contain exactly 28 runtime files")
    for item in files:
        path = ZSK_PACKAGE / "Skills" / item["path"]
        if not path.is_file() or path.is_symlink() or sha256(path) != item["sha256"]:
            raise RuntimeError(f"ZSK manifest mismatch: {item['path']}")
    actual = {path.parent.name for path in (ZSK_PACKAGE / "Skills").glob("zsk-*/SKILL.md")}
    if actual != ZSK_SKILLS:
        raise RuntimeError("unexpected ZSK skill directories")


def verify_examples_and_cli() -> None:
    sys.dont_write_bytecode = True
    content_root = ROOT / "Skills" / "content-slim"
    sys.path.insert(0, str(content_root))
    from runtime.client_manifest import validate_manifest
    from runtime.client_registry import load_registry

    for name, client_id in (
        ("content-client-manifest.example.json", "my-content"),
        ("zsk-content-client-manifest.example.json", "my-zsk-vault"),
    ):
        data = json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))
        validate_manifest(data, expected_client_id=client_id)
    for name in ("client-registry.example.json", "zsk-content-client-registry.example.json"):
        load_registry(ROOT / "examples" / name)
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-B", str(content_root / "scripts" / "content_slim.py"), "--help"],
        cwd=ROOT, env=env, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0 or "Content V2 Slim runtime entry" not in result.stdout:
        raise RuntimeError("Content Slim CLI smoke test failed")


def verify_zsk_delivery() -> None:
    tool = ZSK_PACKAGE / "tools" / "zsk_delivery.py"
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    with tempfile.TemporaryDirectory(prefix="zsk-public-host-") as directory:
        install = subprocess.run(
            [sys.executable, "-B", str(tool), "install", "--host-root", directory, "--package", str(ZSK_PACKAGE)],
            env=env, capture_output=True, text=True, check=False,
        )
        doctor = subprocess.run(
            [sys.executable, "-B", str(tool), "doctor", "--host-root", directory],
            env=env, capture_output=True, text=True, check=False,
        )
        if install.returncode != 0 or json.loads(install.stdout).get("status") != "installed":
            raise RuntimeError(f"ZSK install failed: {install.stderr}")
        if doctor.returncode != 0 or json.loads(doctor.stdout).get("status") != "healthy":
            raise RuntimeError(f"ZSK doctor failed: {doctor.stderr}")


def verify_obsidian_bridge() -> None:
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ZSK_PACKAGE / "Skills"))
    from runtime.vault_reader import read_method_asset, read_primary_profile
    from runtime.vault_search import search_knowledge_assets, search_method_assets
    from shared.contracts import BINDING_SCHEMA, ROOT_KEYS, Binding
    from shared.obsidian_adapter import ObsidianAdapter
    from shared.stage5_intake import IntakeRequest, Stage5Intake
    from shared.stage6_knowledge import KnowledgeRequest, Stage6Knowledge
    from shared.stage7_method import MethodRequest, Stage7Method
    from shared.stage8_profile import ProfileLayers, ProfileRequest, Stage8Profile

    task_id = "01a01e29-a6ba-73a2-82e6-4ad1caa0f33b"
    temporary_parent = Path("/private/tmp") if Path("/private/tmp").is_dir() else Path(tempfile.gettempdir()).resolve()
    with tempfile.TemporaryDirectory(prefix="zsk-content-slim-", dir=temporary_parent) as directory:
        binding = Binding(
            BINDING_SCHEMA, "CLT-BRIDGE001", "中性主体", "中性知识库", "person",
            "obsidian", directory, {key: f"root:{key}" for key in ROOT_KEYS},
            "zsk-stage2-template-v1",
        )
        adapter = ObsidianAdapter()
        if adapter.resolve_binding(binding).status != "ok" or adapter.create_skeleton(binding).status != "ok":
            raise RuntimeError("ZSK Obsidian skeleton failed")
        intake = Stage5Intake(adapter)

        def source(name: str, text: str, role: str):
            result = intake.execute(IntakeRequest(task_id, binding, name, text.encode(), name, source_role=role))
            if result.record is None:
                raise RuntimeError(f"ZSK intake failed for {role}")
            return result.record

        knowledge_source = source("knowledge.txt", "确认需求后再形成书面方案。", "business_knowledge")
        method_source = source("method.txt", "先说顾虑，再给判断顺序。", "reference_method")
        profile_source = source("profile.txt", "中性主体的确认资料。", "profile_material")
        knowledge = Stage6Knowledge(adapter).execute(
            KnowledgeRequest(task_id, binding, knowledge_source, "客户需求确认流程", "客户交付流程", "确认需求后，再形成书面方案。")
        )
        method = Stage7Method(adapter).execute(
            MethodRequest(task_id, binding, method_source, "顾虑到判断的表达结构", "读者决策表达", "从读者顾虑切入", "先拆顾虑再给判断顺序", "用对比句说具体", "邀请读者自查", "把问题判断和行动连成短链")
        )
        profile = Stage8Profile(adapter).execute(
            ProfileRequest(task_id, binding, profile_source, "中性主体", ProfileLayers(("主体已确认当前业务范围。",), ("当前按已确认流程运营。",), ("候选素材须人工确认。",)))
        )
        if (knowledge.status, method.status, profile.status) != ("registered", "registered", "registered"):
            raise RuntimeError("ZSK 03/04/05 asset generation failed")
        root = Path(directory)
        knowledge_assets = search_knowledge_assets(root / "03-业务知识库", needs=["客户交付流程"])
        method_assets = search_method_assets(root / "04-内容方法库", query="读者决策表达")
        if len(knowledge_assets) != 1 or len(method_assets) != 1:
            raise RuntimeError("Content Slim did not retrieve ZSK assets")
        parsed = read_method_asset(root / "04-内容方法库", method_assets[0]["relative_path"])
        if parsed.asset_id != method.asset.asset_id:
            raise RuntimeError("ZSK method identity changed in Content Slim")
        read_primary_profile(root / "05-IP-Profile", {"status": "active", "is_primary": True})


def verify_no_generated_files() -> None:
    forbidden = [path for path in ROOT.rglob("*") if path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}]
    if forbidden:
        raise RuntimeError(f"generated Python files found: {forbidden}")


def main() -> int:
    verify_content()
    verify_zsk()
    verify_examples_and_cli()
    verify_zsk_delivery()
    verify_obsidian_bridge()
    verify_no_generated_files()
    print("PASS: Content Slim 5/34 + ZSK 5/28 + Obsidian bridge verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
