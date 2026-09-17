from __future__ import annotations
import copy,json,os,sys,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Skills'/'content-koubo-slim'))
from runtime.error_model import SlimRuntimeError
from runtime.vault_save import save_markdown_pair
from runtime.content_source import validate_common_manifest,validate_profile_index,validate_common_registry
from runtime.client_registry import _safe_relative_path
from scripts.content_koubo_slim import _normalize_decision

class RepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT,prefix='.repair-')
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.out=self.root/'out'; self.out.mkdir()
        self.args=dict(output_root=self.out,output_template='YYYY/M/W',client_id='qa-client',selected_publish_title='保存恢复测试',oral_body='口播诊断正文',package_markdown='配套诊断正文',now=datetime(2026,9,16,tzinfo=timezone.utc))

    def test_write_flush_fsync_failures_remove_both_and_retry(self):
        for operation in ('write','flush','fsync'):
            for position in (1,2):
                with self.subTest(operation=operation,position=position):
                    out=self.root/f'{operation}-{position}'; out.mkdir()
                    args={**self.args,'output_root':out}
                    real_open=Path.open; real_fsync=os.fsync; count=[0]
                    class FailingHandle:
                        def __init__(self,h): self.h=h
                        def __enter__(self): self.h.__enter__(); return self
                        def __exit__(self,*a): return self.h.__exit__(*a)
                        def __getattr__(self,n): return getattr(self.h,n)
                        def write(self,data):
                            if operation=='write':
                                count[0]+=1
                                if count[0]==position:
                                    self.h.write(data[:3]); raise OSError('injected partial write')
                            return self.h.write(data)
                        def flush(self):
                            if operation=='flush':
                                count[0]+=1
                                if count[0]==position: raise OSError('injected flush')
                            return self.h.flush()
                    def patched_open(p,mode='r',*a,**kw):
                        h=real_open(p,mode,*a,**kw)
                        return FailingHandle(h) if mode=='xb' and p.is_relative_to(out) else h
                    def patched_fsync(fd):
                        count[0]+=1
                        if count[0]==position: raise OSError('injected fsync')
                        return real_fsync(fd)
                    with patch.object(Path,'open',patched_open),patch('runtime.vault_save.os.fsync',patched_fsync if operation=='fsync' else real_fsync):
                        with self.assertRaises(SlimRuntimeError): save_markdown_pair(**args)
                    self.assertEqual(list(out.rglob('*.md')),[])
                    saved=save_markdown_pair(**args)
                    self.assertEqual(saved['oral_path'].read_text(encoding='utf-8'),'口播诊断正文\n')

    def test_receipt_allows_retry_after_save_before_run_transition(self):
        args={**self.args,'receipt_dir':self.root/'receipt'}
        first=save_markdown_pair(**args)
        second=save_markdown_pair(**{**args,'now':datetime(2026,10,1,tzinfo=timezone.utc)})
        self.assertEqual(first,second)
        self.assertEqual(len(list(self.out.rglob('*.md'))),2)

    def test_receipt_never_adopts_unacknowledged_same_name(self):
        first=save_markdown_pair(**self.args)
        with self.assertRaises(SlimRuntimeError):
            save_markdown_pair(**self.args,receipt_dir=self.root/'receipt')
        self.assertEqual(first['oral_path'].read_text(encoding='utf-8'),'口播诊断正文\n')

    def test_receipt_rejects_content_or_target_changes(self):
        args={**self.args,'receipt_dir':self.root/'receipt'}
        first=save_markdown_pair(**args)
        for change in ({'oral_body':'改变批准正文'},{'selected_publish_title':'改变标题'}):
            with self.subTest(change=change),self.assertRaises(SlimRuntimeError): save_markdown_pair(**{**args,**change})
        first['oral_path'].write_text('人为改动',encoding='utf-8')
        with self.assertRaises(SlimRuntimeError): save_markdown_pair(**args)
        self.assertEqual(first['oral_path'].read_text(encoding='utf-8'),'人为改动')

    def test_manifest_matches_schema_for_reproduced_invalid_values(self):
        value=json.loads((ROOT/'examples/content-source-manifest.example.json').read_text(encoding='utf-8'))
        for field,bad in [('revision',0),('revision',True),('knowledge_base_name',''),('client_id',''),('locator',{}),('supported_workflows',['content-koubo-slim','bad'])]:
            with self.subTest(field=field,bad=bad),self.assertRaises(SlimRuntimeError): validate_common_manifest({**value,field:bad})

    def test_profile_index_revision_and_alias_duplicates(self):
        value=json.loads((ROOT/'examples/content-profile-index.example.json').read_text(encoding='utf-8'))
        for bad in (0,True):
            with self.subTest(bad=bad),self.assertRaises(SlimRuntimeError): validate_profile_index({**value,'revision':bad},knowledge_base_id=value['knowledge_base_id'])

    def test_registry_absolute_refs_rejected_at_validation(self):
        value=json.loads((ROOT/'examples/knowledge-base-registry.example.json').read_text(encoding='utf-8'))
        binding=next(iter(value['bindings'].values()))
        binding['manifest_ref']='C:\\outside\\manifest.json'
        with self.assertRaises(SlimRuntimeError): validate_common_registry(value)

    def test_relative_path_lexical_traversal_drive_and_empty_segments(self):
        for value in ('../a','x/../a','C:/a','C:a','x//a','x/./a','/a','x\\a'):
            with self.subTest(value=value),self.assertRaises(ValueError): _safe_relative_path(value)

    def test_common_english_punctuation_is_normalized_but_ambiguous_is_not(self):
        for tail in ('.',',','。','，','!','?','！','？'):
            self.assertEqual(_normalize_decision('  确认正文'+tail+'  '),'确认正文')
        for value in ('随便','差不多','我可能确认正文','确认正文并发布'):
            self.assertEqual(_normalize_decision(value),value)

    def test_receipt_request_only_never_adopts_matching_unacknowledged_files(self):
        args={**self.args,'receipt_dir':self.root/'receipt'}
        saved=save_markdown_pair(**args)
        receipt=args['receipt_dir']/'local-save.json'
        state=json.loads(receipt.read_text(encoding='utf-8'))
        state['result']=None; state['identities']={}
        receipt.write_text(json.dumps(state),encoding='utf-8')
        with self.assertRaises(SlimRuntimeError): save_markdown_pair(**args)
        self.assertTrue(saved['oral_path'].exists())

    def test_receipt_rejects_corruption_and_moved_destination(self):
        args={**self.args,'receipt_dir':self.root/'receipt'}
        save_markdown_pair(**args)
        moved=self.root/'other'; moved.mkdir()
        with self.assertRaises(SlimRuntimeError): save_markdown_pair(**{**args,'output_root':moved})
        (args['receipt_dir']/'local-save.json').write_text('{bad',encoding='utf-8')
        with self.assertRaises(SlimRuntimeError): save_markdown_pair(**args)

    def test_receipt_created_before_failure_can_retry_clean_targets(self):
        args={**self.args,'receipt_dir':self.root/'receipt'}
        real_open=Path.open
        def fail(p,mode='r',*a,**kw):
            if mode=='xb' and p.suffix=='.md': raise OSError('output create failure')
            return real_open(p,mode,*a,**kw)
        with patch.object(Path,'open',fail),self.assertRaises(SlimRuntimeError): save_markdown_pair(**args)
        self.assertEqual(list(self.out.rglob('*.md')),[])
        result=save_markdown_pair(**args)
        self.assertTrue(result['oral_path'].exists())

    def test_saver_rejects_escape_and_reparse_before_writes(self):
        for template in ('../escape','C:/escape','x/../escape','x//escape'):
            with self.subTest(template=template),self.assertRaises(SlimRuntimeError): save_markdown_pair(**{**self.args,'output_template':template})
        self.assertEqual(list(self.out.rglob('*.md')),[])
        real_lstat=Path.lstat
        def junction(p):
            value=real_lstat(p)
            if p==self.out:
                from types import SimpleNamespace
                return SimpleNamespace(st_file_attributes=0x400,st_mode=value.st_mode)
            return value
        with patch.object(Path,'lstat',junction),self.assertRaises(SlimRuntimeError): save_markdown_pair(**self.args)

    def test_readback_failure_cleans_both_files(self):
        original=Path.read_bytes
        def wrong(p): return b'wrong' if p.suffix=='.md' else original(p)
        with patch.object(Path,'read_bytes',wrong),self.assertRaises(SlimRuntimeError): save_markdown_pair(**self.args)
        self.assertEqual(list(self.out.rglob('*.md')),[])

    def test_manifest_output_reparse_is_rejected_before_resolve(self):
        from runtime.client_manifest import validate_manifest,resolve_asset_root
        value=json.loads((ROOT/'examples/content-source-manifest.example.json').read_text(encoding='utf-8'))
        manifest=validate_manifest(value)
        target=self.root/manifest.asset_roots['output']; target.mkdir(parents=True)
        real_lstat=Path.lstat
        def junction(p):
            stat=real_lstat(p)
            if p==target:
                from types import SimpleNamespace
                return SimpleNamespace(st_file_attributes=0x400,st_mode=stat.st_mode)
            return stat
        with patch.object(Path,'lstat',junction),self.assertRaises(SlimRuntimeError): resolve_asset_root(self.root,manifest,'output')

    def test_pending_approved_run_retries_save_without_reapproval(self):
        from scripts.content_koubo_slim import respond_package
        from unittest.mock import MagicMock
        store=MagicMock(); store.resolve_task_record.return_value='key'
        store.get_task.return_value={'state':'package_approved'}
        with patch('scripts.content_koubo_slim.RunStore',return_value=store),patch('scripts.content_koubo_slim._save_approved_package',return_value={'status':'completed'}) as save:
            result,_=respond_package(registry_path=self.root/'registry.json',runs_root=self.root/'runs',task_record='controlled',decision='确认并保存')
        self.assertEqual(result['status'],'completed')
        save.assert_called_once(); store.transition.assert_not_called()

if __name__=='__main__': unittest.main()
