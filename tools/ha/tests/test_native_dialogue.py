"""Native endpoint/session tests in HA 2026.8.2; no real model or device calls."""
import asyncio
import hashlib
import struct
import math
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace, MethodType
from unittest.mock import AsyncMock, patch
import unittest
from homeassistant.core import Context
from homeassistant.components import stt, conversation
from homeassistant.components.conversation.chat_log import current_chat_log
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

    async def test_streaming_delegate_forwards_deltas_with_isolated_inner_id(self):
        deltas=[];nested=[];calls=[]
        self.assertGreaterEqual(self.agent.STREAMING_DELEGATE_TIMEOUT,60)
        class Target:
            supports_streaming=True
            def async_set_context(self,context): calls.append(('context',context))
            async def internal_async_process(self,user_input):
                calls.append(('start',user_input.conversation_id))
                nested[-1].delta_listener(nested[-1],{'role':'assistant','content':'第一段，'})
                calls.append(('delta',None))
                await asyncio.sleep(0)
                nested[-1].delta_listener(nested[-1],{'content':'第二段。'})
                response=intent.IntentResponse(language='zh-CN');response.async_set_speech('第一段，第二段。')
                return conversation.ConversationResult(response=response,
                    conversation_id=user_input.conversation_id,continue_conversation=True)
        @contextmanager
        def session(_hass,conversation_id):
            yield SimpleNamespace(conversation_id=conversation_id)
        @contextmanager
        def chat_log(_hass,_session,_input,chat_log_delta_listener=None):
            item=SimpleNamespace(delta_listener=chat_log_delta_listener);nested.append(item);yield item
        outer=SimpleNamespace(delta_listener=lambda _log,delta:deltas.append(delta.copy()))
        token=current_chat_log.set(outer)
        try:
            with patch('custom_components.r1_input_guard.conversation.conversation.async_get_agent',return_value=Target()), \
                    patch('custom_components.r1_input_guard.conversation.chat_session.async_get_chat_session',side_effect=session), \
                    patch('custom_components.r1_input_guard.conversation.conversation.async_get_chat_log',side_effect=chat_log):
                self.assertTrue(self.agent.supports_streaming)
                result=await self.agent.async_process(self.user())
        finally:
            current_chat_log.reset(token)
        self.assertEqual(['第一段，','第二段。'],[delta['content'] for delta in deltas])
        self.assertEqual('outer',result.conversation_id)
        self.assertNotEqual('outer',calls[1][1])
        self.assertEqual(calls[1][1],self.agent._sessions[next(iter(self.agent._sessions))][0])
        self.delegate.assert_not_awaited()

    async def test_streaming_first_delta_precedes_completion_and_cancel_blocks_stale_delta(self):
        deltas=[];nested=[]
        first_delta=asyncio.Event();release=asyncio.Event()
        class Target:
            supports_streaming=True
            def async_set_context(self,_context): pass
            async def internal_async_process(self,user_input):
                nested[-1].delta_listener(nested[-1],{'role':'assistant','content':'先播放这一段，'})
                first_delta.set()
                await release.wait()
                nested[-1].delta_listener(nested[-1],{'content':'再播放全文。'})
                response=intent.IntentResponse(language='zh-CN');response.async_set_speech('先播放这一段，再播放全文。')
                return conversation.ConversationResult(response=response,
                    conversation_id=user_input.conversation_id,continue_conversation=True)
        @contextmanager
        def session(_hass,conversation_id):
            yield SimpleNamespace(conversation_id=conversation_id)
        @contextmanager
        def chat_log(_hass,_session,_input,chat_log_delta_listener=None):
            item=SimpleNamespace(delta_listener=chat_log_delta_listener);nested.append(item);yield item
        outer=SimpleNamespace(delta_listener=lambda _log,delta:deltas.append(delta.copy()))
        token=current_chat_log.set(outer)
        try:
            with patch('custom_components.r1_input_guard.conversation.conversation.async_get_agent',return_value=Target()), \
                    patch('custom_components.r1_input_guard.conversation.chat_session.async_get_chat_session',side_effect=session), \
                    patch('custom_components.r1_input_guard.conversation.conversation.async_get_chat_log',side_effect=chat_log):
                task=asyncio.create_task(self.agent.async_process(self.user()))
                await asyncio.wait_for(first_delta.wait(),1)
                self.assertFalse(task.done())
                self.assertEqual(['先播放这一段，'],[delta['content'] for delta in deltas])
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
                nested[-1].delta_listener(nested[-1],{'content':'取消后的旧内容。'})
        finally:
            current_chat_log.reset(token)
        self.assertEqual(['先播放这一段，'],[delta['content'] for delta in deltas])
        self.assertFalse(self.agent._sessions);self.assertFalse(self.agent._busy)

    async def test_nonstreaming_delegate_does_not_claim_streaming(self):
        with patch('custom_components.r1_input_guard.conversation.conversation.async_get_agent',
                   return_value=SimpleNamespace(supports_streaming=False)):
            self.assertFalse(self.agent.supports_streaming)

    async def test_real_assist_pipeline_writes_streamed_audio_before_full_reply(self):
        """Exercise HA's real intent streaming threshold through a synthetic TTS sink."""
        nested=[];played=[];events=[]
        first_audio=asyncio.Event();release=asyncio.Event();reply_done=asyncio.Event()
        first_text=('这是第一段流式回答，用来跨过Home Assistant的流式阈值，并证明后续全文仍在生成，'
                    '此时第二段还被异步门闩阻塞，完整回答明确没有完成。')
        second_text='这是生成完成后的第二段。'

        class Target:
            supports_streaming=True
            def async_set_context(self,_context): pass
            async def internal_async_process(self,user_input):
                nested[-1].delta_listener(nested[-1],{'role':'assistant','content':first_text})
                await release.wait()
                nested[-1].delta_listener(nested[-1],{'content':second_text})
                response=intent.IntentResponse(language='zh-CN')
                response.async_set_speech(first_text+second_text)
                reply_done.set()
                return conversation.ConversationResult(response=response,
                    conversation_id=user_input.conversation_id,continue_conversation=True)

        class StreamingTts:
            supports_streaming_input=True
            engine='tts.r1';media_source_id='media-source://r1/test';token='test'
            url='/api/tts_proxy/test';content_type='audio/wav'
            task=None
            def async_set_message_stream(self,message_stream):
                async def synthesize_and_play():
                    async for text in message_stream:
                        # Deterministic stand-in for one TTS PCM write per text chunk.
                        played.append((struct.pack('<h',len(played)+1),text))
                        first_audio.set()
                self.task=asyncio.create_task(synthesize_and_play())
            def async_set_message(self,_message):
                raise AssertionError('streamed response must not fall back to full-text TTS')

        @contextmanager
        def session(_hass,conversation_id):
            yield SimpleNamespace(conversation_id=conversation_id)
        @contextmanager
        def chat_log(_hass,_session,_input,chat_log_delta_listener=None):
            item=SimpleNamespace(delta_listener=chat_log_delta_listener)
            token=current_chat_log.set(item)
            if chat_log_delta_listener is not None:
                nested.append(item)
            try: yield item
            finally: current_chat_log.reset(token)

        tts_stream=StreamingTts()
        pipeline=SimpleNamespace(conversation_language='zh-CN',prefer_local_intents=False,
            tts_language='zh-CN',tts_voice=None)
        run=SimpleNamespace(intent_agent=SimpleNamespace(id='conversation.native'),
            tts_stream=tts_stream,pipeline=pipeline,context=Context(user_id='user1'),
            hass=SimpleNamespace(states=SimpleNamespace(get=lambda _entity_id:None)),
            start_stage=PipelineStage.INTENT,end_stage=PipelineStage.TTS,
            _device_id='r1',_satellite_id='assist_satellite.r1',_conversation_data=SimpleNamespace(),
            _intent_agent_only=True,_streamed_response_text=False,process_event=events.append,
            _get_all_targets_in_satellite_area=lambda *_:False,start=lambda **_kwargs:None,end=AsyncMock())
        run.recognize_intent=MethodType(PipelineRun.recognize_intent,run)
        run.text_to_speech=MethodType(PipelineRun.text_to_speech,run)

        async def dispatch(**kwargs):
            user=conversation.ConversationInput(text=kwargs['text'],context=kwargs['context'],
                conversation_id=kwargs['conversation_id'],device_id=kwargs['device_id'],
                satellite_id=kwargs['satellite_id'],language=kwargs['language'],
                agent_id=kwargs['agent_id'],extra_system_prompt=kwargs['extra_system_prompt'])
            return await self.agent.async_process(user)

        with patch('custom_components.r1_input_guard.conversation.conversation.async_get_agent',return_value=Target()), \
                patch('homeassistant.components.assist_pipeline.pipeline.chat_session.async_get_chat_session',side_effect=session), \
                patch('homeassistant.components.assist_pipeline.pipeline.conversation.async_get_chat_log',side_effect=chat_log), \
                patch('homeassistant.components.assist_pipeline.pipeline.conversation.async_converse',new=dispatch):
            task=asyncio.create_task(PipelineInput(run=run,
                session=SimpleNamespace(conversation_id='outer'),intent_input='请给出长回答',
                device_id='r1',satellite_id='assist_satellite.r1').execute())
            await asyncio.wait_for(first_audio.wait(),1)
            self.assertFalse(reply_done.is_set())
            self.assertFalse(task.done())
            self.assertEqual([(b'\x01\x00',first_text)],played)
            release.set()
            await asyncio.wait_for(task,1)
            await asyncio.wait_for(tts_stream.task,1)

        self.assertEqual([(b'\x01\x00',first_text),(b'\x02\x00',second_text)],played)
        self.assertTrue(run._streamed_response_text)
        run.end.assert_awaited_once()
        self.assertTrue(any(event.data.get('tts_start_streaming') is True
                            for event in events if event.type.value=='intent-progress'))

    async def test_real_assist_pipeline_preserves_over_sixty_seconds_of_streamed_audio(self):
        """Long deterministic PCM chunks remain ordered, unique, and fully drained."""
        nested=[];played=[]
        first_audio=asyncio.Event();release=asyncio.Event();reply_done=asyncio.Event()
        texts=[
            '第一段长回答已经开始播放，后续内容仍在生成。' * 4,
            '第二段长回答继续播放，并在完整生成后正常结束。' * 4,
            '第三段用于确认顺序完整、没有丢句或重复播放。' * 4,
        ]
        durations=[21,21,21]

        class Target:
            supports_streaming=True
            def async_set_context(self,_context): pass
            async def internal_async_process(self,user_input):
                nested[-1].delta_listener(nested[-1],{'role':'assistant','content':texts[0]})
                await release.wait()
                for text in texts[1:]:
                    nested[-1].delta_listener(nested[-1],{'content':text})
                    await asyncio.sleep(0)
                response=intent.IntentResponse(language='zh-CN')
                response.async_set_speech(''.join(texts));reply_done.set()
                return conversation.ConversationResult(response=response,
                    conversation_id=user_input.conversation_id,continue_conversation=True)

        class StreamingTts:
            supports_streaming_input=True
            engine='tts.r1';media_source_id='media-source://r1/long';token='test'
            url='/api/tts_proxy/long';content_type='audio/wav';task=None
            def async_set_message_stream(self,message_stream):
                async def synthesize_and_play():
                    index=0
                    async for text in message_stream:
                        # One deterministic S16LE/16 kHz mono payload per text segment.
                        duration=durations[index]
                        sample=struct.pack('<h',index+1)
                        pcm=sample*(16000*duration)
                        played.append((text,duration,len(pcm),hashlib.sha256(pcm).hexdigest()))
                        index+=1;first_audio.set()
                self.task=asyncio.create_task(synthesize_and_play())
            def async_set_message(self,_message):
                raise AssertionError('long streamed response must not use full-text TTS')

        @contextmanager
        def session(_hass,conversation_id): yield SimpleNamespace(conversation_id=conversation_id)
        @contextmanager
        def chat_log(_hass,_session,_input,chat_log_delta_listener=None):
            item=SimpleNamespace(delta_listener=chat_log_delta_listener)
            token=current_chat_log.set(item)
            if chat_log_delta_listener is not None: nested.append(item)
            try: yield item
            finally: current_chat_log.reset(token)

        stream=StreamingTts()
        run=SimpleNamespace(intent_agent=SimpleNamespace(id='conversation.native'),tts_stream=stream,
            pipeline=SimpleNamespace(conversation_language='zh-CN',prefer_local_intents=False,
                                     tts_language='zh-CN',tts_voice=None),
            context=Context(user_id='user1'),
            hass=SimpleNamespace(states=SimpleNamespace(get=lambda _entity_id:None)),
            start_stage=PipelineStage.INTENT,end_stage=PipelineStage.TTS,
            _device_id='r1',_satellite_id='assist_satellite.r1',_conversation_data=SimpleNamespace(),
            _intent_agent_only=True,_streamed_response_text=False,process_event=lambda _event:None,
            _get_all_targets_in_satellite_area=lambda *_:False,start=lambda **_kwargs:None,end=AsyncMock())
        run.recognize_intent=MethodType(PipelineRun.recognize_intent,run)
        run.text_to_speech=MethodType(PipelineRun.text_to_speech,run)
        async def dispatch(**kwargs):
            return await self.agent.async_process(conversation.ConversationInput(
                text=kwargs['text'],context=kwargs['context'],conversation_id=kwargs['conversation_id'],
                device_id=kwargs['device_id'],satellite_id=kwargs['satellite_id'],language=kwargs['language'],
                agent_id=kwargs['agent_id'],extra_system_prompt=kwargs['extra_system_prompt']))

        with patch('custom_components.r1_input_guard.conversation.conversation.async_get_agent',return_value=Target()), \
                patch('homeassistant.components.assist_pipeline.pipeline.chat_session.async_get_chat_session',side_effect=session), \
                patch('homeassistant.components.assist_pipeline.pipeline.conversation.async_get_chat_log',side_effect=chat_log), \
                patch('homeassistant.components.assist_pipeline.pipeline.conversation.async_converse',new=dispatch):
            task=asyncio.create_task(PipelineInput(run=run,
                session=SimpleNamespace(conversation_id='outer'),intent_input='请给出超过一分钟的回答',
                device_id='r1',satellite_id='assist_satellite.r1').execute())
            await asyncio.wait_for(first_audio.wait(),1)
            self.assertFalse(reply_done.is_set());self.assertEqual([texts[0]],[row[0] for row in played])
            release.set();await asyncio.wait_for(task,1);await asyncio.wait_for(stream.task,1)

        self.assertEqual(texts,[row[0] for row in played])
        self.assertEqual(63,sum(row[1] for row in played))
        self.assertEqual([16000*21*2]*3,[row[2] for row in played])
        self.assertEqual(3,len({row[3] for row in played}))
        run.end.assert_awaited_once()

    async def test_tool_success_text_is_streamed_only_after_explicit_result(self):
        """The pipeline harness makes the external tool-result ordering contract observable."""
        nested=[];played=[]
        progress_audio=asyncio.Event();tool_result=asyncio.Event()
        progress=('正在执行设备操作，请稍候。' * 5)
        success='设备返回执行成功，操作已经完成。'

        class Target:
            supports_streaming=True
            def async_set_context(self,_context): pass
            async def internal_async_process(self,user_input):
                nested[-1].delta_listener(nested[-1],{'role':'assistant','content':progress})
                await tool_result.wait()
                nested[-1].delta_listener(nested[-1],{'content':success})
                response=intent.IntentResponse(language='zh-CN')
                response.async_set_speech(progress+success)
                return conversation.ConversationResult(response=response,
                    conversation_id=user_input.conversation_id,continue_conversation=True)

        class StreamingTts:
            supports_streaming_input=True
            engine='tts.r1';media_source_id='media-source://r1/tool';token='test'
            url='/api/tts_proxy/tool';content_type='audio/wav';task=None
            def async_set_message_stream(self,message_stream):
                async def play():
                    async for text in message_stream:
                        played.append(text);progress_audio.set()
                self.task=asyncio.create_task(play())
            def async_set_message(self,_message):
                raise AssertionError('tool contract must remain on streaming TTS')

        @contextmanager
        def session(_hass,conversation_id): yield SimpleNamespace(conversation_id=conversation_id)
        @contextmanager
        def chat_log(_hass,_session,_input,chat_log_delta_listener=None):
            item=SimpleNamespace(delta_listener=chat_log_delta_listener)
            token=current_chat_log.set(item)
            if chat_log_delta_listener is not None: nested.append(item)
            try: yield item
            finally: current_chat_log.reset(token)

        stream=StreamingTts()
        run=SimpleNamespace(intent_agent=SimpleNamespace(id='conversation.native'),tts_stream=stream,
            pipeline=SimpleNamespace(conversation_language='zh-CN',prefer_local_intents=False,
                                     tts_language='zh-CN',tts_voice=None),
            context=Context(user_id='user1'),hass=SimpleNamespace(states=SimpleNamespace(get=lambda _id:None)),
            start_stage=PipelineStage.INTENT,end_stage=PipelineStage.TTS,
            _device_id='r1',_satellite_id='assist_satellite.r1',_conversation_data=SimpleNamespace(),
            _intent_agent_only=True,_streamed_response_text=False,process_event=lambda _event:None,
            _get_all_targets_in_satellite_area=lambda *_:False,start=lambda **_kwargs:None,end=AsyncMock())
        run.recognize_intent=MethodType(PipelineRun.recognize_intent,run)
        run.text_to_speech=MethodType(PipelineRun.text_to_speech,run)
        async def dispatch(**kwargs):
            return await self.agent.async_process(conversation.ConversationInput(
                text=kwargs['text'],context=kwargs['context'],conversation_id=kwargs['conversation_id'],
                device_id=kwargs['device_id'],satellite_id=kwargs['satellite_id'],language=kwargs['language'],
                agent_id=kwargs['agent_id'],extra_system_prompt=kwargs['extra_system_prompt']))

        with patch('custom_components.r1_input_guard.conversation.conversation.async_get_agent',return_value=Target()), \
                patch('homeassistant.components.assist_pipeline.pipeline.chat_session.async_get_chat_session',side_effect=session), \
                patch('homeassistant.components.assist_pipeline.pipeline.conversation.async_get_chat_log',side_effect=chat_log), \
                patch('homeassistant.components.assist_pipeline.pipeline.conversation.async_converse',new=dispatch):
            task=asyncio.create_task(PipelineInput(run=run,
                session=SimpleNamespace(conversation_id='outer'),intent_input='执行设备操作',
                device_id='r1',satellite_id='assist_satellite.r1').execute())
            await asyncio.wait_for(progress_audio.wait(),1)
            self.assertEqual([progress],played);self.assertFalse(task.done())
            tool_result.set();await asyncio.wait_for(task,1);await asyncio.wait_for(stream.task,1)

        self.assertEqual([progress,success],played)
        run.end.assert_awaited_once()

    async def test_real_assist_pipeline_cancel_blocks_late_audio_write(self):
        """A retained inner chat log cannot write more TTS/playback data after cancel."""
        nested=[];played=[]
        first_audio=asyncio.Event();block=asyncio.Event()
        first_text=('这是取消测试的第一段流式回答，长度足够跨过Home Assistant当前固定的流式启动阈值，'
                    '随后任务会在第二段生成前取消，并检查旧内容无法写入播放端。')

        class Target:
            supports_streaming=True
            def async_set_context(self,_context): pass
            async def internal_async_process(self,_user_input):
                nested[-1].delta_listener(nested[-1],{'role':'assistant','content':first_text})
                await block.wait()

        class StreamingTts:
            supports_streaming_input=True
            def async_set_message_stream(self,message_stream):
                async def play():
                    async for text in message_stream:
                        played.append(text);first_audio.set()
                self.task=asyncio.create_task(play())

        @contextmanager
        def session(_hass,conversation_id): yield SimpleNamespace(conversation_id=conversation_id)
        @contextmanager
        def chat_log(_hass,_session,_input,chat_log_delta_listener=None):
            item=SimpleNamespace(delta_listener=chat_log_delta_listener);nested.append(item)
            token=current_chat_log.set(item)
            try: yield item
            finally: current_chat_log.reset(token)

        stream=StreamingTts()
        run=SimpleNamespace(intent_agent=SimpleNamespace(id='conversation.native'),tts_stream=stream,
            pipeline=SimpleNamespace(conversation_language='zh-CN',prefer_local_intents=False),
            hass=SimpleNamespace(states=SimpleNamespace(get=lambda _entity_id:None)),
            start_stage=PipelineStage.INTENT,end_stage=PipelineStage.TTS,
            context=Context(user_id='user1'),_device_id='r1',_satellite_id='assist_satellite.r1',
            _conversation_data=SimpleNamespace(),_intent_agent_only=True,_streamed_response_text=False,
            process_event=lambda _event:None,_get_all_targets_in_satellite_area=lambda *_:False,
            start=lambda **_kwargs:None,end=AsyncMock())
        run.recognize_intent=MethodType(PipelineRun.recognize_intent,run)
        run.text_to_speech=MethodType(PipelineRun.text_to_speech,run)
        async def dispatch(**kwargs):
            return await self.agent.async_process(conversation.ConversationInput(
                text=kwargs['text'],context=kwargs['context'],conversation_id=kwargs['conversation_id'],
                device_id=kwargs['device_id'],satellite_id=kwargs['satellite_id'],language=kwargs['language'],
                agent_id=kwargs['agent_id'],extra_system_prompt=kwargs['extra_system_prompt']))

        with patch('custom_components.r1_input_guard.conversation.conversation.async_get_agent',return_value=Target()), \
                patch('homeassistant.components.assist_pipeline.pipeline.chat_session.async_get_chat_session',side_effect=session), \
                patch('homeassistant.components.assist_pipeline.pipeline.conversation.async_get_chat_log',side_effect=chat_log), \
                patch('homeassistant.components.assist_pipeline.pipeline.conversation.async_converse',new=dispatch):
            task=asyncio.create_task(PipelineInput(run=run,
                session=SimpleNamespace(conversation_id='outer'),intent_input='请给出长回答',
                device_id='r1',satellite_id='assist_satellite.r1').execute())
            await asyncio.wait_for(first_audio.wait(),1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
            nested[-1].delta_listener(nested[-1],{'content':'取消后不应播放。'})
            await asyncio.sleep(0)
            self.assertEqual([first_text],played)
            run.end.assert_awaited_once()
            stream.task.cancel()
            await asyncio.gather(stream.task,return_exceptions=True)

if __name__=='__main__':unittest.main()
