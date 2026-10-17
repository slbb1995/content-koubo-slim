from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


FACTORY = Path(__file__).resolve().parents[2]
TOOLS = FACTORY / "tools"
if os.fspath(TOOLS) not in sys.path:
    sys.path.insert(0, os.fspath(TOOLS))

import content_koubo_slim_release as release


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


class P7SlimReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="content-koubo-slim-test-", dir=None))
        self.addCleanup(lambda: shutil.rmtree(self.temp, ignore_errors=True))
        self.factory = self.temp / "factory"
        self.factory.mkdir()
        (self.factory / "packages").mkdir()
        (self.factory / release.SELECTION_PATH).write_bytes(canonical({
            "schema_version": "workflow-skill-selection-v1",
            "package_id": "content-koubo-slim",
            "source_root": "Skills",
            "expected_skill_count": 5,
            "skills": list(release.EXPECTED_SKILLS),
        }))
        for skill in release.EXPECTED_SKILLS:
            root = self.factory / "Skills" / skill
            root.mkdir(parents=True)
            (root / "SKILL.md").write_text(f"---\nname: {skill}\n---\n", encoding="utf-8")
            (root / "agents").mkdir()
            (root / "agents" / "openai.yaml").write_text("interface: {}\n", encoding="utf-8")
        subprocess.run(["git", "init", "--quiet", os.fspath(self.factory)], check=True)
        subprocess.run(["git", "-C", os.fspath(self.factory), "config", "user.name", "P7 Test"], check=True)
        subprocess.run(["git", "-C", os.fspath(self.factory), "config", "user.email", "p7@example.invalid"], check=True)
        subprocess.run(["git", "-C", os.fspath(self.factory), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", os.fspath(self.factory), "commit", "--quiet", "-m", "fixture"],
            env={**os.environ, "GIT_AUTHOR_DATE": "2026-08-19T00:00:00+00:00", "GIT_COMMITTER_DATE": "2026-08-19T00:00:00+00:00"},
            check=True,
        )
        self.commit = subprocess.check_output(["git", "-C", os.fspath(self.factory), "rev-parse", "HEAD"], text=True).strip()

    def make_host(self) -> Path:
        host = self.temp / "host"
        host.mkdir()
        (host / "skills").mkdir()
        (host / ".content-workflow").mkdir()
        (host / ".content-workflow-host.json").write_bytes(canonical({"legacy": True}))
        (host / ".content-workflow" / "state.json").write_bytes(canonical({"legacy_release": "frozen"}))
        legacy = host / "skills" / "legacy-content-v1"
        legacy.mkdir()
        (legacy / "SKILL.md").write_text("legacy bytes\n", encoding="utf-8")
        return host

    def test_double_build_is_byte_identical_and_contains_only_five_skills(self) -> None:
        first = self.temp / "build-a"
        second = self.temp / "build-b"
        one = release.build(self.factory, self.commit, "1.5.0", first)
        two = release.build(self.factory, self.commit, "1.5.0", second)
        self.assertEqual(one, two)
        first_files = release.ordinary_files(first)
        second_files = release.ordinary_files(second)
        self.assertEqual(set(first_files), set(second_files))
        self.assertTrue(all(first_files[path].read_bytes() == second_files[path].read_bytes() for path in first_files))
        self.assertEqual({path.split("/")[1] for path in first_files if path.startswith("Skills/")}, set(release.EXPECTED_SKILLS))

    def test_backup_install_doctor_rollback_and_reinstall_preserve_legacy(self) -> None:
        package = self.temp / "package"
        release.build(self.factory, self.commit, "0.12.0-rc.1", package)
        host = self.make_host()
        legacy_before = (host / "skills/legacy-content-v1/SKILL.md").read_bytes()
        control_before = (host / ".content-workflow/state.json").read_bytes()
        backup = self.temp / "backup"
        backed_up = release.backup_host(host, package, backup)
        self.assertEqual(backed_up["preexisting_target_count"], 0)
        self.assertEqual(release.install(host, package, backup)["status"], "installed")
        self.assertEqual(release.doctor(host, package)["skill_count"], 5)
        (host / "skills/legacy-content-v1/independent-change.md").write_text(
            "unrelated host change\n", encoding="utf-8"
        )
        rolled_back = release.rollback(host, package, backup)
        self.assertEqual(rolled_back["status"], "rolled_back")
        self.assertTrue(rolled_back["unrelated_host_drift_observed"])
        self.assertTrue(all(not (host / "skills" / skill).exists() for skill in release.EXPECTED_SKILLS))
        self.assertEqual((host / "skills/legacy-content-v1/SKILL.md").read_bytes(), legacy_before)
        self.assertEqual((host / ".content-workflow/state.json").read_bytes(), control_before)
        self.assertEqual(release.install(host, package, backup)["status"], "installed")

    def test_content_koubo_slim_requires_a_new_real_user_turn_for_each_gate(self) -> None:
        skill_path = FACTORY / "Skills/content-koubo-slim/SKILL.md"
        skill_text = skill_path.read_text(encoding="utf-8")
        for requirement in (
            "必须立即结束当前 Assistant 轮次",
            "同一轮次禁止调用",
            "下一条真实用户消息",
            "不得代写、推断、预填",
        ):
            self.assertIn(requirement, skill_text)
        receipt = json.loads(
            (
                FACTORY
                / "designs/content-v2-slim/content-slim-skill-creator-receipt.json"
            ).read_text(encoding="utf-8")
        )
        design = FACTORY / "designs/content-v2-slim/content-slim-design-card.md"
        self.assertEqual(
            receipt["design_card_sha256"],
            release.sha256(design.read_bytes()),
        )
        self.assertRegex(
            receipt["structural_updates"][-1]["final_skill_sha256"], r"^[0-9a-f]{64}$"
        )

    def test_rc3_review_evidence_binds_six_redacted_turns_and_installed_constraint(self) -> None:
        state = json.loads((FACTORY / "project-state.json").read_text(encoding="utf-8"))
        p7 = state["p7_changes"]
        self.assertEqual(state["phase"]["review_status"], "passed")
        self.assertIn("P7", state["phase"]["passed_gates"])
        self.assertEqual(
            state["phase"]["next"],
            "mainline_pr_review_or_release_decision",
        )
        self.assertEqual(p7["final_review_verdict"], "PASS")
        self.assertEqual(
            p7["final_review_commit"],
            "2c284b708be34f016057530195bee2d82fbd09c4",
        )
        self.assertEqual(
            p7["final_review_session_ref"],
            "codex-session:01a0199f-2157-7a00-a66b-1b6034be53e9",
        )
        self.assertTrue(p7["mainline_pr_authorized"])
        self.assertFalse(p7["main_merged"])
        self.assertFalse(p7["tag_created"])
        self.assertFalse(p7["released"])
        self.assertEqual(
            p7["build_source_commit"],
            "2d77d82cdeaccdb2c0a3db63efe8b4eecb22cc0a",
        )
        self.assertEqual(p7["candidate_version"], "0.11.0-rc.3")
        self.assertEqual(p7["package_skill_count"], 5)
        self.assertEqual(p7["legacy_v1_runtime_dependency_count"], 0)
        self.assertEqual(p7["human_gate_constraint_delivery"], "installed_rc3_verified")
        self.assertEqual(
            p7["installed_content_slim_sha256"],
            "4c5c2505f75563163d76b3b6f4b4e828f67b4aee0119105f2154f610df732874",
        )

        review_evidence = (
            FACTORY / "designs/content-v2-slim/p7-release-install-evidence.md"
        ).read_text(encoding="utf-8")
        for value in (
            "最终独立 Review 结论：`PASS`",
            "2c284b708be34f016057530195bee2d82fbd09c4",
            "codex-session:01a0199f-2157-7a00-a66b-1b6034be53e9",
            "用户已明确授权进入主线 Draft PR 阶段",
        ):
            self.assertIn(value, review_evidence)

        evidence_path = FACTORY / p7["human_gate_evidence_path"]
        evidence = evidence_path.read_text(encoding="utf-8")
        self.assertEqual(
            p7["human_gate_evidence_sha256"],
            release.sha256(evidence_path.read_bytes()),
        )
        for value in (
            "| 1 | Assistant / 方向展示 | `993` |",
            "| 2 | User / 方向决定 | `1002` |",
            "`respond-direction` 仅在后续行 `1012` 调用",
            "| 3 | Assistant / 正文展示 | `1057` |",
            "| 4 | User / 正文决定 | `1064` |",
            "`respond-draft` 仅在后续行 `1074` 调用",
            "| 5 | Assistant / 配套展示 | `1088` |",
            "| 6 | User / 配套与保存决定 | `1095` |",
            "`respond-package` 仅在后续行 `1101` 调用",
            "run-20260819T014658.412810Z-89525c84",
            "run-20260819T042707.131601Z-e6c8ae07",
        ):
            self.assertIn(value, evidence)
        for private_marker in (
            "/Users/",
            "BAOXIAN-CLIENT",
            "朱梅燕",
            "百万医疗",
            "PROFILE-",
        ):
            self.assertNotIn(private_marker, evidence)


if __name__ == "__main__":
    unittest.main()
