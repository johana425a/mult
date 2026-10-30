"""Real parser/source-store regressions; model outputs are deterministic fixtures."""
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

ROOT=Path(__file__).resolve().parents[2]
APP=Path(os.environ.get('DEEPSTEAM_QUIZ_TEST_APP',ROOT))
PACKAGES=APP/('runtime/deeptutor-packages' if (APP/'runtime/deeptutor-packages').is_dir() else 'upstream/DeepTutor')
sys.path[:0]=[str(APP),str(PACKAGES)]
os.environ.update(DEEPTUTOR_AUTH_ENABLED='false',AUTH_ENABLED='false')
from deeptutor.agents.question.pipeline import QuestionPipeline
from deeptutor.agents.question.plan_contract import QuizPlanningError
from deeptutor.agents.question.reading_grounding import prepare_reading_grounding, READING_QUIZ_TOOLS
from deeptutor.runtime.agentic import LabeledStepResult
from deeptutor.core.context import UnifiedContext, TurnRuntimeContext, WorkspaceRuntimeContext
from deeptutor.reading import ReadingStore
from deeptutor.reading.models import UnitReference
from deeptutor.reading.source_revision import ReadingRevisionConflict

TYPES=['choice','concept','fill_in_blank','short_answer','written']
COUNTS={t:1 for t in TYPES}
def items(types=TYPES):
    return [{'topic':f'Original source fact {i+1}', 'question_type':t,'difficulty':'medium'} for i,t in enumerate(types)]
def reply(value=None,**kwargs):
    return LabeledStepResult(label='PLAN',text=json.dumps({'templates':items()} if value is None else value),**kwargs)
def pipeline():
    p=QuestionPipeline.__new__(QuestionPipeline)
    p.language='zh';p.llm_config=NS(max_output_tokens=24000);p._budgets={'planning':{'max_tokens':6000}}
    p._prompts={'plan':{'system':'Plan exactly {num_questions} questions.', 'user_template':
        '{user_message}\n{exploration_trace}\n{allowed_types}\n{per_type_counts}\n{difficulty}'},
        'notices':{'plan_repair':'repair','plan_unusable':'plan invalid'}}
    return p

