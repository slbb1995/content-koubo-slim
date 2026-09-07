from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

import test_content_source_v1 as fixtures

from runtime.content_source import plan_obsidian_configuration, apply_obsidian_configuration
from runtime.error_model import SlimRuntimeError
from runtime.reference_prep import preflight_references
from runtime.run_store import RunStore
from runtime.schema_validation import validate_analyzer_result, SOURCE_ROLE_POLICY
from runtime.vault_search import discover_method_assets, select_method_assets, search_method_assets
from scripts.content_koubo_slim import (prepare_direction_stage, record_direction_result,
    respond_direction, prepare_context_stage, record_context_result, build_parser,
    record_draft_result, respond_draft, record_package_result, respond_package)


def material(root, name='peer.md', *, kind='peer_content_asset', audience='consumer', maturity='historical_reference', body=None):
    text = (f'---\nasset_id: {name}\ntype: {kind}\nstatus: active\naudience_scope: {audience}\n'
            f'source_readable_sha256: {"1"*64}\n'
            f'maturity: {maturity}\nkeywords: ["服务价值"]\nuse_when: ["解释买完以后能得到什么帮助"]\n'
            '---\n\n# 内容组织参考\n\n' + (body or '先说购买后的顾虑，再说明需要了解的服务环节。'))
    path=root/name
    path.write_text(text, encoding='utf-8')
    return {'relative_path':name,'page_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'reason':'本题关注售后体验，采用顾虑与帮助配对的讲法'}


def direction(inp):
    chosen=[{**{k:c[k] for k in ('asset_id','asset_role','relative_path','page_sha256')},
             'usage':'从使用后的疑问切入，按解决问题的过程解释价值，再交代适用条件',
             'reason':'帮助读者判断购买后的服务是否有用'} for c in inp['method_candidates']]
    boundary={'user_thoughts':inp['user_thoughts'],'must_keep':inp['must_keep'],'must_avoid':inp['must_avoid']}
    fused={'target_audience':'需要理解售后帮助的消费者','core_promise':'说明怎样判断后续服务是否有价值',
           'external_reference_value':[],'structure_plan':['指出购买后仍会发生的问题','解释服务怎样回应这些问题','给出核对条件'],
           'conflicts':[],'user_boundaries':boundary,'generalization_boundary':'同行专属身份与结果不迁移，客户能力需另有资料'}
    return {'analysis_version':'slim-1.0','reference_analyses':[],'selected_method_assets':chosen,
        'fused_direction':fused,'content_goal':'explain','speaker_mode':inp['speaker_mode'],'writer_mode':'ganhuo',
        'writer_mode_reason':'解释判断依据','secondary_tactics':[],'business_context_needs':[],
        'customer_readable_direction':{'original_topic':inp['topic_original'],'target_audience':fused['target_audience'],
            'core_promise':fused['core_promise'],'borrowed_value':[],'method_asset_usage':[c['usage'] for c in chosen],
            'oral_structure':fused['structure_plan'],'user_boundaries':boundary,'speaker_mode_explanation':'一般性解释，不声明个人经历',
            'writer_recommendation':{'mode':'ganhuo','reason':'解释判断依据'},'generalization_boundary':fused['generalization_boundary']}}


class IdeaFirstTests(unittest.TestCase):
    def setUp(self):
        self.temp=fixtures.ContentSourceV1Tests().temporary_root();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.vault=fixtures.ContentSourceV1Tests.make_vault(self.root)
        self.methods=self.vault/'04-内容方法库'
        self.registry=self.root/'registry.json';self.runs=self.root/'runs'
        plan=plan_obsidian_configuration(self.vault,registry_path=self.registry,client_id='synthetic-client')
        apply_obsidian_configuration(self.vault,confirmation=plan['confirmation'],registry_path=self.registry,client_id='synthetic-client')

    def start(self, selections=None, references=None, guidance=None):
        _,record=prepare_direction_stage(registry_path=self.registry,runs_root=self.runs,
            client_id=None,speaker_mode='neutral',topic_original='购买以后到底还有谁提供帮助',
            reference_paths=references or [],user_thoughts=None,must_keep=[],must_avoid=[],
            method_selections=selections,planning_guidance=guidance,audience_scope='consumer')
        store=RunStore(self.runs);key=store.resolve_task_record(record)
        inp=json.loads((store.run_directory(key)/'artifacts/analyzer_input_v1.json').read_text())
        return store,key,record,inp

    def test_empty_external_references_are_not_fabricated(self):
        self.assertEqual(preflight_references([]),[])
        selection=material(self.methods)
        store,key,_,inp=self.start([selection])
        self.assertEqual(inp['references'],[])
        self.assertEqual(store.read_task_input(key)['source_mode'],'library')
        result=direction(inp)
        gate,_=record_direction_result(store=store,task_key=key,analyzer_result=result)
        self.assertEqual(store.get_task(key)['state'],'direction_pending')
        self.assertFalse((store.run_directory(key)/'artifacts/approved_direction.json').exists())

    def test_no_library_source_does_not_create_an_unbacked_run(self):
        with self.assertRaises(SlimRuntimeError): self.start()
        self.assertFalse(self.runs.exists())

    def test_semantic_selection_can_use_different_words_than_topic(self):
        s=material(self.methods)
        self.assertEqual(search_method_assets(self.methods,query='房子的前后体验'),[])
        found=discover_method_assets(self.methods,audience_scope='consumer')
        self.assertEqual(found['items'][0]['asset_id'],'peer.md')
        self.assertEqual(select_method_assets(self.methods,[s],audience_scope='consumer')[0]['asset_id'],'peer.md')

    def test_semantic_selection_is_scoped_and_hash_bound(self):
        s=material(self.methods)
        bad=copy.deepcopy(s);bad['relative_path']='../peer.md'
        with self.assertRaises(SlimRuntimeError): select_method_assets(self.methods,[bad])
        bad=copy.deepcopy(s);bad['page_sha256']='0'*64
        with self.assertRaises(SlimRuntimeError): select_method_assets(self.methods,[bad])
        with self.assertRaises(SlimRuntimeError): select_method_assets(self.methods,[s,s])

    def test_page_audience_beats_index_and_experiment_is_not_default(self):
        material(self.methods,'internal.md',audience='internal_sales_training')
        material(self.methods,'experiment.md',maturity='experimental_reference')
        result=discover_method_assets(self.methods,audience_scope='consumer')
        self.assertEqual(result['items'],[])
        self.assertEqual(result['excluded_total'],2)
        self.assertEqual(search_method_assets(self.methods,query='服务价值',audience_scope='consumer'),[])

    def test_guidance_can_be_read_but_is_not_a_peer_or_structure(self):
        s=material(self.methods,'guide.md',kind='oral_method')
        result=discover_method_assets(self.methods)
        self.assertEqual(result['items'][0]['method_kind'],'selection_guide')
        with self.assertRaises(SlimRuntimeError): select_method_assets(self.methods,[s])

    def test_long_peer_details_and_ending_survive_to_context_input(self):
        body=('需要观察服务发生在哪一步。\n\n'*180)+'## 适配结尾\n核对实际服务范围再解释。'
        s=material(self.methods,body=body)
        store,key,record,inp=self.start([s])
        self.assertIn('适配结尾',inp['method_candidates'][0]['excerpt'])
        result=direction(inp);record_direction_result(store=store,task_key=key,analyzer_result=result)
        # Synthetic fixture only: exercise deterministic state transitions, not a real human receipt.
        respond_direction(store=store,task_key=key,method_root=self.methods,decision='认可整版方向')
        ci,_=prepare_context_stage(registry_path=self.registry,runs_root=self.runs,task_record=record)
        self.assertIn('适配结尾',ci['selected_04_assets'][0]['source_excerpt'])
        context={k:ci[k] for k in ('context_version','client_id','speaker_mode','approved_direction','selected_external_reference_mechanisms','writer_mode','secondary_tactics')}
        context.update(topic_original=ci['task_input']['topic_original'],target_audience=ci['approved_direction']['target_audience'],
            user_thoughts=None,must_keep=[],must_avoid=[],selected_04_method_assets=[],selected_03_business_assets=[],profile_context=None,
            source_role_policy=SOURCE_ROLE_POLICY,selected_04_content_assets=[{
              'asset_id':'peer.md','relative_path':'peer.md','source_role':'peer_content_asset',
              'approved_usage':result['selected_method_assets'][0]['usage'],
              'source_metadata':ci['selected_04_assets'][0]['source_metadata'],
              'writer_context':'把需要帮助的具体时刻与能提供的支持一一对应，解释可观察的价值，最后给出核对实际范围的动作。',
              'transfer_boundary':result['fused_direction']['generalization_boundary']}])
        record_context_result(registry_path=self.registry,runs_root=self.runs,task_record=record,context_result=context)
        self.assertEqual(store.get_task(key)['state'],'context_ready')
        self.assertEqual(context['selected_04_content_assets'][0]['source_metadata']['maturity'],'historical_reference')
        self.assertNotIn('source_readable_sha256',context['selected_04_content_assets'][0]['source_metadata'])
        # Continue only the synthetic fixture through all three deterministic Gate transitions.
        record_draft_result(runs_root=self.runs,task_record=record,base_draft_version=0,
            writer_result={'paragraphs':[{'text':'买完以后，先想想哪些时候你还会需要帮助。遇到问题能否得到清楚的解释，比一句长期陪伴更容易判断。'}]})
        respond_draft(runs_root=self.runs,task_record=record,decision='确认正文')
        package={'cover_titles':['买完以后谁来帮','看得见的服务价值'],
            'publish_titles':['买完以后还有哪些帮助','怎样判断后续服务的价值','把服务说清楚再做选择'],
            'recommended_cover_title':'买完以后谁来帮','recommended_publish_title':'买完以后还有哪些帮助',
            'publish_copy':'购买不是体验的终点。遇到问题能不能得到清楚的解释，需要处理的时候知道找谁、需要准备什么，这些具体的事情，比一句长期陪伴更容易帮助我们判断服务有没有价值。',
            'tags':['#服务价值','#客户体验','#售后服务','#沟通','#消费选择']}
        record_package_result(runs_root=self.runs,task_record=record,base_package_version=0,package_result=package)
        completed,_=respond_package(registry_path=self.registry,runs_root=self.runs,task_record=record,decision='确认并保存')
        self.assertEqual(completed['status'],'completed')
        self.assertEqual(completed['publish_status'],'not_requested')
        self.assertEqual(len(list((self.vault/'07-生产与反馈').rglob('*.md'))),2)

    def test_oversize_material_is_explicit_not_silently_truncated(self):
        s=material(self.methods,body='资料'*7000)
        with self.assertRaisesRegex(SlimRuntimeError,'.*'): select_method_assets(self.methods,[s])

    def test_library_run_reuses_same_input_and_separates_changed_sources(self):
        s=material(self.methods)
        _,_,a,_=self.start([s]);_,_,b,_=self.start([s]);self.assertEqual(a,b)
        s=material(self.methods,body='新内容：先比较不同任务，再决定需要哪些支持。')
        _,_,c,_=self.start([s]);self.assertNotEqual(a,c)

    def test_drift_after_direction_blocks_context(self):
        s=material(self.methods);store,key,record,inp=self.start([s])
        record_direction_result(store=store,task_key=key,analyzer_result=direction(inp))
        respond_direction(store=store,task_key=key,method_root=self.methods,decision='认可整版方向')
        material(self.methods,body='changed')
        with self.assertRaises(SlimRuntimeError): prepare_context_stage(registry_path=self.registry,runs_root=self.runs,task_record=record)

    def test_no_reference_analysis_may_not_claim_external_borrowing(self):
        s=material(self.methods);_,_,_,inp=self.start([s]);out=direction(inp)
        out['fused_direction']['external_reference_value']=['假称来自客户对标']
        with self.assertRaises(SlimRuntimeError): validate_analyzer_result(out,inp)
        out=direction(inp);out['selected_method_assets']=[]
        with self.assertRaises(SlimRuntimeError): validate_analyzer_result(out,inp)

    def test_unreadable_explicit_reference_never_falls_back_to_library(self):
        s=material(self.methods)
        with self.assertRaises(SlimRuntimeError): self.start([s],[self.root/'missing.md'])
        self.assertFalse(self.runs.exists())

    def test_cli_accepts_an_idea_without_external_reference(self):
        args=build_parser().parse_args(['start','--topic-original','一段想法'])
        self.assertEqual(args.reference,[])

    def test_enhancement_alone_cannot_replace_a_content_blueprint(self):
        s=material(self.methods,'ORAL-ENH-test.md',kind='oral_method_asset')
        store,key,_,inp=self.start([s])
        with self.assertRaises(SlimRuntimeError):
            record_direction_result(store=store,task_key=key,analyzer_result=direction(inp))

    def test_malformed_actual_profile_still_blocks_configuration(self):
        other=self.root/'other';other.mkdir()
        vault=fixtures.ContentSourceV1Tests.make_vault(other)
        (vault/'05-IP-Profile'/'broken-person.md').write_text('# 缺少人物元数据',encoding='utf-8')
        with self.assertRaises(SlimRuntimeError):
            plan_obsidian_configuration(vault,registry_path=other/'registry.json',client_id='synthetic')
        self.assertFalse((other/'registry.json').exists())

    def test_planning_guidance_is_frozen_and_rechecked(self):
        s=material(self.methods)
        g=material(self.methods,'guide.md',kind='oral_method')
        store,key,record,inp=self.start([s],guidance=[g])
        self.assertEqual(inp['planning_guidance'][0]['page_sha256'],g['page_sha256'])
        record_direction_result(store=store,task_key=key,analyzer_result=direction(inp))
        respond_direction(store=store,task_key=key,method_root=self.methods,decision='认可整版方向')
        material(self.methods,'guide.md',kind='oral_method',body='新的选材边界')
        with self.assertRaises(SlimRuntimeError):
            prepare_context_stage(registry_path=self.registry,runs_root=self.runs,task_record=record)


if __name__=='__main__': unittest.main()
