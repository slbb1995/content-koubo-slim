"""Synthetic business regressions; confirmation inputs here are test fixtures only."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
STANDALONE = (ROOT / 'Skills/content-koubo-slim').is_dir()
SKILL = ROOT / ('Skills' if STANDALONE else 'skills/content-mainline') / 'content-koubo-slim'
sys.path.insert(0, str(SKILL))
from scripts import content_koubo_slim as api
from runtime.run_store import RunStore
from runtime.error_model import SlimRuntimeError
from runtime.schema_validation import SOURCE_ROLE_POLICY, validate_publish_pack_result


def pack():
    return {'cover_titles':['买完以后谁来帮','看得见的服务价值'],
        'publish_titles':['买完以后还有哪些帮助','怎样判断后续服务的价值','把服务说清楚再做选择'],
        'recommended_cover_title':'买完以后谁来帮','recommended_publish_title':'买完以后还有哪些帮助',
        'publish_copy':'先问清楚服务范围，再做选择。',
        'tags':['#服务价值','#客户体验','#售后服务','#沟通','#消费选择']}


class CustomerRepairTests(unittest.TestCase):
    def setUp(self):
        if STANDALONE:
            from test_idea_first import IdeaFirstTests, material, direction
            f=IdeaFirstTests();f.setUp();self.addCleanup(f.doCleanups)
            self.root,self.runs,self.registry,self.vault=f.root,f.runs,f.registry,f.vault
            store,key,record,inp=f.start([material(f.methods)])
            result=direction(inp)
            api.record_direction_result(store=store,task_key=key,analyzer_result=result)
            api.respond_direction(store=store,task_key=key,method_root=f.methods,decision='认可整版方向')
            ci,_=api.prepare_context_stage(registry_path=self.registry,runs_root=self.runs,task_record=record)
            context={k:ci[k] for k in ('context_version','client_id','speaker_mode','approved_direction','selected_external_reference_mechanisms','writer_mode','secondary_tactics')}
            context.update(topic_original=ci['task_input']['topic_original'],target_audience=ci['approved_direction']['target_audience'],
                user_thoughts=None,must_keep=[],must_avoid=[],selected_04_method_assets=[],selected_03_business_assets=[],profile_context=None,
                source_role_policy=SOURCE_ROLE_POLICY,selected_04_content_assets=[{
                'asset_id':'peer.md','relative_path':'peer.md','source_role':'peer_content_asset',
                'approved_usage':result['selected_method_assets'][0]['usage'],
                'source_metadata':ci['selected_04_assets'][0]['source_metadata'],
                'writer_context':'先说明具体顾虑，再逐项解释服务范围。',
                'transfer_boundary':result['fused_direction']['generalization_boundary']}])
            api.record_context_result(registry_path=self.registry,runs_root=self.runs,task_record=record,context_result=context)
        else:
            from tests.p4.test_content_koubo_writer_p4 import context_ready_run
            temp=tempfile.TemporaryDirectory(prefix='koubo-repair-',dir='/private/tmp' if Path('/private/tmp').is_dir() else None);self.addCleanup(temp.cleanup)
            self.root=Path(temp.name);self.runs=self.root/'runs'
            self.registry,record,key=context_ready_run(self.root)
            data=json.loads(self.registry.read_text());self.vault=Path(data['clients']['client-alpha']['vault_root'])
            store=RunStore(self.runs)
        self.store,self.key,self.record=store,key,record
        self.args={'runs_root':self.runs,'task_record':record}
        api.record_draft_result(**self.args,base_draft_version=0,writer_result={'paragraphs':[{'text':'先问清楚需要什么帮助，再判断服务范围。'}]})
        api.respond_draft(**self.args,decision='确认正文')

    def package(self,base=0):
        api.record_package_result(**self.args,base_package_version=base,package_result=pack(),based_on_draft_version=self.store.latest_version(self.key,"draft")[0])

    def save(self):
        return api.respond_package(**self.args,registry_path=self.registry,decision='确认并保存')[0]

    def revise(self,version=1):
        _,wi=api.respond_draft(**self.args,decision='需要修改',feedback='扩写，并补一句交流问题')
        self.assertEqual(wi['base_draft_version'],version)
        with self.assertRaises(SlimRuntimeError):api.prepare_package_stage(**self.args)
        with self.assertRaises(SlimRuntimeError):api.respond_draft(**self.args,decision='确认正文')
        api.record_draft_result(**self.args,base_draft_version=version,revision_feedback='扩写，并补一句交流问题',writer_result={'paragraphs':[{'text':f'第{version+1}版：先判断需要什么帮助，再逐项核对服务范围。你最在意哪一项？'}]})
        api.respond_draft(**self.args,decision='确认正文')

    def test_approved_draft_reopens_and_preserves_approval(self):
        path=self.store.run_directory(self.key)/'artifacts/approved_draft.json';old=path.read_bytes()
        self.revise();self.assertEqual(path.read_bytes(),old)
        self.assertEqual(api.prepare_package_stage(**self.args)[0]['approved_draft']['draft_version'],2)

    def test_package_pending_revises_without_reusing_stale_package(self):
        self.package();self.revise()
        wi,_=api.prepare_package_stage(**self.args)
        self.assertEqual(wi['base_package_version'],1);self.assertIsNone(wi['previous_package'])
        with self.assertRaises(SlimRuntimeError):self.save()
        self.package(1);self.assertEqual(self.save()['status'],'completed')

    def test_saved_run_revises_twice_and_old_files_stay_unchanged(self):
        self.package();self.save()
        previous={str(p):p.read_bytes() for p in self.vault.rglob('*.md')}
        for version in (1,2):
            self.revise(version);self.package(version);self.assertEqual(self.save()['publish_status'],'not_requested')
        for p,data in previous.items():self.assertEqual(Path(p).read_bytes(),data)
        self.assertEqual(len(list(self.vault.rglob('*-口播稿.md'))),3)
        self.assertEqual(len(list(self.vault.rglob('*-配套文案.md'))),3)
        self.assertTrue(any(self.vault.rglob('*第3版-口播稿.md')))

    def test_empty_revision_does_not_reopen_saved_state(self):
        self.package();self.save()
        with self.assertRaises(SlimRuntimeError):api.respond_draft(**self.args,decision='需要修改',feedback=' ')
        self.assertEqual(self.store.get_task(self.key)['state'],'saved')

    def test_stale_writer_version_cannot_be_saved(self):
        self.revise()
        with self.assertRaises(SlimRuntimeError):api.record_draft_result(**self.args,base_draft_version=1,revision_feedback='再次修改',writer_result={'paragraphs':[{'text':'过期结果'}]})

    def test_late_package_cannot_attach_to_newer_body(self):
        prepared,_=api.prepare_package_stage(**self.args)
        self.revise()
        for bound in (None, prepared['approved_draft']['draft_version']):
            with self.assertRaises(SlimRuntimeError):
                api.record_package_result(**self.args,base_package_version=0,package_result=pack(),based_on_draft_version=bound)
        self.assertFalse(any((self.store.run_directory(self.key)/'artifacts').glob('package_v*.json')))
        self.package();self.assertEqual(self.save()['status'],'completed')

    def test_variable_publish_description_and_explicit_first_request(self):
        value,_=api.prepare_package_stage(**self.args,revision_feedback='发布说明写成150字')
        self.assertEqual(value['revision_request'],'发布说明写成150字')
        for text in ['简短说明', '逐项核对服务范围。'*30]:
            value=pack();value['publish_copy']=text;self.assertEqual(validate_publish_pack_result(value)['publish_copy'],text)
        for text in ['', ' ', '文字\0错误']:
            value=pack();value['publish_copy']=text
            with self.assertRaises(SlimRuntimeError):validate_publish_pack_result(value)

    def test_cli_reexec_ignores_injected_pathlib_and_reads_existing_run(self):
        shim=self.root/'shim';shim.mkdir()
        (shim/'sitecustomize.py').write_text('from pathlib import Path\nPath.read_bytes=lambda *a,**k: (_ for _ in ()).throw(OSError("injected host hook"))\n')
        env=dict(os.environ,PYTHONPATH=str(shim),PYTHONDONTWRITEBYTECODE='1')
        p=subprocess.run([sys.executable,str(SKILL/'scripts/content_koubo_slim.py'),'status','--runs-root',str(self.runs),'--task-record',self.record],env=env,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr+p.stdout)
        self.assertTrue(json.loads(p.stdout)['run_exists'])

    def test_isolated_host_root_creates_no_other_host_state(self):
        host=self.root/'synthetic-host'
        # Missing task: diagnostic, not a new Run and not a fallback to another host.
        p=subprocess.run([sys.executable,str(SKILL/'scripts/content_koubo_slim.py'),'--host-root',str(host),'status','--task-record','missing'],capture_output=True,text=True)
        self.assertEqual(p.returncode,2,p.stderr+p.stdout)
        self.assertFalse((host/'.content-koubo-slim/runs/index.json').exists())

if __name__=='__main__':unittest.main()
