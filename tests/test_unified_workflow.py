"""Combined direction/platform behavior; all confirmations are synthetic fixtures."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from tests import test_direction_design as direction_cases
from tests.release_baseline.test_three_platform_publish_pack import platform_pack

api = direction_cases.api
SlimRuntimeError = direction_cases.SlimRuntimeError


class UnifiedWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.fixture = direction_cases.DirectionDesignTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.store, self.key, self.record, inp = f.start()
        result = direction_cases.model_result(inp, two=True, references=True)
        api.record_direction_result(store=self.store, task_key=self.key, analyzer_result=result)
        f.approve(self.store, self.key, 'compare')
        self.design = copy.deepcopy(result['direction_options'][1]['fused_direction']['writing_design'])
        context = f.context(self.record)
        api.record_context_result(registry_path=f.registry, runs_root=f.runs,
                                 task_record=self.record, context_result=context)
        self.args = dict(runs_root=f.runs, task_record=self.record)
        api.record_draft_result(**self.args, base_draft_version=0, writer_result={'paragraphs':[
            {'text':'团队用 AI 加快制作时，先核对输入、输出和检查人；制作和交接是两个环节。'},
            {'text':'对照同一项交付，分别核对制作时间和交接要求，再决定先改哪里，不预设工具的效果。'}]})

    def prepare(self):
        api.respond_draft(**self.args, decision='确认正文')
        handoff, _ = api.prepare_package_stage(**self.args)
        self.assertEqual(handoff['package_contract_version'], 'content-koubo-publish-pack-input-v2')
        self.assertEqual(handoff['target_platforms'], ['douyin', 'xiaohongshu', 'wechat_channels'])
        return handoff

    def save(self, pack, base=0, draft=1):
        api.record_package_result(**self.args, base_package_version=base, based_on_draft_version=draft,
                                  package_result=pack)
        return api.respond_package(**self.args, registry_path=self.fixture.registry, decision='确认并保存')[0]

    def test_new_direction_three_platform_save_and_scoped_revision_across_processes(self):
        with self.assertRaises(SlimRuntimeError):
            api.prepare_package_stage(**self.args)
        self.prepare()
        done = self.save(platform_pack())
        self.assertEqual(done['publish_status'], 'not_requested')
        first = self.store.read_fixed_json(self.key, 'saved_release_d1_p1.json')
        oral = Path(first['oral_path']).read_bytes()
        original_package = Path(first['package_path']).read_bytes()
        api.respond_package(**self.args, registry_path=self.fixture.registry, decision='需要修改',
            feedback='只改小红书正文', revision_scope=['xiaohongshu.publish_copy'])
        value = platform_pack(xhs_copy='把制作与交接分开核对，再按实际问题调整安排。')
        invalid = copy.deepcopy(value)
        invalid['platforms']['douyin']['title'] = '越过修改范围的标题'
        path = self.fixture.root / 'package.json'
        command = [sys.executable, '-B', str(Path(api.__file__)), 'record-package',
            '--runs-root', str(self.fixture.runs), '--task-record', self.record,
            '--base-package-version', '1', '--based-on-draft-version', '1', '--package-result', str(path)]
        path.write_text(json.dumps(invalid, ensure_ascii=False))
        rejected = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(rejected.returncode, 2, rejected.stdout)
        path.write_text(json.dumps(value, ensure_ascii=False))
        accepted = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        api.respond_package(**self.args, registry_path=self.fixture.registry, decision='确认并保存')
        second = self.store.read_fixed_json(self.key, 'saved_release_d1_p2.json')
        self.assertEqual(first['oral_path'], second['oral_path'])
        self.assertEqual(Path(first['oral_path']).read_bytes(), oral)
        self.assertEqual(Path(first['package_path']).read_bytes(), original_package)
        self.assertNotEqual(first['package_path'], second['package_path'])
        self.assertEqual(self.store.read_fixed_json(self.key, 'content_context_v1.json')['approved_direction']['writing_design'], self.design)
        stored = self.store.read_fixed_json(self.key, 'package_v2.json')['content']['platforms']
        self.assertEqual(stored['douyin'], platform_pack()['platforms']['douyin'])
        self.assertEqual(stored['wechat_channels'], platform_pack()['platforms']['wechat_channels'])

    def test_body_revision_preserves_design_and_rejects_old_package_binding(self):
        self.prepare(); self.save(platform_pack())
        first = self.store.read_fixed_json(self.key, 'saved_release_d1_p1.json')
        before = {p:Path(p).read_bytes() for p in (first['oral_path'], first['package_path'])}
        api.respond_draft(**self.args, decision='需要修改', feedback='把结尾缩短')
        api.record_draft_result(**self.args, base_draft_version=1, revision_feedback='把结尾缩短',
            writer_result={'paragraphs':[{'text':'把制作与交接分开看，核清输入、输出和检查人，再决定调整什么。'}]})
        api.respond_draft(**self.args, decision='确认正文')
        new_input, _ = api.prepare_package_stage(**self.args)
        self.assertEqual(new_input['approved_draft']['draft_version'], 2)
        with self.assertRaises(SlimRuntimeError):
            self.save(platform_pack(), base=1, draft=1)
        self.save(platform_pack(), base=1, draft=2)
        for path, data in before.items():
            self.assertEqual(Path(path).read_bytes(), data)
        self.assertEqual(self.store.latest_version(self.key, 'direction')[0], 1)
        self.assertEqual(self.store.read_fixed_json(self.key, 'content_context_v1.json')['approved_direction']['writing_design'], self.design)


if __name__ == '__main__':
    unittest.main()
