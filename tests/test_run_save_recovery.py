"""Real synthetic Run recovery; all Gate choices here are simulated inputs."""
from pathlib import Path
import unittest
from unittest.mock import patch
import test_content_source_v1 as baseline
from runtime.run_store import RunStore
from runtime.error_model import SlimRuntimeError

class RunSaveRecoveryTests(unittest.TestCase):
    def exercise(self,kind):
        original_respond=baseline.respond_package
        transition=RunStore.transition
        original_open=Path.open
        reached=[]
        def wrapped(**args):
            store=RunStore(args['runs_root']); key=store.resolve_task_record(args['task_record'])
            if kind=='state-commit':
                def fail_transition(self,key,target,*a,**kw):
                    if target=='saved': raise SlimRuntimeError('SLIM_RUN_STORE_INVALID','test',detail='injected state commit failure')
                    return transition(self,key,target,*a,**kw)
                context=patch.object(RunStore,'transition',fail_transition)
            else:
                def fail_open(path,mode='r',*a,**kw):
                    handle=original_open(path,mode,*a,**kw)
                    if mode!='xb' or not path.name.endswith('-配套文案.md'): return handle
                    class Failing:
                        def __enter__(self): handle.__enter__(); return self
                        def __exit__(self,*a): return handle.__exit__(*a)
                        def __getattr__(self,n): return getattr(handle,n)
                        def write(self,value):
                            handle.write(value[:4]); raise OSError('injected package partial write')
                    return Failing()
                context=patch.object(Path,'open',fail_open)
            with context,self.assertRaises(SlimRuntimeError): original_respond(**args)
            self.assertEqual(store.get_task(key)['state'],'blocked')
            reached.append('blocked')
            result=original_respond(**args)
            self.assertEqual(store.get_task(key)['state'],'saved')
            reached.append('saved')
            return result
        with patch.object(baseline,'respond_package',wrapped):
            baseline.ContentSourceV1Tests().test_common_profile_completes_three_gates_and_saves_to_its_own_path()
        self.assertEqual(reached,['blocked','saved'])
    def test_real_run_recovers_second_partial_write(self): self.exercise('partial-write')
    def test_real_run_recovers_after_pair_before_state_commit(self): self.exercise('state-commit')