class QuizPlanTests(unittest.IsolatedAsyncioTestCase):
    async def plan(self,p):
        return await p._plan(user_message='Five questions from the open reading source',
            exploration_trace='ORIGINAL_SOURCE_MARKER_73',num_questions=5,difficulty='',
            allowed_types=TYPES,per_type_counts=COUNTS,stream=NS(progress=AsyncMock()),client=None)

    async def test_valid_plan_uses_one_call_and_exact_five_types(self):
        p=pipeline();p._run_labeled_step=AsyncMock(return_value=reply())
        plan=await self.plan(p)
        self.assertEqual(Counter(t.question_type for t in plan.templates),COUNTS)
        self.assertEqual(p._run_labeled_step.await_count,1)

    async def test_user_can_request_another_language_from_the_interface(self):
        p=pipeline();p.language='en';p._run_labeled_step=AsyncMock(return_value=reply())
        await p._plan(user_message='Please write this quiz in Chinese.',
            exploration_trace='SOURCE_EVIDENCE',num_questions=5,difficulty='',
            allowed_types=TYPES,per_type_counts=COUNTS,stream=NS(progress=AsyncMock()),client=None)
        messages=p._run_labeled_step.call_args.kwargs['messages']
        self.assertIn('honour that request',messages[0]['content'])
        self.assertIn('Please write this quiz in Chinese.',messages[1]['content'])

    async def test_equivalent_json_envelopes(self):
        for value in [items(),{'questions':items()},{'ideas':items()},{'plan':{'templates':items()}}]:
            p=pipeline();p._run_labeled_step=AsyncMock(return_value=reply(value))
            self.assertEqual(len((await self.plan(p)).templates),5)

    async def test_aliased_types_preserve_user_distribution(self):
        p=pipeline();p._run_labeled_step=AsyncMock(return_value=reply({'templates':items(
            ['multiple_choice','true_false','fill_in_the_blank','short-answer','essay'])}))
        self.assertEqual(Counter(t.question_type for t in (await self.plan(p)).templates),COUNTS)

    async def test_malformed_plan_is_repaired_with_same_source(self):
        p=pipeline();p._run_labeled_step=AsyncMock(side_effect=[LabeledStepResult('PLAN','Not JSON'),reply()])
        self.assertEqual(len((await self.plan(p)).templates),5)
        messages=p._run_labeled_step.call_args_list[1].kwargs['messages']
        self.assertIn('ORIGINAL_SOURCE_MARKER_73',json.dumps(messages))
        self.assertIn('Expected exactly 5',messages[-1]['content'])

    async def test_empty_reasoning_retry_keeps_selection_and_grows_budget(self):
        p=pipeline();p._run_labeled_step=AsyncMock(side_effect=[LabeledStepResult('UNKNOWN','',reasoning_only=True),reply()])
        await self.plan(p)
        later=p._run_labeled_step.call_args_list[1].kwargs
        self.assertEqual(later['max_tokens'],12000)
        self.assertNotIn('reasoning_effort',later)

    async def test_fewer_questions_are_repaired_not_silently_accepted(self):
        p=pipeline();p._run_labeled_step=AsyncMock(side_effect=[reply({'templates':items()[:2]}),reply()])
        self.assertEqual(len((await self.plan(p)).templates),5)
        self.assertEqual(p._run_labeled_step.await_count,2)

    async def test_wrong_type_distribution_is_repaired(self):
        p=pipeline();p._run_labeled_step=AsyncMock(side_effect=[reply({'templates':items(['choice']*5)}),reply()])
        self.assertEqual(Counter(t.question_type for t in (await self.plan(p)).templates),COUNTS)

    async def test_excluded_coding_does_not_get_relabelled(self):
        p=pipeline();bad=items();bad[-1]['question_type']='coding'
        p._run_labeled_step=AsyncMock(side_effect=[reply({'templates':bad}),reply()])
        await self.plan(p)
        self.assertEqual(p._run_labeled_step.await_count,2)

    async def test_duplicate_topics_and_invalid_fields_do_not_become_questions(self):
        p=pipeline();bad=items();bad[1]['topic']=bad[0]['topic'];bad[2]['topic']={'invented':'object'}
        p._run_labeled_step=AsyncMock(side_effect=[reply({'templates':bad}),reply()])
        await self.plan(p);self.assertEqual(p._run_labeled_step.await_count,2)

    async def test_truncated_response_not_accepted_even_if_json_repairs(self):
        p=pipeline();p._run_labeled_step=AsyncMock(side_effect=[reply(finish_reason='length'),reply()])
        await self.plan(p);self.assertEqual(p._run_labeled_step.await_count,2)

    async def test_persistent_failure_is_bounded_and_never_returns_empty_quiz(self):
        p=pipeline();p._run_labeled_step=AsyncMock(return_value=reply({'analysis':'No plan'}))
        with self.assertRaises(QuizPlanningError):await self.plan(p)
        self.assertEqual(p._run_labeled_step.await_count,3)

    async def test_cancel_and_transport_errors_are_not_format_retries(self):
        for error in [asyncio.CancelledError(),ConnectionError('offline')]:
            p=pipeline();p._run_labeled_step=AsyncMock(side_effect=error)
            with self.assertRaises(type(error)):await self.plan(p)
            self.assertEqual(p._run_labeled_step.await_count,1)

    async def test_question_repair_keeps_model_settings_and_original_source(self):
        p=pipeline();p._budgets['repair']={'max_tokens':3000}
        p._prompts['repair']={'system':'Repair JSON','user_template':'{question_type} {invalid_payload} {issues}'}
        p._run_labeled_step=AsyncMock(side_effect=[LabeledStepResult('UNKNOWN','',reasoning_only=True),
            LabeledStepResult('FINISH','{"question":"original source","correct_answer":"yes","explanation":"source"}')])
        result=await p._repair_quiz_payload(template=NS(question_id='q1',topic='source',question_type='short_answer',difficulty='medium'),
            payload={},issues=['missing'],stream=NS(progress=AsyncMock()),client=None,exploration_trace='SOURCE_MARKER_73',
            user_message='Please keep questions and explanations in Chinese.')
        self.assertEqual(result['correct_answer'],'yes')
        later=p._run_labeled_step.call_args_list[1].kwargs
        self.assertEqual(later['max_tokens'],6000)
        self.assertNotIn('reasoning_effort',later)
        self.assertIn('SOURCE_MARKER_73',json.dumps(later['messages']))
        self.assertIn('honour that request',later['messages'][0]['content'])
        self.assertIn('Please keep questions and explanations in Chinese.',json.dumps(later['messages']))

class QuizReadingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='Quiz reading 中文 ')
        root=Path(self.tmp.name)/'source';self.store=ReadingStore(root);self.mid='b'*16
        self.store.ingest_units(self.mid,filename='video.vtt',unit='segment',render_mode='video',
            units=[f'Original caption {i}: value is {73+i}.' for i in range(30)],
            extractor='bilibili-subtitles',unit_refs=[UnitReference(locator=i+1,title=f'00:{i*2:02d}',source_href=f'#t={i*2}') for i in range(30)])
        class ScopedStore(ReadingStore):
            def __init__(self,*args,**kwargs):super().__init__(root)
        self.patches=[patch('deeptutor.reading.ReadingStore',ScopedStore),patch('deeptutor.reading.store.ReadingStore',ScopedStore)]
        for p in self.patches:p.start()
        self.context=UnifiedContext(user_message='Generate five questions',language='zh',metadata={
            'reading_material_id':self.mid,'reading_material_revision':1,'reading_viewport':{'locator':1}},
            runtime=TurnRuntimeContext(workspace=WorkspaceRuntimeContext(root=str(root),output_dir=str(Path(self.tmp.name)/'out'))))

    async def asyncTearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()

    async def test_original_captions_beyond_first_page_are_in_seed(self):
        ground=await prepare_reading_grounding(self.context)
        self.assertIn('Original caption 29: value is 102.',ground.seed)
        self.assertIn('[00:58]',ground.seed)
        self.assertIn('read_material',ground.prompt)

    async def test_large_transcript_has_bounded_seed_and_continuation(self):
        self.store.ingest_units(self.mid,filename='large.vtt',unit='segment',render_mode='video',
            extractor='bilibili-subtitles',units=[f'Caption {i}: '+('original text '*200) for i in range(50)])
        self.context.metadata['reading_material_revision']=2
        ground=await prepare_reading_grounding(self.context)
        self.assertIn('Only part of the source is in this seed.',ground.seed)
        self.assertIn('Continue read_material with cursor:',ground.seed)
        self.assertNotIn('read completely',ground.seed)
        self.assertLess(len(ground.seed),28000)

    async def test_explicit_selection_keeps_current_locator(self):
        self.context.metadata['reading_viewport']={'locator':20,'selection':'caption 19'}
        ground=await prepare_reading_grounding(self.context)
        self.assertIn('Original caption 19: value is 92.',ground.seed)
        self.assertNotIn('Original caption 29',ground.seed)

    async def test_reading_tool_binding_cannot_be_supplied_by_model(self):
        p=pipeline();p._reading_grounding=await prepare_reading_grounding(self.context)
        args=p._augment_tool_kwargs('read_material',{'locators':'1','_material_id':'c'*16},self.context)
        self.assertEqual(args['_material_id'],self.mid)

    async def test_source_change_during_generation_is_rejected(self):
        ground=await prepare_reading_grounding(self.context)
        self.store.ingest_units(self.mid,filename='video.vtt',unit='segment',render_mode='video',extractor='bilibili-subtitles',units=['changed'])
        with self.assertRaises(ReadingRevisionConflict):ground.check(self.context)

    async def test_nonreading_turn_has_no_implicit_source(self):
        self.assertIsNone(await prepare_reading_grounding(UnifiedContext()))

    async def test_quiz_mounts_reading_tools_and_respects_explicit_limits(self):
        p=pipeline();p._reading_grounding=await prepare_reading_grounding(self.context)
        p.enabled_tools=[];p._optional_tools=[];p.registry=None;p._mount_flags=lambda context:None
        with patch('deeptutor.agents.question.pipeline.compose_enabled_tools',return_value=[]):
            self.assertEqual(p._resolved_tools(self.context),list(READING_QUIZ_TOOLS))
            self.context.allowed_builtin_tools=['read_material']
            self.assertEqual(p._resolved_tools(self.context),['read_material'])

    async def test_reading_tool_limits_do_not_remove_explicit_optional_tools(self):
        p=pipeline();p._reading_grounding=await prepare_reading_grounding(self.context)
        p.enabled_tools=['web_search'];p._optional_tools=[];p.registry=None;p._mount_flags=lambda context:None
        self.context.allowed_builtin_tools=['read_material']
        with patch('deeptutor.agents.question.pipeline.compose_enabled_tools',return_value=['web_search']):
            self.assertEqual(p._resolved_tools(self.context),['web_search','read_material'])

if __name__=='__main__':unittest.main(verbosity=2)
