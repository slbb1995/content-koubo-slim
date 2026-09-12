#!/usr/bin/env python3
"""Verify a temporary installed ZSK Obsidian to Content Slim bridge."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "01a01e29-a6ba-73a2-82e6-4ad1caa0f33b"


def verify(zsk_root: Path) -> dict[str, object]:
    zsk_skills = zsk_root / "skills"
    if not (zsk_skills / "zsk-router" / "SKILL.md").is_file():
        raise RuntimeError("ZSK root is missing zsk-router")
    if not (zsk_skills / "shared" / "stage7_method.py").is_file():
        raise RuntimeError("ZSK root is missing shared runtime")
    sys.path.insert(0, str(zsk_skills))

    from shared.contracts import BINDING_SCHEMA, ROOT_KEYS, Binding
    from shared.obsidian_adapter import ObsidianAdapter
    from shared.stage5_intake import IntakeRequest, Stage5Intake
    from shared.stage6_knowledge import KnowledgeRequest, Stage6Knowledge
    from shared.stage7_method import MethodRequest, Stage7Method
    from shared.stage8_profile import (
        ProfileLayers,
        ProfileRequest,
        Stage8Profile,
    )
    from shared.templates import TEMPLATE_VERSION

    temporary_parent = (
        Path("/private/tmp")
        if Path("/private/tmp").is_dir()
        else Path(tempfile.gettempdir()).resolve()
    )
    with tempfile.TemporaryDirectory(
        prefix="zsk-content-bridge-", dir=temporary_parent
    ) as directory:
        parent = Path(directory)
        installed_skills = parent / "installed-skills"
        installed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "install.py"),
                "--dest",
                str(installed_skills),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if installed.returncode != 0:
            raise RuntimeError(
                f"Content install failed: {installed.stderr}"
            )
        content_skill_root = installed_skills / "content-slim"
        sys.path.insert(0, str(content_skill_root))

        from runtime.binding_setup import configure_zsk_binding
        from runtime.client_manifest import load_manifest
        from runtime.client_registry import load_registry, resolve_client
        from runtime.vault_reader import (
            read_method_asset,
            read_primary_profile,
        )
        from runtime.vault_search import (
            search_knowledge_assets,
            search_method_assets,
        )

        vault = parent / "vault"
        vault.mkdir(mode=0o700)
        host = parent / "host" / ".content-v2-slim"
        registry = host / "client-registry.json"
        runs = host / "runs"
        reference = parent / "reference.md"
        reference.write_text(
            "# 参考\n\n先说顾虑，再给判断顺序。\n",
            encoding="utf-8",
        )
        client_id = "CLT-BRIDGE001"
        binding = Binding(
            BINDING_SCHEMA,
            client_id,
            "桥接验收主体",
            "桥接验收知识库",
            "person",
            "obsidian",
            str(vault),
            {key: f"root:{key}" for key in ROOT_KEYS},
            TEMPLATE_VERSION,
        )
        adapter = ObsidianAdapter()
        if adapter.resolve_binding(binding).status != "ok":
            raise RuntimeError("ZSK binding resolution failed")
        if adapter.create_skeleton(binding).status != "ok":
            raise RuntimeError("ZSK skeleton creation failed")
        intake = Stage5Intake(adapter)

        def source(name: str, text: str, role: str):
            result = intake.execute(
                IntakeRequest(
                    TASK_ID,
                    binding,
                    name,
                    text.encode("utf-8"),
                    name,
                    source_role=role,
                )
            )
            if result.record is None:
                raise RuntimeError(f"ZSK intake failed for {role}")
            return result.record

        knowledge_source = source(
            "knowledge.txt",
            "确认需求后再形成书面方案。",
            "business_knowledge",
        )
        method_source = source(
            "method.txt",
            "先说顾虑，再给判断顺序。",
            "reference_method",
        )
        profile_source = source(
            "profile.txt",
            "桥接验收主体的确认资料。",
            "profile_material",
        )
        knowledge = Stage6Knowledge(adapter).execute(
            KnowledgeRequest(
                TASK_ID,
                binding,
                knowledge_source,
                "客户需求确认流程",
                "客户交付流程",
                "确认需求后，再形成书面方案。",
            )
        )
        method = Stage7Method(adapter).execute(
            MethodRequest(
                TASK_ID,
                binding,
                method_source,
                "顾虑到判断的表达结构",
                "读者决策表达",
                "从读者顾虑切入",
                "先拆顾虑再给判断顺序",
                "用对比句说具体",
                "邀请读者自查",
                "把问题判断和行动连成短链",
            )
        )
        profile = Stage8Profile(adapter).execute(
            ProfileRequest(
                TASK_ID,
                binding,
                profile_source,
                "桥接验收主体",
                ProfileLayers(
                    ("主体已确认当前业务范围。",),
                    ("当前按已确认流程运营。",),
                    ("候选素材须人工确认。",),
                ),
            )
        )
        if (
            knowledge.status,
            method.status,
            profile.status,
        ) != ("registered", "registered", "registered"):
            raise RuntimeError("ZSK 03/04/05 generation failed")

        knowledge_assets = search_knowledge_assets(
            vault / "03-业务知识库", needs=["客户交付流程"]
        )
        method_assets = search_method_assets(
            vault / "04-内容方法库", query="读者决策表达"
        )
        if len(knowledge_assets) != 1 or len(method_assets) != 1:
            raise RuntimeError("Content Slim did not retrieve ZSK 03/04")
        parsed_method = read_method_asset(
            vault / "04-内容方法库",
            method_assets[0]["relative_path"],
        )
        if parsed_method.asset_id != method.asset.asset_id:
            raise RuntimeError("ZSK method identity changed during read")
        read_primary_profile(
            vault / "05-IP-Profile",
            {"status": "active", "is_primary": True},
        )

        preview = configure_zsk_binding(
            registry_path=registry,
            runs_root=runs,
            vault_root=vault,
            client_id=client_id,
            speaker_mode="personal_ip",
        )
        if preview["status"] != "waiting" or registry.exists():
            raise RuntimeError("Content binding preview wrote or skipped Gate")
        configured = configure_zsk_binding(
            registry_path=registry,
            runs_root=runs,
            vault_root=vault,
            client_id=client_id,
            speaker_mode="personal_ip",
            confirmed_vault_root=str(vault),
        )
        if configured["status"] != "completed":
            raise RuntimeError("Content binding was not completed")
        loaded_registry = load_registry(registry)
        location = resolve_client(loaded_registry, client_id)
        load_manifest(location.manifest_path, expected_client_id=client_id)

        started = subprocess.run(
            [
                sys.executable,
                "-B",
                str(content_skill_root / "scripts" / "content_slim.py"),
                "start",
                "--registry",
                str(registry),
                "--runs-root",
                str(runs),
                "--client-id",
                client_id,
                "--speaker-mode",
                "personal_ip",
                "--topic-original",
                "如何先确认需求再给方案",
                "--reference",
                str(reference),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            started_payload = json.loads(started.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Content start returned invalid JSON: {started.stderr}"
            ) from exc
        if started.returncode != 0 or not started_payload.get(
            "run_created_now"
        ):
            raise RuntimeError(
                f"Content start failed after binding: {started_payload}"
            )
        if any(
            path.name == "approved_package.json"
            for path in runs.rglob("*")
        ):
            raise RuntimeError("Bridge test unexpectedly approved a package")
        if any(
            path.is_file()
            for path in (vault / "07-生产与反馈").rglob("*")
        ):
            raise RuntimeError("Bridge test unexpectedly created output files")

        reused = configure_zsk_binding(
            registry_path=registry,
            runs_root=runs,
            vault_root=vault,
            client_id=client_id,
            speaker_mode="personal_ip",
        )
        if reused["status"] != "completed":
            raise RuntimeError("Persisted binding was not reusable")

        return {
            "status": "passed",
            "zsk_assets": {"03": 1, "04": 1, "05": 1},
            "installed_copy_verified": True,
            "binding_preview_wrote": False,
            "binding_reused": True,
            "content_run_created": True,
            "output_files_created": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="验证独立 ZSK 与 Content Slim 的本地桥接"
    )
    parser.add_argument("--zsk-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify(args.zsk_root.resolve())
    except Exception as exc:
        print(
            json.dumps(
                {"status": "failed", "message": str(exc)},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
