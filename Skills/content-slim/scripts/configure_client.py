#!/usr/bin/env python3
"""Preview, create, or reuse one explicit ZSK Obsidian binding."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from runtime.binding_setup import BindingSetupError, configure_zsk_binding


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Content Slim 一次持久绑定"
    )
    parser.add_argument("--registry", required=True)
    parser.add_argument("--runs-root", required=True)
    parser.add_argument("--vault-root", required=True)
    parser.add_argument("--client-id")
    parser.add_argument(
        "--speaker-mode",
        choices=("neutral", "company_brand", "personal_ip"),
        default="neutral",
    )
    parser.add_argument("--confirm-vault-root")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        response = configure_zsk_binding(
            registry_path=args.registry,
            runs_root=args.runs_root,
            vault_root=args.vault_root,
            client_id=args.client_id,
            speaker_mode=args.speaker_mode,
            confirmed_vault_root=args.confirm_vault_root,
        )
        exit_code = 0
    except BindingSetupError as exc:
        response = {
            "status": "blocked",
            "status_label": "知识库绑定未完成",
            "workflow_stage": "绑定本地知识库",
            "message": exc.message,
            "next_action": "按提示修正绑定条件后重新预检。",
            "run_exists": False,
            "run_created_now": False,
            "artifacts_exist": False,
            "artifacts_preserved": False,
        }
        exit_code = 2
    print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
