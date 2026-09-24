"""Platform-pack v2 behavior over synthetic content; no publishing or traffic claims."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "Skills/content-koubo-slim"), str(ROOT / "tests")]

from runtime.error_model import SlimRuntimeError
from runtime.feishu_save import save_feishu_pair, save_feishu_package_revision
from runtime.feishu_source import FeishuRoot, FeishuSpace
from runtime.schema_validation import validate_publish_pack_result
from scripts import content_koubo_slim as api
import test_customer_repairs as customer_fixtures
from test_feishu_retained import FakeClient


def platform_pack(*, xhs_copy: str = "把判断步骤整理成可回看的简短清单。") -> dict:
    return {
        "contract_version": "content-koubo-publish-pack-result-v2",
        "platforms": {
            "douyin": {
                "title": "团队用 AI，先明确谁来检查",
                "publish_copy": "从会议纪要这类重复任务开始，先说清输入、输出和检查人，再决定工具。",
                "tags": ["#企业AI应用", "#会议纪要", "#团队协作"],
            },
            "xiaohongshu": {
                "title": "团队 AI 落地自查｜先定检查人",
                "publish_copy": xhs_copy,
                "tags": ["#企业AI应用", "#工作流程", "#团队管理", "#效率工具"],
            },
            "wechat_channels": {
                "title": "团队开始用 AI，检查环节定了吗？",
                "publish_copy": "适合正在尝试 AI 的团队：从一个重复任务开始，把输入、输出和人工核对安排进流程。",
                "tags": ["#企业AI应用", "#团队协作", "#工作方法"],
            },
        },
        "cover_texts": ["团队用 AI\n先定谁来检查", "AI 落地\n别漏掉人工核对"],
        "recommended_cover_text": "团队用 AI\n先定谁来检查",
    }


class ThreePlatformRunTests(unittest.TestCase):
    def setUp(self):
        fixture = customer_fixtures.CustomerRepairTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.args = fixture.args
        self.store = fixture.store
        self.key = fixture.key
        self.vault = fixture.vault
        self.registry = fixture.registry

    def record(self, value: dict, *, base: int, feedback=None, scope=None):
        return api.record_package_result(
            **self.args, base_package_version=base, package_result=value,
            revision_feedback=feedback, revision_scope=scope,
            based_on_draft_version=1,
        )

    def test_v2_contract_has_three_complete_groups_and_flexible_tags(self):
        value = validate_publish_pack_result(
            platform_pack(), target_platforms=("douyin", "xiaohongshu", "wechat_channels")
        )
        self.assertEqual(tuple(value["platforms"]), ("douyin", "xiaohongshu", "wechat_channels"))
        self.assertEqual(len(value["platforms"]["douyin"]["tags"]), 3)
        bad = platform_pack(); bad["platforms"]["douyin"]["tags"] = []
        with self.assertRaises(SlimRuntimeError):
            validate_publish_pack_result(bad, target_platforms=("douyin", "xiaohongshu", "wechat_channels"))

    def test_cli_carries_explicit_platform_and_field_scope(self):
        args = api.build_parser().parse_args([
            "prepare-package", "--task-record", "controlled",
            "--target-platform", "xiaohongshu",
            "--revision-scope", "xiaohongshu.publish_copy",
            "--feedback", "只改小红书正文",
        ])
        self.assertEqual(args.target_platform, ["xiaohongshu"])
        self.assertEqual(args.revision_scope, ["xiaohongshu.publish_copy"])

    def test_prepare_projects_context_but_keeps_body_as_fact_boundary(self):
        handoff, _ = api.prepare_package_stage(**self.args)
        self.assertEqual(handoff["package_contract_version"], "content-koubo-publish-pack-input-v2")
        self.assertEqual(handoff["writing_context"]["fact_boundary"], "approved_draft_only")
        self.assertEqual(handoff["writing_context"]["speaker_mode"], "neutral")
        self.assertIsNone(handoff["writing_context"]["voice_guidance"])
        self.assertNotIn("selected_03_business_assets", handoff)
        self.assertNotIn("profile_context", handoff)

    def test_initial_pair_then_package_only_revision_preserves_oral_and_old_package(self):
        self.record(platform_pack(), base=0)
        first, _ = api.respond_package(**self.args, registry_path=self.registry, decision="确认并保存")
        self.assertEqual(first["status"], "completed")
        artifacts = self.store.run_directory(self.key) / "artifacts"
        saved1 = self.store.read_fixed_json(self.key, "saved_release_d1_p1.json")
        oral_before = Path(saved1["oral_path"]).read_bytes()
        package_before = Path(saved1["package_path"]).read_bytes()

        _, handoff = api.respond_package(
            **self.args, registry_path=self.registry, decision="需要修改",
            feedback="只改小红书发布正文", revision_scope=["xiaohongshu.publish_copy"],
        )
        self.assertEqual(handoff["previous_package"], platform_pack())
        revised = platform_pack(xhs_copy="按输入、输出、检查人三步自查，方便团队保存后逐项核对。")
        self.record(revised, base=1, feedback="只改小红书发布正文",
                    scope=["xiaohongshu.publish_copy"])
        second, _ = api.respond_package(**self.args, registry_path=self.registry, decision="确认并保存")
        self.assertIn("原纯口播稿已核验复用", second["message"])
        saved2 = self.store.read_fixed_json(self.key, "saved_release_d1_p2.json")
        self.assertEqual(saved1["oral_path"], saved2["oral_path"])
        self.assertEqual(Path(saved1["oral_path"]).read_bytes(), oral_before)
        self.assertEqual(Path(saved1["package_path"]).read_bytes(), package_before)
        self.assertNotEqual(saved1["package_path"], saved2["package_path"])
        self.assertTrue(Path(saved2["package_path"]).name.endswith("配套文案-第2版.md"))
        self.assertTrue((artifacts / "approved_package.json").exists())
        self.assertTrue((artifacts / "approved_package_v2.json").exists())

    def test_scoped_revision_rejects_changes_to_other_platforms(self):
        self.record(platform_pack(), base=0)
        api.respond_package(**self.args, registry_path=self.registry, decision="需要修改",
            feedback="只改小红书正文", revision_scope=["xiaohongshu.publish_copy"])
        bad = platform_pack(xhs_copy="新版小红书正文")
        bad["platforms"]["douyin"]["title"] = "不应一起变化的抖音标题"
        with self.assertRaises(SlimRuntimeError):
            self.record(bad, base=1, feedback="只改小红书正文",
                        scope=["xiaohongshu.publish_copy"])


class ThreePlatformSaveTests(unittest.TestCase):
    def test_readable_samples_cover_three_industries_goals_and_modes_without_claiming_traffic(self):
        text = (ROOT / "examples/three-platform-synthetic-samples.md").read_text(encoding="utf-8")
        for value in ("保险知识解释", "企业 AI 落地观点", "家居服务转化说明",
                      "explain", "discuss", "convert", "neutral", "company_brand", "personal_ip"):
            self.assertIn(value, text)
        self.assertEqual(text.count("### 抖音"), 3)
        self.assertEqual(text.count("### 小红书"), 3)
        self.assertEqual(text.count("### 视频号"), 3)
        self.assertIn("不证明真实流量", text)
        enterprise = text.split("## 2. 企业 AI", 1)[1].split("## 3. 家居服务", 1)[0]
        home = text.split("## 3. 家居服务", 1)[1]
        for leaked in ("保单", "理赔", "百万医疗"):
            self.assertNotIn(leaked, enterprise)
            self.assertNotIn(leaked, home)

    def test_feishu_package_revision_reuses_verified_oral_and_retries_without_duplicates(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".three-platform-feishu-") as folder:
            client = FakeClient(); space = FeishuSpace("https://feishu.cn/wiki/space/123", "123", client)
            root = FeishuRoot(space, "output", "output")
            first = save_feishu_pair(
                output_root=root, output_template="YYYY/M/W", client_id="qa",
                selected_publish_title="稳定归档名", oral_body="合成正文",
                package_markdown="第一版三平台配套", receipt_dir=Path(folder) / "d1-p1",
                now=datetime(2026, 9, 24, tzinfo=timezone.utc),
            )
            second = save_feishu_package_revision(
                output_root=root, output_template="YYYY/M/W", client_id="qa",
                archive_title="稳定归档名", package_markdown="第二版三平台配套",
                verified_oral=first, receipt_dir=Path(folder) / "d1-p2",
                draft_version=1, package_version=2,
                now=datetime(2026, 10, 8, tzinfo=timezone.utc),
            )
            count = client.sequence
            again = save_feishu_package_revision(
                output_root=root, output_template="YYYY/M/W", client_id="qa",
                archive_title="稳定归档名", package_markdown="第二版三平台配套",
                verified_oral=first, receipt_dir=Path(folder) / "d1-p2",
                draft_version=1, package_version=2,
                now=datetime(2026, 11, 1, tzinfo=timezone.utc),
            )
            self.assertEqual(second, again)
            self.assertEqual(client.sequence, count)
            self.assertEqual(first["oral_ref"], second["oral_ref"])
            self.assertNotEqual(first["package_ref"], second["package_ref"])
            self.assertEqual(client.get_node(first["oral_ref"])["parent_node_token"],
                             client.get_node(second["package_ref"])["parent_node_token"])

    def test_local_package_revision_failure_cleans_owned_partial_and_retry_succeeds(self):
        from runtime.vault_save import save_markdown_pair, save_markdown_package_revision
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".three-platform-local-retry-") as folder:
            root = Path(folder); out = root / "out"; out.mkdir()
            first = save_markdown_pair(
                output_root=out, output_template="YYYY/M/W", client_id="qa",
                selected_publish_title="稳定归档名", oral_body="合成正文",
                package_markdown="第一版配套", receipt_dir=root / "d1-p1",
                now=datetime(2026, 9, 24, tzinfo=timezone.utc),
            )
            args = dict(output_root=out, output_template="YYYY/M/W", client_id="qa",
                archive_title="稳定归档名", package_markdown="第二版配套",
                verified_oral=first, receipt_dir=root / "d1-p2",
                draft_version=1, package_version=2,
                now=datetime(2026, 10, 8, tzinfo=timezone.utc))
            original_open = Path.open
            def fail_once(path, mode="r", *values, **kwargs):
                handle = original_open(path, mode, *values, **kwargs)
                if mode != "xb" or not path.name.endswith("配套文案-第2版.md"):
                    return handle
                class Failing:
                    def __enter__(self): handle.__enter__(); return self
                    def __exit__(self, *exc): return handle.__exit__(*exc)
                    def __getattr__(self, name): return getattr(handle, name)
                    def write(self, value): handle.write(value[:2]); raise OSError("injected partial write")
                return Failing()
            with patch.object(Path, "open", fail_once), self.assertRaises(SlimRuntimeError):
                save_markdown_package_revision(**args)
            self.assertFalse(any(out.rglob("*配套文案-第2版.md")))
            saved = save_markdown_package_revision(**args)
            self.assertTrue(saved["package_path"].exists())
            self.assertEqual(saved["oral_path"], first["oral_path"])
            self.assertEqual(saved["package_path"].parent, first["oral_path"].parent)

    def test_feishu_acknowledged_package_revision_failure_retries_without_duplicate(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".three-platform-feishu-retry-") as folder:
            client = FakeClient(); space = FeishuSpace("https://feishu.cn/wiki/space/123", "123", client)
            root = FeishuRoot(space, "output", "output")
            first = save_feishu_pair(output_root=root, output_template="weekly", client_id="qa",
                selected_publish_title="稳定归档名", oral_body="合成正文",
                package_markdown="第一版配套", receipt_dir=Path(folder) / "d1-p1")
            original = client.create_document
            failed = [False]
            def acknowledged(parent, title, body):
                node = original(parent, title, body)
                if title.endswith("配套文案-第2版") and not failed[0]:
                    failed[0] = True
                    exc = SlimRuntimeError("SLIM_SAVE_FAILED", "fake", detail="acknowledged interruption")
                    exc.received_refs = node
                    raise exc
                return node
            args = dict(output_root=root, output_template="weekly", client_id="qa",
                archive_title="稳定归档名", package_markdown="第二版配套",
                verified_oral=first, receipt_dir=Path(folder) / "d1-p2",
                draft_version=1, package_version=2)
            with patch.object(client, "create_document", acknowledged), self.assertRaises(SlimRuntimeError):
                save_feishu_package_revision(**args)
            count = client.sequence
            saved = save_feishu_package_revision(**args)
            self.assertEqual(client.sequence, count)
            self.assertEqual(saved["oral_ref"], first["oral_ref"])

    def test_same_archive_name_batch_suffixes_do_not_collide(self):
        from runtime.vault_save import save_markdown_pair
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".three-platform-batch-") as folder:
            root = Path(folder); out = root / "out"; out.mkdir()
            suffixes = ["a-" + "1" * 32, "b-" + "2" * 32]
            saved = [save_markdown_pair(
                output_root=out, output_template="weekly", client_id="qa",
                selected_publish_title="同名主题", oral_body="合成正文 " + suffix,
                package_markdown="三平台合成配套", item_suffix=suffix,
            ) for suffix in suffixes]
            self.assertNotEqual(saved[0]["oral_path"], saved[1]["oral_path"])
            self.assertEqual(len(list(out.rglob("*.md"))), 4)


if __name__ == "__main__":
    unittest.main()
