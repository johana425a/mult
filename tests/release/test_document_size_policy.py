"""The installed reader and ingestion queue must honor the same 512 MiB policy."""
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(os.environ.get('DEEPSTEAM_SIZE_TEST_APP', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(ROOT))
from integration.document_jobs import child_environment
from integration.document_ingestion_jobs import DocumentIngestions


def reader_limit():
    spec = importlib.util.spec_from_file_location('size_policy_reader', ROOT/'scripts/workspace_document_reader.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MAX_FILE_BYTES


class DocumentSizePolicyTests(unittest.TestCase):
    def test_default_and_explicit_limits_match_in_reader_and_child(self):
        for value, expected in [(None,512), ('invalid',512), ('1073741824',512), ('104857600',100), ('0',1)]:
            with self.subTest(value=value), patch.dict(os.environ):
                os.environ.pop('EDUAGENT_DOCUMENT_MAX_BYTES',None)
                if value is not None:os.environ['EDUAGENT_DOCUMENT_MAX_BYTES']=value
                self.assertEqual(reader_limit(),expected*1024*1024)
                self.assertEqual(int(child_environment()['EDUAGENT_DOCUMENT_MAX_BYTES']),expected*1024*1024)

    def test_ingestion_above_old_200_mib_limit_is_retained_and_deduplicated(self):
        with tempfile.TemporaryDirectory(prefix='DeepSteam size policy ') as folder, patch.dict(os.environ):
            os.environ.pop('EDUAGENT_DOCUMENT_MAX_BYTES',None)
            root=Path(folder);source=root/'large textbook.pdf'
            with source.open('wb') as stream:
                stream.write(b'%PDF-1.7\n% size admission fixture, not a parser acceptance\n')
                stream.seek(201*1024*1024-1);stream.write(b'\n')
            jobs=DocumentIngestions(test_root=root/'state')
            identity=jobs.prepare(source,'contest-size-policy')
            row=jobs._row(identity);retained=jobs.jobs.cache/row['source']
            self.assertEqual(retained.stat().st_size,source.stat().st_size)
            with source.open('rb') as stream:self.assertEqual(row['source_hash'],hashlib.file_digest(stream,'sha256').hexdigest())
            self.assertEqual(jobs.prepare(source,'contest-size-policy'),identity)
            self.assertEqual(row['status'],'queued')
            with patch.dict(os.environ,EDUAGENT_DOCUMENT_MAX_BYTES=str(100*1024*1024)):
                with self.assertRaisesRegex(ValueError,'document_source_invalid'):
                    jobs.prepare(source,'contest-size-policy')

    def test_over_512_mib_rejected_before_copy(self):
        with tempfile.TemporaryDirectory(prefix='DeepSteam size cap ') as folder, patch.dict(os.environ):
            os.environ.pop('EDUAGENT_DOCUMENT_MAX_BYTES',None)
            root=Path(folder);source=root/'too large.pdf'
            with source.open('wb') as stream:
                stream.seek(512*1024*1024);stream.write(b'X')
            jobs=DocumentIngestions(test_root=root/'state')
            with self.assertRaisesRegex(ValueError,'document_source_invalid'):jobs.prepare(source,'contest-size-policy')
            self.assertFalse((jobs.cache/'sources').exists())


if __name__=='__main__':unittest.main()
