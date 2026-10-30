"""Prevent omitted patches, stale mirrors and old generated assets from shipping."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'installer'))
from release_runtime_binding import component_identity, direct_map, member, sha, verify_compiled, verify_direct


class RuntimeBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='DeepSteam candidate 中文 ')
        self.root=Path(self.temp.name);self.source=self.root/'source';self.runtime=self.root/'app'
        self.source.mkdir();self.runtime.mkdir()

    def tearDown(self):self.temp.cleanup()

    def put(self,base,name,data='code=1\n'):
        p=base/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(data,'utf-8');return p

    def test_new_module_is_automatically_required_and_stale_file_fails(self):
        names=['integration/new_tool.py','upstream/DeepTutor/deeptutor/reading/new_parser.py',
               'integration/harness/new_tool.mjs','scripts/new_worker.py']
        for name in names:self.put(self.source,name)
        with self.assertRaisesRegex(ValueError,'Missing application file'):verify_direct(self.source,self.runtime,names)
        mapping=direct_map(names)
        self.assertEqual(len(mapping),6)
        for row in mapping:self.put(self.runtime,row['runtime'])
        self.assertEqual(len(verify_direct(self.source,self.runtime,names)),6)
        self.put(self.runtime,mapping[-1]['runtime'],'old_code=0')
        with self.assertRaisesRegex(ValueError,'Stale application file'):verify_direct(self.source,self.runtime,names)

    def test_shadow_python_copy_and_deleted_source_do_not_pass(self):
        name='upstream/DeepTutor/deeptutor/reading/parser.py'
        self.put(self.source,name)
        self.put(self.runtime,'runtime/deeptutor-packages/deeptutor/reading/parser.py')
        self.put(self.runtime,'runtime/python/Lib/site-packages/deeptutor/reading/parser.py','old=1')
        with self.assertRaisesRegex(ValueError,'Stale Python mirror'):verify_direct(self.source,self.runtime,[name])
        (self.source/name).unlink()
        with self.assertRaisesRegex(ValueError,'Deleted source remains'):verify_direct(self.source,self.runtime,[name])

    def test_tests_do_not_become_runtime_modules_and_unsafe_paths_fail(self):
        self.assertEqual(direct_map(['integration/harness/workspace.test.mjs','desktop/transport-electron-fixture.cjs','scripts/test_runtime.py']),[])
        for name in ('../escape','C:/escape','/escape','a\\b'):
            with self.assertRaises(ValueError):member(self.runtime,name)

    def test_release_identity_cannot_remain_on_an_older_version(self):
        name='LOCAL-BUILD-INFO.json'
        self.put(self.source,name,'{"version":"new-candidate"}')
        self.put(self.runtime,name,'{"version":"old-installation"}')
        with self.assertRaisesRegex(ValueError,'Stale application file'):verify_direct(self.source,self.runtime,[name])

    def builds(self):
        names=['upstream/DeepTutor/web/app/page.tsx','upstream/OpenMAIC/app/page.tsx']
        for name in names:self.put(self.source,name)
        components=[]
        for key,prefix,target in [('frontend','upstream/DeepTutor/web/','runtime/native-frontends/rc/.next'),
                                  ('classroom','upstream/OpenMAIC/','runtime/openmaic-standalone/.next')]:
            path=self.put(self.runtime,target+'/BUILD_ID',key+'-build')
            output={'path':path.relative_to(self.runtime).as_posix(),'bytes':path.stat().st_size,'sha256':sha(path)}
            identity=component_identity(self.source,prefix,names)
            components.append({'component':key,'source':identity,'source_after':identity,'exit_code':0,
                'build_id':key+'-build','outputs':[output],'output_roots':[target]})
        receipt=self.runtime/'installer/compiled-source.json';receipt.parent.mkdir()
        receipt.write_text(json.dumps({'components':components}),'utf-8')
        return names,receipt

    def test_frontend_and_classroom_bound_to_current_source_and_outputs(self):
        names,receipt=self.builds()
        self.assertEqual(len(verify_compiled(self.source,self.runtime,names)['components']),2)
        self.put(self.source,names[1],'new source')
        with self.assertRaisesRegex(ValueError,'Compiled source changed'):verify_compiled(self.source,self.runtime,names)

    def test_extra_stale_chunk_missing_component_and_changed_asset_fail(self):
        names,receipt=self.builds()
        extra=self.put(self.runtime,'runtime/native-frontends/rc/.next/static/stale.js')
        with self.assertRaisesRegex(ValueError,'Unrecorded'):verify_compiled(self.source,self.runtime,names)
        extra.unlink()
        data=json.loads(receipt.read_text());data['components'].pop();receipt.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'Both frontend and classroom'):verify_compiled(self.source,self.runtime,names)

    def test_standalone_cannot_ship_an_english_compiled_ui(self):
        names,receipt=self.builds()
        self.put(self.source,'RELEASE-IDENTITY.json',json.dumps({'edition':'windows-standalone-zh','default_language':'zh'}))
        with self.assertRaisesRegex(ValueError,'Compiled language differs'):verify_compiled(self.source,self.runtime,names)
        data=json.loads(receipt.read_text())
        for build in data['components']:build['default_language']='zh'
        receipt.write_text(json.dumps(data))
        self.assertEqual(len(verify_compiled(self.source,self.runtime,names)['components']),2)


if __name__=='__main__':unittest.main(verbosity=2)
