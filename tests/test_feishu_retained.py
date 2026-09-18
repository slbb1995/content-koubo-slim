"""Offline backend contract tests, never a claim of live Feishu acceptance."""
from pathlib import Path
from types import SimpleNamespace
import json,os,subprocess,sys,tempfile,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Skills/content-koubo-slim'))
from runtime.feishu_source import FeishuSpace,FeishuRoot,assert_below
from runtime.feishu_save import save_feishu_pair
from runtime.feishu_binding import resolve_feishu_binding
from runtime.feishu_client import _lark_command
from runtime.error_model import SlimRuntimeError

class FakeClient:
    def __init__(self):
        self.nodes={}; self.bodies={}; self.sequence=0; self.fail_package=None
        for token in ('knowledge','content','profiles','workflow','output'):
            self.add(token,'',token,'# '+token+'\n')
    def add(self,token,parent,title,body):
        node=dict(space_id='123',node_token=token,obj_token='obj'+token,parent_node_token=parent,title=title,obj_type='docx',node_type='origin',has_child=False)
        self.nodes[token]=node; self.bodies[node['obj_token']]=body
        return dict(node)
    def get_node(self,ref):
        for n in self.nodes.values():
            if ref in (n['node_token'],n['obj_token']): return dict(n)
        raise AssertionError('unknown fake ref '+ref)
    def fetch_markdown(self,ref): return self.bodies[self.get_node(ref)['obj_token']]
    def list_children(self,space,parent): return [dict(n) for n in self.nodes.values() if n['parent_node_token']==parent]
    def create_document(self,parent,title,body):
        self.sequence+=1
        node=self.add('new'+str(self.sequence),parent,title,body)
        if self.fail_package and title.endswith('配套文案'):
            mode=self.fail_package; self.fail_package=None
            exc=SlimRuntimeError('SLIM_SAVE_FAILED','fake',detail='injected create interruption')
            if mode=='acknowledged': exc.received_refs=node
            raise exc
        return node

class FeishuRetainedTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT,prefix='.feishu-')
        self.addCleanup(self.tmp.cleanup)
        self.client=FakeClient(); self.space=FeishuSpace('https://feishu.cn/wiki/space/123','123',self.client)
        self.args=dict(output_root=FeishuRoot(self.space,'output','output'),output_template='weekly',client_id='qa',selected_publish_title='保存测试标题',oral_body='合成口播正文',package_markdown='合成配套正文',receipt_dir=Path(self.tmp.name)/'receipt')
    def test_native_binding_resolves_without_local_mirror(self):
        binding=dict(binding_id='BND-1234567890ABCDEF',client_id='qa-client',knowledge_base_id='KB-1234567890ABCDEF',backend='feishu',locator={'knowledge_base_ref':self.space.locator},manifest_ref='manifest',profile_index_ref='index',supported_workflows=['content-koubo-slim'],workflow_defaults={},status='active')
        manifest=dict(contract_version='content-source-v1',knowledge_base_id=binding['knowledge_base_id'],client_id='qa-client',knowledge_base_name='Synthetic',backend='feishu',locator=self.space.locator,asset_roots={name:name for name in ('knowledge','content','profiles','workflow','output')},profile_index_ref='index',workflow_outputs={'content-koubo-slim':'weekly'},supported_workflows=['content-koubo-slim'],revision=1)
        self.client.add('manifest','workflow','Manifest',json.dumps(manifest))
        self.client.add('index','workflow','Index','{}')
        with patch('runtime.feishu_source.get_client',return_value=self.client):
            location=resolve_feishu_binding({'_registry_sha256':'a'*64},binding)
        self.assertEqual(location.backend_type,'feishu')
        self.assertEqual(location.vault_root.space_id,'123')
    def test_pair_readback_and_receipt_retry(self):
        first=save_feishu_pair(**self.args); count=self.client.sequence
        self.assertEqual(save_feishu_pair(**self.args),first)
        self.assertEqual(self.client.sequence,count)
        self.assertNotEqual(first['oral_ref'],first['package_ref'])
    def test_acknowledged_second_create_failure_reuses_first_and_second(self):
        self.client.fail_package='acknowledged'
        with self.assertRaises(SlimRuntimeError): save_feishu_pair(**self.args)
        count=self.client.sequence
        result=save_feishu_pair(**self.args)
        self.assertEqual(self.client.sequence,count)
        self.assertEqual(result['publish_status'],'not_requested')
    def test_unknown_create_is_not_recreated_or_adopted(self):
        self.client.fail_package='unknown'
        with self.assertRaises(SlimRuntimeError): save_feishu_pair(**self.args)
        count=self.client.sequence
        with self.assertRaises(SlimRuntimeError): save_feishu_pair(**self.args)
        self.assertEqual(self.client.sequence,count)
    def test_cross_space_and_shortcut_are_rejected(self):
        self.client.nodes['content']['space_id']='999'
        with self.assertRaises(SlimRuntimeError): assert_below(self.space,'content','content')
        self.client.nodes['content']['space_id']='123'; self.client.nodes['content']['node_type']='shortcut'
        with self.assertRaises(SlimRuntimeError): assert_below(self.space,'content','content')

    def test_windows_cmd_transport_rejects_unknown_shim(self):
        with self.assertRaises(ValueError):
            _lark_command(r'C:\missing\lark-cli.cmd', ['--title', '研发&销售'], platform='nt')

    def test_non_windows_transport_executes_binary_directly(self):
        self.assertEqual(
            _lark_command('/usr/local/bin/lark-cli',['wiki','+node-list'],platform='posix'),
            ['/usr/local/bin/lark-cli','wiki','+node-list'])

if __name__=='__main__': unittest.main()
