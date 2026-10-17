import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('gate',Path(__file__).resolve().parents[2]/'scripts/verify_delivery_manifest.py')
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)

class GateTests(unittest.TestCase):
    def manifest(self):
        root=Path(tempfile.mkdtemp(prefix='delivery-gate-'))
        file=root/'source.md';file.write_text('# Verified source\n',encoding='utf-8')
        return {'expected_cases':{'chat':['md']},'cases':[{'id':'chat','files':[{'path':str(file),'download_path':str(file),
            'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'bytes':file.stat().st_size,'expected_text':['Verified source']}]}]}
    def test_empty_and_missing_cases_fail(self):
        for data in ({},{'expected_cases':{'chat':['md']},'cases':[]}):
            with self.assertRaises(ValueError):gate.verify(data)
        data=self.manifest();data['expected_cases']['reading']=['pdf']
        with self.assertRaisesRegex(ValueError,'Missing'):gate.verify(data)
    def test_actual_hash_parsed_content_and_download_required(self):
        data=self.manifest();self.assertTrue(gate.verify(data)['passed'])
        data['cases'][0]['files'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'hash'):gate.verify(data)
        data=self.manifest();del data['cases'][0]['files'][0]['download_path']
        with self.assertRaisesRegex(ValueError,'downloaded'):gate.verify(data)
    def test_invalid_json_is_not_successful_utf8(self):
        root=Path(tempfile.mkdtemp(prefix='delivery-json-'));file=root/'broken.json';file.write_text('{invalid}',encoding='utf-8')
        with self.assertRaises(json.JSONDecodeError):gate.inspect(file,hashlib.sha256(file.read_bytes()).hexdigest(),file.stat().st_size)

if __name__=='__main__':unittest.main()
