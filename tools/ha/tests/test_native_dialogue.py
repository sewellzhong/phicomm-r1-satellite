"""Native endpoint/session tests in HA 2026.8.2; no real model or device calls."""
import asyncio
import struct
import math
from dataclasses import replace
from types import SimpleNamespace, MethodType
from unittest.mock import AsyncMock, patch
import unittest
from homeassistant.core import Context
from homeassistant.components import stt, conversation
from homeassistant.components.assist_pipeline.pipeline import PipelineInput, PipelineRun, PipelineStage
from homeassistant.helpers import intent
from custom_components.r1_input_guard.endpoint import CommandStream
from custom_components.r1_input_guard.stt import GuardedStt
from custom_components.r1_input_guard.conversation import NativeConversation

META=stt.SpeechMetadata(language='zh',format=stt.AudioFormats.WAV,codec=stt.AudioCodecs.PCM,
    bit_rate=stt.AudioBitRates.BITRATE_16,sample_rate=stt.AudioSampleRates.SAMPLERATE_16000,
    channel=stt.AudioChannels.CHANNEL_MONO)

async def audio(frames=1000):
    for _ in range(frames): yield struct.pack('<320h', *(int(1000*math.sin(2*math.pi*440*i/16000)) for i in range(320)))

class EndpointTest(unittest.IsolatedAsyncioTestCase):
    def guard(self, native=True):
        data={'source_registry_id':'source'}
        if native:data['mode']='r1_native'
        guard=GuardedStt(SimpleNamespace(entry_id='test',data=data));guard.entity_id='stt.test';guard.hass=SimpleNamespace()
        self.count=0
        async def recognize(metadata,stream):
            async for chunk in stream:self.count+=len(chunk)
            return stt.SpeechResult('现在几点？',stt.SpeechResultState.SUCCESS)
        source=SimpleNamespace(available=True,check_metadata=lambda m:True,
            audio_processing=stt.DEFAULT_AUDIO_PROCESSING,
            internal_async_process_audio_stream=AsyncMock(side_effect=recognize))
        guard._source=lambda:source
        return guard,source

    async def test_native_accepts_20_seconds_and_preserves_processing_preferences(self):
        guard,_=self.guard();processing=guard.audio_processing
        self.assertFalse(processing.requires_external_vad)
        self.assertEqual(stt.DEFAULT_AUDIO_PROCESSING.prefers_auto_gain_enabled,processing.prefers_auto_gain_enabled)
        self.assertEqual(stt.DEFAULT_AUDIO_PROCESSING.prefers_noise_reduction_enabled,processing.prefers_noise_reduction_enabled)
        self.assertTrue(stt.DEFAULT_AUDIO_PROCESSING.requires_external_vad)
        result=await guard.async_process_audio_stream(META,audio())
        self.assertEqual(stt.SpeechResultState.SUCCESS,result.result);self.assertEqual(640000,self.count)
        standard,_=self.guard(False);self.assertTrue(standard.audio_processing.requires_external_vad)

    async def test_control_diagnostic_distinguishes_homophone_without_retaining_text(self):
        for text, target, homophone in [('现在语速多少','speech_speed',False),('当前语速是多少','speech_speed',False),('现在雨速多少',None,True)]:
            guard,source=self.guard()
            async def recognize(metadata,stream):
                async for chunk in stream: pass
                return stt.SpeechResult(text,stt.SpeechResultState.SUCCESS)
            source.internal_async_process_audio_stream.side_effect=recognize
            result=await guard.async_process_audio_stream(META,audio(10))
            self.assertEqual(text,result.text)
            self.assertEqual(target,guard._last_diagnostic['control_target'])
            self.assertEqual(homophone,guard._last_diagnostic['speed_homophone'])
            self.assertNotIn(text,str(guard._last_diagnostic))

    async def test_overlength_wrong_format_early_return_and_cancellation(self):
        guard,source=self.guard()
        self.assertEqual(stt.SpeechResultState.ERROR,(await guard.async_process_audio_stream(META,audio(6051))).result)
        self.assertEqual(stt.SpeechResultState.ERROR,(await guard.async_process_audio_stream(replace(META,sample_rate=8000),audio())).result)
        source.internal_async_process_audio_stream.side_effect=None
        source.internal_async_process_audio_stream.return_value=stt.SpeechResult('开灯',stt.SpeechResultState.SUCCESS)
        self.assertEqual(stt.SpeechResultState.ERROR,(await guard.async_process_audio_stream(META,audio())).result)
        source.internal_async_process_audio_stream.side_effect=asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):await guard.async_process_audio_stream(META,audio())

    async def test_stall_wall_deadline_and_stream_error(self):
        guard,_=self.guard()
        async def stalled():
            yield bytes(640)
            await asyncio.sleep(1)
            yield bytes(640)
        with patch.object(CommandStream,'IDLE_SECONDS',.01):
            self.assertEqual(stt.SpeechResultState.ERROR,(await guard.async_process_audio_stream(META,stalled())).result)
        with patch.object(CommandStream,'INPUT_SECONDS',0):
            self.assertEqual(stt.SpeechResultState.ERROR,(await guard.async_process_audio_stream(META,audio())).result)
        async def failed():
            yield bytes(640)
            raise ValueError('synthetic disconnect')
        self.assertEqual(stt.SpeechResultState.ERROR,(await guard.async_process_audio_stream(META,failed())).result)

    async def test_silent_and_dc_audio_cannot_reach_intent_even_if_asr_invents_text(self):
        guard, _ = self.guard()
        for pcm in (bytes(640), struct.pack('<320h', *([5000]*320))):
            async def silent():
                for _ in range(100): yield pcm
            result = await guard.async_process_audio_stream(META, silent())
            self.assertEqual('', result.text)
            self.assertEqual('no_audio_energy', guard._last_diagnostic['reason'])

    async def test_quiet_device_speech_is_not_misclassified_as_silence(self):
        guard, _ = self.guard()
        async def quiet():
            frame=struct.pack('<320h', *(int(76*math.sin(2*math.pi*440*i/16000)) for i in range(320)))
            for _ in range(10): yield frame
        result=await guard.async_process_audio_stream(META,quiet())
        self.assertEqual('现在几点？',result.text)

    async def test_native_only_wake_filter_preserves_short_answers(self):
        from custom_components.r1_input_guard.policy import classify
        self.assertEqual('wake_only', classify('Alexa。', native=True))
        self.assertEqual('accepted', classify('Alexa。'))
        for text in ('好','是','嗯','再说一遍','客厅','开灯'):
            self.assertEqual('accepted', classify(text, native=True))

    async def test_total_recognition_deadline_and_zero_bytes(self):
        guard,source=self.guard()
        result=await guard.async_process_audio_stream(META,audio(0))
        self.assertEqual('',result.text)
        async def slow(metadata,stream):
            async for _ in stream:pass
            await asyncio.sleep(1)
            return stt.SpeechResult('开灯',stt.SpeechResultState.SUCCESS)
        source.internal_async_process_audio_stream.side_effect=slow
        with patch('custom_components.r1_input_guard.stt.RECOGNITION_TIMEOUT',.01):
            result=await guard.async_process_audio_stream(META,audio(1))
        self.assertEqual(stt.SpeechResultState.ERROR,result.result)

    async def test_real_ha_pipeline_bypasses_segmenter_and_does_not_intent_on_incomplete_audio(self):
        for frames,success in [(1000,True),(6051,False)]:
            guard,_=self.guard();events=[]
            run=SimpleNamespace(start_stage=PipelineStage.STT,end_stage=PipelineStage.TTS,
                audio_settings=SimpleNamespace(needs_processor=False,is_vad_enabled=True),
                intent_agent=None,stt_provider=guard,debug_recording_queue=None,tts_stream=None,
                start=lambda **kw:None,process_event=events.append,end=AsyncMock(),_capture_chunk=lambda b:None,
                recognize_intent=AsyncMock(return_value=('回复',False)),text_to_speech=AsyncMock())
            async def enhanced(stream):
                index=0
                async for data in stream:
                    # Include >0.7s silence and two short speech-separated pauses without actual audio.
                    probability=0 if 60<=index<100 or 110<=index<150 else 1
                    yield SimpleNamespace(audio=data,speech_probability=probability,timestamp_ms=index*20)
                    index+=1
            run.process_volume_only=enhanced
            run._speech_to_text_stream=MethodType(PipelineRun._speech_to_text_stream,run)
            run.speech_to_text=MethodType(PipelineRun.speech_to_text,run)
            with patch('homeassistant.components.assist_pipeline.pipeline.VoiceCommandSegmenter',side_effect=AssertionError('HA must not endpoint R1')):
                await PipelineInput(run=run,session=SimpleNamespace(conversation_id='test'),stt_metadata=META,stt_stream=audio(frames)).execute()
            if success:
                self.assertEqual(640000,self.count);run.recognize_intent.assert_awaited_once();run.text_to_speech.assert_awaited_once()
            else:
                run.recognize_intent.assert_not_awaited();run.text_to_speech.assert_not_awaited()
                self.assertEqual('stt-stream-failed',[e.data['code'] for e in events if e.type=='error'][0])

class ConversationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.agent=NativeConversation(SimpleNamespace(entry_id='native',data={'conversation_registry_id':'router'}))
        self.agent.hass=SimpleNamespace()
        self.registry=patch('custom_components.r1_input_guard.conversation.er.async_get').start()
        self.registry.return_value.async_get.return_value=SimpleNamespace(platform='conversation_router',disabled=False,entity_id='conversation.router')
        self.delegate=patch('custom_components.r1_input_guard.conversation.conversation.async_converse',new_callable=AsyncMock).start()
        self.inner=[]
        async def reply(**kwargs):
            self.inner.append(kwargs)
            response=intent.IntentResponse(language='zh-CN');response.async_set_speech('继续说？')
            return conversation.ConversationResult(response=response,conversation_id=kwargs['conversation_id'],continue_conversation=True)
        self.delegate.side_effect=reply
        self.clock=patch.object(self.agent,'_clock',return_value=0).start()
        self.addCleanup(patch.stopall)

    def user(self,text='现在几点？',satellite='assist_satellite.r1',user='user1'):
        return SimpleNamespace(text=text,conversation_id='outer',context=Context(user_id=user),language='zh-CN',device_id='r1',satellite_id=satellite)

    async def test_same_session_within_ttl_and_new_session_after_expiry(self):
        first=self.user();a=await self.agent.async_process(first)
        self.clock.return_value=90;b=await self.agent.async_process(self.user('客厅'))
        self.assertEqual(self.inner[0]['conversation_id'],self.inner[1]['conversation_id'])
        self.assertIs(first.context,self.inner[0]['context']);self.assertEqual('r1',self.inner[0]['device_id'])
        self.assertEqual('outer',a.conversation_id);self.assertTrue(b.continue_conversation)
        self.clock.return_value=991;await self.agent.async_process(self.user())
        self.assertNotEqual(self.inner[1]['conversation_id'],self.inner[2]['conversation_id'])

    async def test_explicit_end_clears_but_cancel_and_short_answers_delegate(self):
        await self.agent.async_process(self.user())
        result=await self.agent.async_process(self.user('结束对话。'))
        self.assertFalse(result.continue_conversation);self.assertEqual('',result.response.speech['plain']['speech'])
        self.assertEqual(1,len(self.inner))
        for text in ['取消','停止','好','是','嗯','客厅','５']:
            await self.agent.async_process(self.user(text))
            self.assertEqual(text,self.inner[-1]['text'])
        self.assertNotEqual(self.inner[0]['conversation_id'],self.inner[1]['conversation_id'])

    async def test_users_and_satellites_are_isolated(self):
        await self.agent.async_process(self.user())
        await self.agent.async_process(self.user(satellite='assist_satellite.other'))
        await self.agent.async_process(self.user(user='user2'))
        self.assertEqual(3,len({x['conversation_id'] for x in self.inner}))

    async def test_cancelled_delegate_clears_mapping_and_unload_clears(self):
        self.delegate.side_effect=asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):await self.agent.async_process(self.user())
        self.assertFalse(self.agent._sessions);self.assertFalse(self.agent._busy)

if __name__=='__main__':unittest.main()
