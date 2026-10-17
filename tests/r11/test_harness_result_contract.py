"""Exercise the real public pipeline boundary consumed by Partner persistence."""
import asyncio,sys,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
app=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(app),str(app/'upstream/DeepTutor')]
from deeptutor.agents.loop.pipeline import AgenticLoopPipeline
from deeptutor.agents.loop.agent_loop import LoopOutcome

class ResultContract(unittest.IsolatedAsyncioTestCase):
    async def exercise(self,completed=True,emit=True,source='chat'):
        pipeline=NS(emit_result=emit,event_source=source,usage=None)
        context=NS(runtime=NS(workspace=object()))
        stream=NS(result=AsyncMock())
        outcome=LoopOutcome(final_text='v = 120 * 2 / (2 + 2) = 60',completed=completed)
        with patch('integration.harness_turn.enabled',return_value=True),patch('integration.harness_turn.run_pipeline',return_value=outcome):
            payload=await AgenticLoopPipeline.run(pipeline,context,stream)
        return payload,stream

    async def test_partner_gets_one_authoritative_result(self):
        payload,stream=await self.exercise()
        self.assertIsInstance(payload,dict)
        self.assertEqual(payload['response'],'v = 120 * 2 / (2 + 2) = 60')
        self.assertTrue(payload['completed'])
        stream.result.assert_awaited_once_with(payload,source='chat')

    async def test_private_capability_can_suppress_result(self):
        payload,stream=await self.exercise(emit=False)
        self.assertIn('response',payload)
        stream.result.assert_not_awaited()

    async def test_failed_turn_cannot_be_marked_complete(self):
        payload,stream=await self.exercise(completed=False)
        self.assertFalse(payload['completed'])
        self.assertEqual(stream.result.await_count,1)

    async def test_surface_identity_is_preserved(self):
        payload,stream=await self.exercise(source='mastery')
        stream.result.assert_awaited_once_with(payload,source='mastery')

    async def test_cancellation_does_not_emit_success(self):
        pipeline=NS(emit_result=True,event_source='chat',usage=None)
        context=NS(runtime=NS(workspace=object()))
        stream=NS(result=AsyncMock())
        with patch('integration.harness_turn.enabled',return_value=True),patch('integration.harness_turn.run_pipeline',side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await AgenticLoopPipeline.run(pipeline,context,stream)
        stream.result.assert_not_awaited()

if __name__=='__main__':unittest.main(verbosity=2)
