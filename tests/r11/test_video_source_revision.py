"""Real disk regressions for media admission; no network or model fixtures."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
app = Path(os.environ.get('DEEPSTEAM_REVISION_TEST_APP', ROOT))
packages = app / ('runtime/deeptutor-packages' if (app/'runtime/deeptutor-packages/deeptutor').exists() else 'upstream/DeepTutor')
sys.path[:0] = [str(app), str(packages)]
from deeptutor.reading.store import ReadingStore
from deeptutor.reading.models import OutlineEntry, UnitReference
from deeptutor.reading.source_revision import resolve_media_revision, ReadingRevisionConflict
from integration.harness_turn import _source_snapshot, _invoke


class VideoRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='DeepSteam video revision 中文 ')
        self.store = ReadingStore(Path(self.temp.name)/'reading source')
        self.mid = 'a'*16

    def tearDown(self):
        self.temp.cleanup()

    def put(self, texts=('原书中的实验取样结果为 73。', '随后复测结果为 79。'), starts=(0.125, 8.75), *, placeholder=False):
        if placeholder:
            texts, starts = ('[Transcript unavailable for this video.]',), (0,)
        cues = [{'start': start, 'end': start + 3, 'text': text} for start,text in zip(starts,texts)]
        return self.store.ingest_units(self.mid, filename='video.vtt', units=texts,
            unit='segment', title='Video fixture', mime='text/vtt', render_mode='video',
            extractor='bilibili-no-subtitles' if placeholder else 'bilibili-subtitles',
            source_type='upload' if placeholder else 'bilibili_authenticated_subtitles',
            source_url='https://www.bilibili.com/video/BV1SmpD6QEuX/',
            assets=None if placeholder else {'bilibili-cues.json':json.dumps(cues,ensure_ascii=False).encode()},
            outline=[OutlineEntry(locator=i,title=str(start)) for i,start in enumerate(starts,1)],
            unit_refs=[UnitReference(locator=i,source_href=f'#t={start}',title=str(start)) for i,start in enumerate(starts,1)])

    def resolve(self, revision=1, viewport=None, replay=False):
        return resolve_media_revision(self.store,self.mid,revision,viewport or {},replay=replay,language='zh')

    def test_same_subtitle_refresh_is_idempotent_and_preserves_state(self):
        first = self.put()
        root=self.store._dir(self.mid)
        (root/'positions').mkdir(exist_ok=True)
        position=root/'positions'/f'{self.mid}.json';position.write_text('{"locator":2}',encoding='utf-8')
        stamp=(root/'manifest.json').stat().st_mtime_ns
        for _ in range(3):self.assertEqual(self.put().revision,first.revision)
        self.assertEqual(position.read_text('utf-8'),'{"locator":2}')
        self.assertEqual((root/'manifest.json').stat().st_mtime_ns,stamp)
        self.assertEqual(self.store.revisions(self.mid),[])

    def test_changed_words_create_a_real_revision(self):
        self.put();after=self.put(texts=('Changed original content', 'New result'))
        self.assertEqual(after.revision,2)
        self.assertIn('73', self.store.revision_unit_text(self.mid,1,1))
        self.assertFalse(self.store.revision_content_matches(self.mid,1))

    def test_subsecond_timestamp_change_is_not_identical(self):
        self.put();self.assertEqual(self.put(starts=(0.250,8.75)).revision,2)
        with self.assertRaises(ReadingRevisionConflict):self.resolve(replay=True)

    def test_caption_arrival_upgrades_an_unselected_failed_placeholder(self):
        self.put(placeholder=True);self.put()
        revision,viewport,refresh=self.resolve(viewport={'locator':1,'time_seconds':9},replay=True)
        self.assertEqual(revision,2);self.assertEqual(viewport['locator'],2)
        self.assertEqual(refresh['reason'],'captions_became_available')

    def test_new_question_uses_ready_captions_and_records_actual_revision(self):
        self.put();self.put(texts=('Changed original content','New result'))
        revision,viewport,refresh=self.resolve(viewport={'locator':100,'time_seconds':9})
        self.assertEqual(revision,2);self.assertEqual(viewport['locator'],2)
        self.assertEqual(refresh['requested_revision'],1)
        from deeptutor.services.session._turn_runtime_shared import _request_snapshot_metadata
        saved=_request_snapshot_metadata(payload={'reading_material_id':self.mid,
            'reading_material_revision':revision,'reading_viewport':viewport},content='Question',
            capability='chat',config={},attachments=[],notebook_references=[],history_references=[],
            partner_group_references=[],question_notebook_references=[],book_references=[],
            persona='',memory_references=[],llm_selection=None)
        self.assertEqual(saved['request_snapshot']['readingMaterialRevision'],2)

    def test_no_timestamp_discards_stale_segment_number(self):
        self.put(placeholder=True);self.put()
        _,viewport,_=self.resolve(viewport={'locator':999})
        self.assertNotIn('locator',viewport)

    def test_selected_quote_cannot_silently_follow_changed_source(self):
        self.put();self.put(texts=('Changed original content','New result'))
        with self.assertRaises(ReadingRevisionConflict):
            self.resolve(viewport={'selection':'原书中的实验取样结果为 73。','locator':1})

    def test_replay_of_changed_real_transcript_remains_pinned(self):
        self.put();self.put(texts=('Changed original content','New result'))
        with self.assertRaises(ReadingRevisionConflict):self.resolve(replay=True)

    def test_unknown_or_future_revision_is_rejected(self):
        self.put()
        with self.assertRaises(ReadingRevisionConflict):self.resolve(20)
        self.put(texts=('Changed original content','New result'))
        shutil.rmtree(self.store._dir(self.mid)/'revisions'/'000001')
        with self.assertRaises(ReadingRevisionConflict):self.resolve()

    def test_legacy_duplicate_revision_is_reconciled_from_real_bytes(self):
        self.put();root=self.store._dir(self.mid)
        prior=root/'revisions'/'000001';prior.mkdir(parents=True)
        for name in ('manifest.json','outline.json','unit_refs.json'):shutil.copy2(root/name,prior/name)
        for name in ('units','assets'):shutil.copytree(root/name,prior/name)
        manifest=json.loads((root/'manifest.json').read_text('utf-8'));manifest['revision']=2
        (root/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        revision,_,record=self.resolve(viewport={'selection':'原书中的实验取样结果为 73。','locator':1},replay=True)
        self.assertEqual(revision,2);self.assertEqual(record['reason'],'identical_content')
        (prior/'units/0001.txt').write_text('different',encoding='utf-8')
        with self.assertRaises(ReadingRevisionConflict):self.resolve(replay=True)

    def test_document_revision_contract_is_unchanged(self):
        self.store.ingest_units(self.mid,filename='document.md',units=['first'])
        self.store.ingest_units(self.mid,filename='document.md',units=['second'])
        revision,_,record=self.resolve()
        self.assertEqual(revision,1);self.assertIsNone(record)

    def test_execution_keeps_a_frozen_source_and_rejects_later_change(self):
        self.put(placeholder=True);self.put()
        revision,_,_=self.resolve()
        context=NS(runtime=NS(workspace=NS(workspace_id='fixture')),language='zh',metadata={
            'reading_material_id':self.mid,'reading_material_revision':revision})
        with patch('integration.execution_workspace_binding.owner_workspace_binding',return_value={'path':self.temp.name}), \
             patch('deeptutor.reading.store.ReadingStore',return_value=self.store):
            frozen=_source_snapshot(context,'fixture')
            self.put()
            self.assertEqual(_source_snapshot(context,'fixture'),frozen)
            self.put(texts=('Changed content during execution','Do not mix revisions'))
            with self.assertRaises(ReadingRevisionConflict):
                asyncio.run(_invoke({'pipeline':None,'context':context,'stream':None,'owner':'fixture','source_snapshot':frozen},'read_material',{},'call'))

    def test_conflict_is_readable_and_keeps_structured_error_code(self):
        error=ReadingRevisionConflict('zh')
        self.assertEqual(error.status_code,409)
        self.assertIn('重新打开',str(error));self.assertNotIn("{'code':",str(error))
        self.assertEqual(error.detail['code'],'execution_source_context_changed')
        self.assertFalse(error.retryable)


if __name__=='__main__':unittest.main(verbosity=2)
