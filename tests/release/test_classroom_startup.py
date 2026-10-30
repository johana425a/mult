"""A dead or unready classroom child cannot be reported as a successful launch."""
from contextlib import ExitStack
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock,patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('competition_test_openmaic_runtime',ROOT/'scripts/openmaic_runtime.py')
runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)


class ClassroomStartupTests(unittest.TestCase):
    def invoke(self,statuses):
        with tempfile.TemporaryDirectory(prefix='DeepSteam classroom startup ') as tmp,ExitStack() as stack:
            root=Path(tmp);(root/'server.js').write_text('// fixture','utf-8');(root/'logs').mkdir()
            storage=SimpleNamespace(logs=root/'logs',prepare=lambda *paths:None)
            for name,value in {'STANDALONE':root,'STATE':root/'process.json','NODE':Path(sys.executable),'STORAGE':storage}.items():
                stack.enter_context(patch.object(runtime,name,value))
            stack.enter_context(patch.object(runtime,'environment',return_value={}))
            stack.enter_context(patch.object(runtime.socket,'socket'))
            stack.enter_context(patch.object(runtime.subprocess,'Popen',return_value=SimpleNamespace(pid=1234)))
            stack.enter_context(patch.object(runtime.psutil,'Process',return_value=SimpleNamespace(create_time=lambda:1)))
            stack.enter_context(patch.object(runtime.time,'sleep'))
            stack.enter_context(patch.object(runtime,'status',side_effect=statuses))
            stopped=stack.enter_context(patch.object(runtime,'stop'))
            try:return runtime.start(),None,stopped.call_count
            except RuntimeError as error:return None,str(error),stopped.call_count

    def test_child_exit_is_failure_not_success_with_running_false(self):
        value,error,stops=self.invoke([{'running':False},{'running':False,'healthy':False}])
        self.assertIsNone(value);self.assertIn('exited before startup',error);self.assertEqual(stops,0)

    def test_unhealthy_startup_times_out_and_stops_owned_child(self):
        value,error,stops=self.invoke([{'running':False}]+[{'running':True,'healthy':False}]*15)
        self.assertIsNone(value);self.assertIn('timed out',error);self.assertEqual(stops,1)

    def test_only_healthy_running_child_succeeds(self):
        value,error,stops=self.invoke([{'running':False},{'running':True,'healthy':True}])
        self.assertIsNone(error);self.assertTrue(value['healthy']);self.assertEqual(stops,0)


if __name__=='__main__':unittest.main(verbosity=2)
