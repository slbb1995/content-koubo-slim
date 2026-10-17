"""Synthetic workflow tests; decisions are fixtures, never real customer approvals."""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ('Skills' if (ROOT/'Skills/content-koubo-slim').is_dir() else 'skills/content-mainline')
SKILL = SKILLS / 'content-koubo-slim'
sys.path.insert(0, str(SKILL))
from scripts import content_koubo_slim as api
from runtime.content_source import plan_obsidian_configuration, apply_obsidian_configuration
from runtime.run_store import RunStore
from runtime.error_model import SlimRuntimeError
from runtime.schema_validation import (SOURCE_ROLE_POLICY, validate_analyzer_result,
    design_structure, build_gate_a, validate_writer_context)
from runtime.vault_search import discover_method_assets
from tests.release_baseline import test_content_source_v1 as base_fixtures
from tests.release_baseline.test_idea_first import direction as legacy_direction, material


def model_result(inp, two=False, references=False):
    old = legacy_direction(inp)
    if references:
        old['reference_analyses'] = [{'reference_id':'REF-001','content_value':'提供先区分现象再核对原因的组织方式',
            'hook_mechanism':'从读者遇到的落差进入','structure_mechanism':'区分现象后按依据检查',
            'transferable_points':['让核对动作回应开头问题'],'prohibited_transfers':['对标作者专属经历及数据']}]
        old['fused_direction']['external_reference_value']=['按条件逐步核对的推进方式']
        old['customer_readable_direction']['borrowed_value']=old['fused_direction']['external_reference_value']
    a=copy.deepcopy(old);a.pop('analysis_version');a.pop('reference_analyses')
    a['option_id']='diagnose'
    a['reference_usage']=[{'reference_id':ref['reference_id'],'adopted_value':'把症状与原因分开，再说明核对次序',
                          'application':'用于从审核负担进入并安排检查动作','not_used':'不采用另一条方案比较路线'} for ref in inp['references']]
    design={'angle':'员工交得更快，负责人为何仍反复审核；保留先核对原因的原意',
        'opening':'让负责人认出提交变快与审核负担增加的落差，并承诺给出核对顺序',
        'body_steps':[{'content':'先分清任务数量增加与单份返工增加','reason':'两种现象需要不同解释，不能直接归因工具',
                       'evidence':'目前没有客户数据，只提出应核对的记录'},
                      {'content':'选一条重复返工记录，对照交付要求与确认方式','reason':'在区分现象后提供可执行的核对动作',
                       'evidence':'以实际返工记录验证，不预设唯一原因'}],
        'ending':'回到这一项工作，先核清要求并约定怎样判断完成，再观察后续返工',
        'method_uses':[{'asset_id':'ORAL-GUIDE-001','application':'把开头问题、核对推进与收尾检查接起来'}],
        'evidence_boundary':'不编客户案例或提效比例，不把一个原因说成所有团队的根因'}
    a['fused_direction']['writing_design']=design
    a['fused_direction']['structure_plan']=design_structure(design)
    a['customer_readable_direction']['oral_structure']=design_structure(design)
    a['fused_direction']['target_audience']='需要审核团队交付的负责人'
    a['fused_direction']['core_promise']='分清审核负担增加的情况，给出一个核对动作'
    for k in ['target_audience','core_promise']:a['customer_readable_direction'][k]=a['fused_direction'][k]
    options=[a]
    if two:
        b=copy.deepcopy(a);b['option_id']='compare';d=b['fused_direction']['writing_design']
        d['angle']='在同一项交付中比较只加快制作与同时明确交接标准两种做法'
        d['opening']='让负责人知道两种安排解决的是不同环节'
        d['body_steps']=[{'content':'在共同交付要求下比较制作与交接两段工作的改变','reason':'统一标准后才有比较意义','evidence':'只讨论安排差异，不宣称已证实效果'}]
        d['ending']='按实际任务的瓶颈决定先改哪段，不宣布某种方式全面更好'
        b['fused_direction']['structure_plan']=design_structure(d);b['customer_readable_direction']['oral_structure']=design_structure(d)
        b['fused_direction']['core_promise']='根据任务条件选择需要调整的工作安排';b['customer_readable_direction']['core_promise']=b['fused_direction']['core_promise']
        for use in b['reference_usage']:use.update(adopted_value='比较不同环节的问题',application='仅用于对比两种工作安排',not_used='不采用诊断核对路线')
        options.append(b)
    return {'analysis_version':'slim-1.1','reference_analyses':old['reference_analyses'],
        'method_judgment':{'intent':inp['user_thoughts'] or '先检查实际原因，不预设工具无效','decision':'retain','reason':'原题已经指向具体审核问题，保持原意并补齐推进',
            'angles':[],'unused_methods_reason':'不额外加标杆、排名或性别元素，直接核对适合本题','material_gaps':['尚无实际返工记录'],
            'guidance_ids':['ORAL-GUIDE-001']},'direction_options':options,
        'recommended_option_id':'diagnose','recommendation_reason':'客户关注审核返工，先查原因更贴近原意'}


class DirectionDesignTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.vault=base_fixtures.ContentSourceV1Tests.make_vault(self.root)
        self.methods=self.vault/'04-内容方法库';self.registry=self.root/'registry.json';self.runs=self.root/'runs'
        plan=plan_obsidian_configuration(self.vault,registry_path=self.registry,client_id='synthetic-client')
        apply_obsidian_configuration(self.vault,confirmation=plan['confirmation'],registry_path=self.registry,client_id='synthetic-client')
        package=os.environ.get('ORAL_METHOD_PACKAGE')
        if package:
            src=Path(package);shutil.copytree(src/'口播结构',self.methods/'口播结构')
            self.guide=next(self.methods.rglob('06_从选题到全文_角度与结构使用指引.md'))
        else:
            self.guide=self.methods/'common-guide.md'
            self.guide.write_text('---\nasset_id: ORAL-GUIDE-001\nasset_version: "1.1.0"\ntype: oral_method\nmethod_kind: selection_guide\nstatus: active\naudience_scope: both\nkeywords: ["选题"]\nuse_when: ["方向判断"]\n---\n\n# 通用方法\n先判断原意，按需选择角度，设计开头、推进和完整收尾。\n')
        self.guidance={'relative_path':self.guide.relative_to(self.methods).as_posix(),
                       'page_sha256':hashlib.sha256(self.guide.read_bytes()).hexdigest(),'reason':'每次判断原意、切入、推进与收尾'}
        self.reference=self.root/'reference.md';self.reference.write_text('# 参考\n\n分析交付中的现象后，可提出检查依据与执行顺序。\n')
        self.request=dict(registry_path=self.registry,runs_root=self.runs,client_id=None,speaker_mode='neutral',
            topic_original='员工用 AI 提交更快，负责人审核负担反而增加',reference_paths=[self.reference],
            user_thoughts='先核对原因，不预设工具无效',must_keep=[],must_avoid=[],method_selections=[],planning_guidance=[self.guidance])

    def start(self, **kw):
        _,record=api.prepare_direction_stage(**{**self.request,**kw});store=RunStore(self.runs);key=store.resolve_task_record(record)
        return store,key,record,store.read_fixed_json(key,'analyzer_input_v1.json')

    def approve(self,store,key,option=None,version=1):
        return api.respond_direction(store=store,task_key=key,method_root=self.methods,decision='认可整版方向',selected_option_id=option,direction_version=version)

    def context(self,record):
        ci,_=api.prepare_context_stage(registry_path=self.registry,runs_root=self.runs,task_record=record)
        c={k:copy.deepcopy(ci[k]) for k in ['context_version','client_id','speaker_mode','approved_direction','selected_external_reference_mechanisms','writer_mode','secondary_tactics']}
        c.update(topic_original=ci['task_input']['topic_original'],target_audience=ci['approved_direction']['target_audience'],
            user_thoughts=ci['task_input']['user_thoughts'],must_keep=[],must_avoid=[],selected_04_content_assets=[],selected_04_method_assets=[],
            selected_03_business_assets=[],profile_context=None,source_role_policy=SOURCE_ROLE_POLICY)
        return c

    def test_missing_stale_or_wrong_version_guidance_creates_no_run(self):
        with self.assertRaises(SlimRuntimeError):self.start(planning_guidance=[])
        bad={**self.guidance,'page_sha256':'0'*64}
        with self.assertRaises(SlimRuntimeError):self.start(planning_guidance=[bad])
        self.guide.write_text(self.guide.read_text().replace('1.1.0','9.0.0'))
        bad={**self.guidance,'page_sha256':hashlib.sha256(self.guide.read_bytes()).hexdigest()}
        with self.assertRaises(SlimRuntimeError):self.start(planning_guidance=[bad])
        self.assertFalse(self.runs.exists())

    def test_retaining_original_with_no_angle_and_no_extra_structure_is_valid(self):
        store,key,record,inp=self.start();result=model_result(inp,references=True)
        validate_analyzer_result(result,inp);gate,_=api.record_direction_result(store=store,task_key=key,analyzer_result=result)
        self.assertEqual(len(gate['direction_options']),1);self.assertEqual(store.get_task(key)['state'],'direction_pending')
        with self.assertRaises(SlimRuntimeError):api.prepare_context_stage(registry_path=self.registry,runs_root=self.runs,task_record=record)
        self.approve(store,key);self.assertEqual(store.read_fixed_json(key,'approved_direction.json')['selected_option_id'],'diagnose')
        self.assertEqual(inp['planning_guidance'][0]['asset_version'],'1.1.0')

    def test_two_options_require_explicit_selection_and_current_version(self):
        store,key,record,inp=self.start();result=model_result(inp,two=True,references=True)
        api.record_direction_result(store=store,task_key=key,analyzer_result=result)
        for option,version in [(None,1),('invented',1),('compare',None),('compare',0)]:
            with self.assertRaises(SlimRuntimeError):self.approve(store,key,option,version)
        self.assertEqual(store.get_task(key)['state'],'direction_pending')
        self.approve(store,key,'compare');c=self.context(record)
        self.assertEqual(c['approved_direction']['writing_design'],result['direction_options'][1]['fused_direction']['writing_design'])
        self.assertIn('对比两种工作安排',''.join(c['selected_external_reference_mechanisms']))
        self.assertNotIn('用于从审核负担进入',''.join(c['selected_external_reference_mechanisms']))
        self.assertEqual(len(list(self.runs.glob('run-*/'))),1)

    def test_design_projection_unknown_material_and_missing_judgment_rejected(self):
        _,_,_,inp=self.start();good=model_result(inp,references=True)
        for mutate in [lambda r:r.pop('method_judgment'),lambda r:r['direction_options'][0]['fused_direction']['writing_design'].pop('ending'),
            lambda r:r['direction_options'][0]['fused_direction']['writing_design']['method_uses'][0].update(asset_id='UNREAD'),
            lambda r:r['direction_options'][0]['fused_direction']['structure_plan'].append('别的主题'),
            lambda r:r['method_judgment']['guidance_ids'].append('UNREAD'),
            lambda r:r['direction_options'][0].update(selected_method_assets=[{}])]:
            bad=copy.deepcopy(good);mutate(bad)
            with self.assertRaises(SlimRuntimeError):validate_analyzer_result(bad,inp)

    def test_guidance_alone_cannot_replace_a_blueprint(self):
        with self.assertRaises(SlimRuntimeError):self.start(reference_paths=[],method_selections=[])
        choice=material(self.methods);store,key,_,inp=self.start(reference_paths=[],method_selections=[choice])
        result=model_result(inp);api.record_direction_result(store=store,task_key=key,analyzer_result=result)
        self.assertEqual(result['reference_analyses'],[])

    def test_context_cannot_drop_or_rewrite_design(self):
        store,key,record,inp=self.start();result=model_result(inp,references=True)
        api.record_direction_result(store=store,task_key=key,analyzer_result=result);self.approve(store,key)
        good=self.context(record)
        for mutate in [lambda c:c['approved_direction'].pop('writing_design'),lambda c:c['approved_direction']['writing_design'].update(ending='换成工具推销')]:
            bad=copy.deepcopy(good);mutate(bad)
            with self.assertRaises(SlimRuntimeError):api.record_context_result(registry_path=self.registry,runs_root=self.runs,task_record=record,context_result=bad)
        api.record_context_result(registry_path=self.registry,runs_root=self.runs,task_record=record,context_result=good)
        bad=copy.deepcopy(good);bad['approved_direction']['writing_design']['ending']='静默换题'
        with self.assertRaises(SlimRuntimeError):validate_writer_context(bad,frozen_task=store.read_task_input(key),approved_snapshot=store.read_fixed_json(key,'approved_direction.json'))

    def test_changed_source_blocks_approval_and_p3(self):
        store,key,record,inp=self.start();api.record_direction_result(store=store,task_key=key,analyzer_result=model_result(inp,references=True))
        original=self.guide.read_bytes();self.guide.write_bytes(original+b'\nchanged')
        with self.assertRaises(SlimRuntimeError):self.approve(store,key)
        self.guide.write_bytes(original);self.approve(store,key);self.guide.write_bytes(original+b'\nchanged')
        with self.assertRaises(SlimRuntimeError):self.context(record)

    def test_direction_revision_keeps_judgment_and_rejects_stale_approval(self):
        store,key,record,inp=self.start();api.record_direction_result(store=store,task_key=key,analyzer_result=model_result(inp,references=True))
        api.respond_direction(store=store,task_key=key,method_root=self.methods,decision='需要修改',feedback='结尾只落一个核对动作')
        with self.assertRaises(SlimRuntimeError):self.approve(store,key,version=1)
        revised=store.read_fixed_json(key,'analyzer_input_v2.json');self.assertEqual(revised['analysis_version'],'slim-1.1')
        api.record_direction_result(store=store,task_key=key,analyzer_result=model_result(revised,references=True))
        with self.assertRaises(SlimRuntimeError):self.approve(store,key,version=1)
        self.approve(store,key,version=2)

    def test_legacy_run_is_resumable_without_new_guide_and_not_reused_as_new(self):
        store,key,record,inp=self.start(analysis_version='slim-1.0',planning_guidance=[])
        result=legacy_direction(inp);result['reference_analyses']=model_result(inp,references=True)['reference_analyses']
        api.record_direction_result(store=store,task_key=key,analyzer_result=result)
        api.respond_direction(store=store,task_key=key,method_root=self.methods,decision='认可整版方向')
        self.assertNotIn('writing_design',self.context(record)['approved_direction'])
        _,_,new_record,_=self.start();self.assertNotEqual(record,new_record)

    def test_new_default_cli_and_schema_contract(self):
        args=api.build_parser().parse_args(['start','--topic-original','测试']);self.assertEqual(args.analysis_version,'slim-1.1')
        plan=self.root/'selection.json';plan.write_text(json.dumps({'materials':[],'planning_guidance':[self.guidance]}))
        command=[sys.executable,str(SKILL/'scripts/content_koubo_slim.py'),'start','--registry',str(self.registry),'--runs-root',str(self.runs),
            '--topic-original',self.request['topic_original'],'--reference',str(self.reference),'--speaker-mode','neutral','--method-selection',str(plan)]
        done=subprocess.run(command,capture_output=True,text=True);self.assertEqual(done.returncode,0,done.stdout+done.stderr)
        response=json.loads(done.stdout);store=RunStore(self.runs);key=store.resolve_task_record(response['task_record']);inp=store.read_fixed_json(key,'analyzer_input_v1.json')
        result=model_result(inp,references=True)
        try:import jsonschema
        except ImportError:self.skipTest('jsonschema unavailable; runtime validation covered separately')
        for filename,value in [('analyzer-input.schema.json',inp),('analyzer-output.schema.json',result)]:
            schema=json.loads((SKILLS/'content-koubo-analyzer/schemas'/filename).read_text());jsonschema.Draft202012Validator.check_schema(schema);jsonschema.validate(value,schema)
        # Cross-process CLI handoff: the two-option gate cannot approve its recommendation by default.
        result=model_result(inp,two=True,references=True)
        output=self.root/'analyzer.json';output.write_text(json.dumps(result,ensure_ascii=False))
        script=[sys.executable,str(SKILL/'scripts/content_koubo_slim.py')]
        locator=['--runs-root',str(self.runs),'--task-record',response['task_record']]
        recorded=subprocess.run(script+['record-direction',*locator,'--analyzer-result',str(output)],capture_output=True,text=True)
        self.assertEqual(recorded.returncode,0,recorded.stdout+recorded.stderr)
        approval=['respond-direction',*locator,'--registry',str(self.registry),'--decision','认可整版方向','--direction-version','1']
        ambiguous=subprocess.run(script+approval,capture_output=True,text=True)
        self.assertNotEqual(ambiguous.returncode,0)
        chosen=subprocess.run(script+approval+['--selected-option','compare'],capture_output=True,text=True)
        self.assertEqual(chosen.returncode,0,chosen.stdout+chosen.stderr)
        prepared=subprocess.run(script+['prepare-context',*locator,'--registry',str(self.registry)],capture_output=True,text=True)
        self.assertEqual(prepared.returncode,0,prepared.stdout+prepared.stderr)
        self.assertEqual(json.loads(prepared.stdout)['context_input']['approved_direction']['writing_design'],
                         result['direction_options'][1]['fused_direction']['writing_design'])


    @unittest.skipUnless(os.environ.get('ORAL_METHOD_PACKAGE'), 'public package integration is an explicit local cross-repository check')
    def test_public_angle_guide_and_structure_reach_writer_together(self):
        detail=next(self.methods.rglob('07_八种切入角度及组合示例.md'))
        structure=next(self.methods.rglob('ORAL-STR-004_*.md'))
        def selection(path,reason):
            return dict(relative_path=path.relative_to(self.methods).as_posix(),page_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),reason=reason)
        store,key,record,inp=self.start(reference_paths=[],method_selections=[selection(structure,'先区分现象再核对原因')],
            planning_guidance=[self.guidance,selection(detail,'理解反差怎样接诊断推进，避免只有一句反问')])
        result=model_result(inp)
        result['method_judgment'].update(decision='refine',angles=['反差'],guidance_ids=['ORAL-GUIDE-001','ORAL-GUIDE-002'])
        result['direction_options'][0]['fused_direction']['writing_design']['method_uses'] += [
            {'asset_id':'ORAL-GUIDE-002','application':'用提交速度与审核负担之间的落差进入，不制造群体对立'},
            {'asset_id':'ORAL-STR-004','application':'区分现象和解释，再给核对动作与依据，不预设唯一原因'}]
        api.record_direction_result(store=store,task_key=key,analyzer_result=result);self.approve(store,key)
        context=self.context(record)
        ci,_=api.prepare_context_stage(registry_path=self.registry,runs_root=self.runs,task_record=record)
        source=ci['selected_04_assets'][0]
        context['selected_04_method_assets']=[{'asset_id':source['asset_id'],'relative_path':source['relative_path'],
            'source_role':'oral_method_asset','approved_usage':source['approved_usage'],'source_metadata':source['source_metadata'],
            'writer_context':'先把看到的变化分开，再基于实际记录决定从哪里检查；无法确认的原因作为核对问题，末尾说明下一次怎样观察。',
            'transfer_boundary':context['approved_direction']['generalization_boundary']}]
        api.record_context_result(registry_path=self.registry,runs_root=self.runs,task_record=record,context_result=context)
        writer,_=api.prepare_draft_stage(runs_root=self.runs,task_record=record)
        self.assertEqual([u['asset_id'] for u in context['approved_direction']['writing_design']['method_uses']],
            ['ORAL-GUIDE-001','ORAL-GUIDE-002','ORAL-STR-004'])
        self.assertTrue(any(i['asset_id']=='ORAL-GUIDE-002' and len(i['content'])>8000 for i in inp['planning_guidance']))
        found=discover_method_assets(self.methods)
        self.assertNotIn('ORAL-STR-007',{i['asset_id'] for i in found['items']})
        self.assertIn('ORAL-STR-007',{i['asset_id'] for i in discover_method_assets(self.methods,allow_experimental=True)['items']})

    def test_three_gate_save_and_body_revision_preserve_the_same_design(self):
        store,key,record,inp=self.start();result=model_result(inp,two=True,references=True)
        api.record_direction_result(store=store,task_key=key,analyzer_result=result);self.approve(store,key,'diagnose')
        context=self.context(record);api.record_context_result(registry_path=self.registry,runs_root=self.runs,task_record=record,context_result=context)
        writer,_=api.prepare_draft_stage(runs_root=self.runs,task_record=record)
        body={'paragraphs':[{'text':'员工交得快了，你却还在反复审核。先别急着判断工具没用，先分清是任务总量变多，还是同一份交付被反复退回。'},
            {'text':'可以挑一条重复返工的记录，对照当时的交付要求：要交给谁，用来做什么，做到哪一步算完成。没有记录支持，就先把这些当作核对问题。'},
            {'text':'先把这一项工作的要求和确认方式说清，再看下次返工发生在哪里。这样才知道接下来该改哪一处。'}]}
        api.record_draft_result(runs_root=self.runs,task_record=record,base_draft_version=0,writer_result=body)
        self.assertEqual(store.get_task(key)['state'],'draft_pending')
        with self.assertRaises(SlimRuntimeError):api.prepare_package_stage(runs_root=self.runs,task_record=record)
        api.respond_draft(runs_root=self.runs,task_record=record,decision='确认正文')
        pack={'cover_titles':['交得快为何还返工','先核清交付要求'],'publish_titles':['审核负担增加先查什么','交付变快之后还要核对什么','先分清任务变多还是反复返工'],
            'recommended_cover_title':'交得快为何还返工','recommended_publish_title':'审核负担增加先查什么',
            'publish_copy':'提交变快之后，审核负担增加的原因需要具体核对。先分清任务总量变化与同一份交付的反复修改，再找一条实际返工记录，核清交付要求和确认方式，不急着给工具下结论。',
            'tags':['#团队协作','#工作方法','#交付','#人工智能','#审核']}
        api.record_package_result(runs_root=self.runs,task_record=record,base_package_version=0,package_result=pack)
        self.assertEqual(store.get_task(key)['state'],'package_pending');self.assertEqual(list((self.vault/'07-生产与反馈').rglob('*.md')),[])
        done,_=api.respond_package(registry_path=self.registry,runs_root=self.runs,task_record=record,decision='确认并保存')
        self.assertEqual(done['publish_status'],'not_requested');self.assertEqual(store.get_task(key)['state'],'saved')
        self.assertEqual(len(list((self.vault/'07-生产与反馈').rglob('*.md'))),2)
        _,rev=api.respond_draft(runs_root=self.runs,task_record=record,decision='需要修改',feedback='把结尾再说短一点')
        self.assertEqual(store.latest_version(key,'direction')[0],1)
        self.assertEqual(store.read_fixed_json(key,'content_context_v1.json')['approved_direction']['writing_design'],result['direction_options'][0]['fused_direction']['writing_design'])
        if os.environ.get('KOUBO_DEMO_DIR'):
            dest=Path(os.environ['KOUBO_DEMO_DIR']);dest.mkdir(parents=True,exist_ok=True)
            for name in ['analyzer_input_v1.json','direction_v1.json','approved_direction.json','content_context_v1.json','draft_v1.md','package_v1.json']:
                shutil.copyfile(store.run_directory(key)/'artifacts'/name,dest/name)
            (dest/'README.md').write_text('合成教学样本，调用真实 Runtime 验证合同与状态。三个确认决定是测试夹具，不是客户真人确认；正文由固定教学样本提供，不是外部模型效果评测。\n')

if __name__=='__main__':unittest.main()
