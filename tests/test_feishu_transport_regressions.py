"""Synthetic exports and inert argv echo; no Feishu calls or credentials."""
import hashlib
import html
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'Skills/content-koubo-slim'), str(ROOT/'tests')]
from runtime.feishu_client import _lark_command, document_body_variants
from runtime.feishu_source import FeishuSpace, FeishuDocument, FeishuRoot, remote_json
from runtime.feishu_save import save_feishu_pair, verify_saved_feishu_pair
from runtime.error_model import SlimRuntimeError
from test_feishu_retained import FakeClient


class NativeTitleClient(FakeClient):
    title_override = None
    extra_body = ''
    def fetch_markdown(self, ref):
        node = self.get_node(ref)
        title = self.title_override or node['title']
        return '<title>' + html.escape(title) + '</title>\n\n' + super().fetch_markdown(ref) + self.extra_body


class NativeTitleTests(unittest.TestCase):
    def test_config_unwraps_title_but_digest_includes_it(self):
        client=NativeTitleClient();space=FeishuSpace('https://feishu.cn/wiki/space/123','123',client)
        client.add('config','workflow','Manifest','```json\n{"revision":1}\n```\n')
        doc=FeishuDocument(space,'config')
        data,digest=remote_json(doc)
        self.assertEqual(data,{'revision':1})
        client.title_override='Changed title'
        with self.assertRaises(SlimRuntimeError):
            remote_json(FeishuDocument(space,'config',expected_sha256=digest))

    def test_save_retry_and_saved_status_share_title_handling(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            client=NativeTitleClient();space=FeishuSpace('https://feishu.cn/wiki/space/123','123',client)
            args=dict(output_root=FeishuRoot(space,'output','output'),output_template='weekly',client_id='qa',selected_publish_title='研发&销售',oral_body='正文\n\n保留段落',package_markdown='配文',receipt_dir=Path(folder)/'receipt')
            saved=save_feishu_pair(**args);count=client.sequence
            self.assertEqual(save_feishu_pair(**args),saved)
            self.assertEqual(client.sequence,count)
            verify=dict(output_root=args['output_root'],output_template='weekly',receipt_dir=args['receipt_dir'],expected_result=saved,draft_version=1,item_suffix=None)
            self.assertTrue(verify_saved_feishu_pair(**verify))
            client.extra_body='篡改正文'
            self.assertFalse(verify_saved_feishu_pair(**verify))
            with self.assertRaises(SlimRuntimeError): save_feishu_pair(**args)

    def test_wrong_native_title_is_rejected(self):
        with self.assertRaises(SlimRuntimeError):
            document_body_variants('<title>其他标题</title>\n正文','应有标题')

    def test_only_leading_transport_wrapper_is_removed(self):
        body='正文\n<title>嵌入正文的标签</title>\n结束\n'
        variants=document_body_variants('<title>标题</title>\n\n'+body,'标题')
        self.assertIn(body,variants)
        self.assertNotIn('正文\n结束\n',variants)


class WindowsLauncherTests(unittest.TestCase):
    def package(self, root):
        shim=root/'lark-cli.cmd';shim.write_text('@echo off\n',encoding='utf-8')
        package=root/'node_modules'/'@larksuite'/'cli';(package/'scripts').mkdir(parents=True)
        (package/'package.json').write_text(json.dumps({'name':'@larksuite/cli','bin':{'lark-cli':'scripts/run.js'}}),encoding='utf-8')
        entry=package/'scripts'/'run.js';entry.write_text('console.log(JSON.stringify(process.argv.slice(2)));',encoding='utf-8')
        return shim,entry

    def test_native_executable_receives_unmodified_argv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);shim=root/'lark-cli.cmd';exe=root/'lark-cli.exe';exe.touch()
            args=['--title','研发&销售|%PATH%"^!<>']
            self.assertEqual(_lark_command(str(shim),args,platform='nt'),[str(exe),*args])

    def test_official_npm_entry_bypasses_cmd(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);shim,entry=self.package(root);node=root/'node.exe';node.touch()
            args=['docs','+create','--title','研发&销售']
            self.assertEqual(_lark_command(str(shim),args,platform='nt'),[str(node),str(entry),*args])
            (entry.parent.parent/'package.json').write_text('{}')
            with self.assertRaises(ValueError): _lark_command(str(shim),args,platform='nt')

    @unittest.skipUnless(os.name=='nt', 'requires real Windows process argument transport')
    def test_windows_node_roundtrip_preserves_all_title_characters(self):
        self.assertIsNotNone(shutil.which('node'), 'Windows CI must provide Node for npm transport test')
        with tempfile.TemporaryDirectory() as tmp:
            shim,entry=self.package(Path(tmp))
            args=['研发&销售','a|b','%PATH%','"引号"','空 格','^!<>','尾部\\']
            command=_lark_command(str(shim),args)
            result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',shell=False,check=True)
            self.assertEqual(json.loads(result.stdout),args)

if __name__=='__main__': unittest.main()
