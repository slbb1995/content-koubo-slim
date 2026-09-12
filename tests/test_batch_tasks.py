"""Batch business regressions. All Gate decisions are synthetic test fixtures."""
import copy
import json
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
STANDALONE = (ROOT / 'Skills/content-koubo-slim').is_dir()
sys.path.insert(0, str(ROOT / ('Skills' if STANDALONE else 'skills/content-mainline') / 'content-koubo-slim'))
from scripts import content_koubo_slim as api
from runtime.batch_tasks import start_request, batch_status
from runtime.run_store import RunStore
from runtime.error_model import SlimRuntimeError
from runtime.schema_validation import SOURCE_ROLE_POLICY
if STANDALONE:
    from test_customer_repairs import pack
else:
    from tests.test_customer_repairs import pack


class BatchTests(unittest.TestCase):
    def setUp(self):
        if STANDALONE:
            from test_idea_first import IdeaFirstTests, material
            f = IdeaFirstTests(); f.setUp(); self.addCleanup(f.doCleanups)
            self.root, self.registry, self.vault, self.methods = f.root, f.registry, f.vault, f.methods
            extra = {'method_selections': [material(f.methods)], 'audience_scope':'consumer'}
            refs = []; client = None
        else:
            from tests.p2.test_content_koubo_analyzer_p2 import write_fixture, write_references
            from tests.p3.test_content_koubo_context_p3 import write_p3_assets
            temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
            self.root = Path(temp.name).resolve(); self.registry, self.vault = write_fixture(self.root)
            write_p3_assets(self.vault)
            refs = write_references(self.root, 2); client = 'client-alpha'
            self.methods = self.vault / 'authorized-methods'; extra = {}
        self.runs = self.root / 'batch-runs'
        self.request = dict(registry_path=self.registry, runs_root=self.runs, client_id=client,
            speaker_mode='neutral', topic_original='普通家庭做保险选择前，先问哪几个问题？',
            reference_paths=refs, user_thoughts=None, must_keep=[], must_avoid=[], **extra)
        self.plan = {'batch_id':str(uuid4()), 'output_count':2,
            'items':[{'item_id':'item-1','user_thoughts':'先从具体顾虑切入'}, {'item_id':'item-2','user_thoughts':'先从日常判断切入'}]}
        self.path = self.root / 'batch-plan.json'

    def start(self):
        self.path.write_text(json.dumps(self.plan, ensure_ascii=False))
        return start_request(api.prepare_direction_stage, self.request, output_count=self.plan['output_count'], plan_path=self.path)

    def finish(self, record):
        store=RunStore(self.runs); key=store.resolve_task_record(record)
        inp=store.read_fixed_json(key,'analyzer_input_v1.json')
        if STANDALONE:
            from test_idea_first import direction
            result=direction(inp)
        else:
            from tests.p2.test_content_koubo_analyzer_p2 import analyzer_result
            result=analyzer_result(inp)
        api.record_direction_result(store=store,task_key=key,analyzer_result=result)
        api.respond_direction(store=store,task_key=key,method_root=self.methods,decision='认可整版方向')
        ci,_=api.prepare_context_stage(registry_path=self.registry,runs_root=self.runs,task_record=record)
        if STANDALONE:
            context={k:ci[k] for k in ('context_version','client_id','speaker_mode','approved_direction','selected_external_reference_mechanisms','writer_mode','secondary_tactics')}
            context.update(topic_original=ci['task_input']['topic_original'],target_audience=ci['approved_direction']['target_audience'],
                user_thoughts=ci['task_input']['user_thoughts'],must_keep=[],must_avoid=[],selected_04_method_assets=[],selected_03_business_assets=[],profile_context=None,
                source_role_policy=SOURCE_ROLE_POLICY,selected_04_content_assets=[{
                'asset_id':'peer.md','relative_path':'peer.md','source_role':'peer_content_asset',
                'approved_usage':result['selected_method_assets'][0]['usage'],
                'source_metadata':ci['selected_04_assets'][0]['source_metadata'],
                'writer_context':'先说明具体顾虑，再逐项解释服务范围。',
                'transfer_boundary':result['fused_direction']['generalization_boundary']}])
        else:
            from tests.p3.test_content_koubo_context_p3 import context_result
            context=context_result(ci)
        api.record_context_result(registry_path=self.registry,runs_root=self.runs,task_record=record,context_result=context)
        args={'runs_root':self.runs,'task_record':record}
        api.record_draft_result(**args,base_draft_version=0,writer_result={'paragraphs':[{'text':'先问清需求，核对实际服务范围，再判断哪些帮助适合自己。'}]})
        api.respond_draft(**args,decision='确认正文')
        api.record_package_result(**args,base_package_version=0,package_result=pack(),based_on_draft_version=1)
        api.respond_package(**args,registry_path=self.registry,decision='确认并保存')
        return key

    def test_single_run_does_not_depend_on_batch_receipt(self):
        response=start_request(api.prepare_direction_stage,self.request)
        original=RunStore.write_fixed_json
        def forbid_receipt(store,key,name,payload):
            if name.startswith('saved_pair_'):raise AssertionError('single Run gained batch receipt dependency')
            return original(store,key,name,payload)
        with patch.object(RunStore,'write_fixed_json',forbid_receipt):
            key=self.finish(response['task_record'])
        self.assertEqual(RunStore(self.runs).get_task(key)['state'],'saved')

    def test_receipt_cannot_count_paths_outside_output_or_with_parent_segments(self):
        record=self.start()['items'][0]['task_record'];key=self.finish(record);store=RunStore(self.runs)
        receipt_path=store.run_directory(key)/'artifacts/saved_pair_v1.json'
        original=json.loads(receipt_path.read_text());saved=Path(original['oral_path'])
        outside=self.vault/'outside-output.md';outside.write_bytes(saved.read_bytes())
        for unsafe in (str(outside),str(saved.parent/'..'/saved.parent.name/saved.name)):
            receipt={**original,'oral_path':unsafe};receipt_path.write_text(json.dumps(receipt))
            status=batch_status(store,self.plan['batch_id']);self.assertEqual(status['saved_count'],0)
        receipt_path.write_text(json.dumps(original))
        self.assertEqual(batch_status(store,self.plan['batch_id'])['saved_count'],1)

    def test_count_without_plan_rejected_before_any_run(self):
        for count in (0,2,10,True):
            with self.assertRaises(SlimRuntimeError):
                start_request(api.prepare_direction_stage,self.request,output_count=count)
            with self.assertRaises(SlimRuntimeError):
                api.prepare_direction_stage(**self.request,output_count=count)
        self.assertFalse(self.runs.exists())

    def test_malformed_or_duplicate_plan_does_not_create_partial_batch(self):
        original=copy.deepcopy(self.plan)
        for mutate in (lambda p:p.update(output_count=3),lambda p:p['items'][1].update(item_id='item-1'),lambda p:p['items'][1].update(user_thoughts=3)):
            self.plan=copy.deepcopy(original);mutate(self.plan)
            with self.assertRaises(SlimRuntimeError):self.start()
            self.assertFalse(self.runs.exists())

    def test_invalid_later_item_preflight_leaves_no_actual_batch(self):
        real=api.prepare_direction_stage
        def prepare(**kw):
            if kw['batch_item']['item_id']=='item-2':raise SlimRuntimeError('SLIM_ANALYZER_INPUT_INVALID','test')
            return real(**kw)
        self.path.write_text(json.dumps(self.plan))
        with self.assertRaises(SlimRuntimeError):start_request(prepare,self.request,output_count=2,plan_path=self.path)
        self.assertFalse(self.runs.exists())

    def test_ten_identical_topics_have_distinct_resumable_runs(self):
        self.plan['output_count']=10
        self.plan['items']=[{'item_id':f'item-{i}'} for i in range(10)]
        result=self.start(); self.assertEqual(result['saved_count'],0)
        records=[i['task_record'] for i in result['items']]
        self.assertEqual(len(set(records)),10)
        self.assertEqual(records,[i['task_record'] for i in self.start()['items']])
        self.assertTrue(all(i['state'] not in ('draft_approved','saved') for i in result['items']))

    def test_changed_plan_or_binding_cannot_reuse_batch(self):
        self.start(); self.plan['items'][0]['user_thoughts']='更改已冻结计划'
        with self.assertRaises(SlimRuntimeError):self.start()
        self.plan['items'][0]['user_thoughts']='先从具体顾虑切入'
        self.request['speaker_mode']='company_brand'
        with self.assertRaises(SlimRuntimeError):self.start()

    def test_interrupted_initialization_resumes_existing_runs(self):
        real=api.prepare_direction_stage; self.path.write_text(json.dumps(self.plan))
        def interrupted(**kw):
            if Path(kw['runs_root'])==self.runs and kw['batch_item']['item_id']=='item-2':raise OSError('simulated interruption')
            return real(**kw)
        with self.assertRaises(OSError):start_request(interrupted,self.request,output_count=2,plan_path=self.path)
        result=batch_status(RunStore(self.runs),self.plan['batch_id'])
        self.assertEqual(result['status'],'working');self.assertEqual(result['saved_count'],0)
        result=self.start();self.assertEqual(len({i['task_record'] for i in result['items']}),2)

    def test_cli_requires_plan_and_exposes_independent_records(self):
        script=Path(api.__file__)
        command=[sys.executable, '-I', '-S', '-B', str(script), 'start', '--registry', str(self.registry),
            '--runs-root', str(self.runs), '--speaker-mode', 'neutral', '--topic-original', self.request['topic_original'],
            '--output-count', '2']
        for path in self.request['reference_paths']:command += ['--reference', str(path)]
        if self.request['client_id']:command += ['--client-id', self.request['client_id']]
        if STANDALONE:
            selection=self.root/'selection.json';selection.write_text(json.dumps(self.request['method_selections']))
            command += ['--method-selection', str(selection), '--audience-scope','consumer']
        rejected=subprocess.run(command,capture_output=True,text=True)
        self.assertNotEqual(rejected.returncode,0);self.assertFalse(self.runs.exists())
        self.path.write_text(json.dumps(self.plan))
        accepted=subprocess.run(command+['--batch-plan',str(self.path)],capture_output=True,text=True)
        self.assertEqual(accepted.returncode,0,accepted.stdout+accepted.stderr)
        response=json.loads(accepted.stdout);self.assertEqual(response['output_count'],2)
        self.assertEqual(len(set(i['task_record'] for i in response['items'])),2)

    def test_saved_revision_reopens_only_its_item(self):
        result=self.start();a,b=[i['task_record'] for i in result['items']]
        self.finish(a);self.finish(b)
        args={'runs_root':self.runs,'task_record':a}
        api.respond_draft(**args,decision='需要修改',feedback='补一句自然交流')
        status=batch_status(RunStore(self.runs),self.plan['batch_id'])
        self.assertEqual(status['saved_count'],1);self.assertEqual(status['items'][1]['state'],'saved')
        api.record_draft_result(**args,base_draft_version=1,revision_feedback='补一句自然交流',
            writer_result={'paragraphs':[{'text':'先问清需求，核对实际服务范围。你通常先看哪些条件？'}]})
        api.respond_draft(**args,decision='确认正文')
        api.record_package_result(**args,base_package_version=1,package_result=pack(),based_on_draft_version=2)
        api.respond_package(**args,registry_path=self.registry,decision='确认并保存')
        self.assertEqual(batch_status(RunStore(self.runs),self.plan['batch_id'])['saved_count'],2)
        self.assertEqual(len(list(self.vault.rglob('*-口播稿.md'))),3)

    def test_post_save_receipt_failure_can_resume_without_overwrite(self):
        result=self.start();record=result['items'][0]['task_record']
        original=RunStore.write_fixed_json
        def interrupted(store,key,name,payload):
            if name.startswith('saved_pair_'):raise SlimRuntimeError('SLIM_VERSION_WRITE_FAILED','test')
            return original(store,key,name,payload)
        with patch.object(RunStore,'write_fixed_json',interrupted):
            with self.assertRaises(SlimRuntimeError):self.finish(record)
        self.assertEqual(batch_status(RunStore(self.runs),self.plan['batch_id'])['saved_count'],0)
        old={str(p):p.read_bytes() for p in self.vault.rglob('*-口播稿.md')}
        api.respond_package(runs_root=self.runs,task_record=record,registry_path=self.registry,decision='确认并保存')
        self.assertEqual(batch_status(RunStore(self.runs),self.plan['batch_id'])['saved_count'],1)
        for path,data in old.items():self.assertEqual(Path(path).read_bytes(),data)

    def test_independent_gates_same_titles_and_verified_saved_count(self):
        result=self.start();a,b=[i['task_record'] for i in result['items']]
        key=self.finish(a);store=RunStore(self.runs)
        status=batch_status(store,self.plan['batch_id']);self.assertEqual(status['saved_count'],1)
        self.assertNotEqual(status['items'][1]['state'],'saved')
        self.finish(b);status=batch_status(store,self.plan['batch_id'])
        self.assertEqual(status['status'],'completed');self.assertEqual(status['saved_count'],2)
        files=list(self.vault.rglob('*-口播稿.md'));self.assertEqual(len(files),2)
        # Distinct item identity does not reuse draft_version or the selected title.
        self.assertTrue(all(store.latest_version(store.resolve_task_record(r),'draft')[0]==1 for r in (a,b)))
        files[0].write_text('external edit')
        status=batch_status(store,self.plan['batch_id']);self.assertEqual(status['saved_count'],1)
        self.assertEqual(status['status'],'working')
        files[1].unlink();self.assertEqual(batch_status(store,self.plan['batch_id'])['saved_count'],0)

if __name__ == '__main__':unittest.main()
