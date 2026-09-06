"""Run against HA 2026.8.2 image. Synthetic STT, real HA pipeline orchestration."""
import asyncio
import unittest
from types import SimpleNamespace, MethodType
from unittest.mock import AsyncMock, patch
from homeassistant.components import stt
from homeassistant.components.assist_pipeline.pipeline import PipelineInput, PipelineRun, PipelineStage
from custom_components.r1_input_guard.policy import classify
from custom_components.r1_input_guard.stt import GuardedStt

async def audio():
    yield b'\0' * 640

class PolicyTest(unittest.TestCase):
    def test_empty_and_markers(self):
        for text in [None, '', '。', '！？…', '\u200b\ufeff\u3000', '🎵', '[BLANK_AUDIO]',
                     '[no speech]', '(silence)', '【噪音】', '<|nospeech|>', '[音乐]。(noise)']:
            with self.subTest(text=text): self.assertNotEqual('accepted',classify(text))

    def test_valid_input_and_missing_context_are_preserved(self):
        for text in ['现在什么时间？','现在几点？','开灯','停','好','不','是','否','5','５','嗯','算了',
                     '取消','Alexa','奥ex斯','欧ex萨','音乐','播放[音乐]','谢谢观看','我听着呢',
                     '谢谢观看谢谢观看谢谢观看谢谢观看','𠀀','[music]🎵打开灯']:
            with self.subTest(text=text): self.assertEqual('accepted',classify(text))

class AdapterTest(unittest.IsolatedAsyncioTestCase):
    def guard(self, text='现在几点？', state=stt.SpeechResultState.SUCCESS):
        entry=SimpleNamespace(entry_id='guard',data={'source_registry_id':'registry-uuid'})
        guard=GuardedStt(entry);guard.hass=SimpleNamespace();guard.entity_id='stt.r1_input_guard'
        source=SimpleNamespace(available=True,check_metadata=lambda m:True,
            audio_processing=stt.DEFAULT_AUDIO_PROCESSING,
            internal_async_process_audio_stream=AsyncMock(return_value=stt.SpeechResult(text,state)))
        guard._source=lambda:source
        return guard,source

    async def test_filter_and_exact_passthrough(self):
        guard,source=self.guard('。');stream=audio();metadata=object()
        result=await guard.async_process_audio_stream(metadata,stream)
        self.assertEqual('',result.text);self.assertEqual(stt.SpeechResultState.SUCCESS,result.result)
        source.internal_async_process_audio_stream.assert_awaited_once_with(metadata,stream)
        original=stt.SpeechResult('  现在几点？  ',stt.SpeechResultState.SUCCESS)
        source.internal_async_process_audio_stream.return_value=original
        self.assertIs(original,await guard.async_process_audio_stream(metadata,stream))

    async def test_error_is_not_disguised_as_empty(self):
        guard,source=self.guard('。',stt.SpeechResultState.ERROR)
        result=await guard.async_process_audio_stream(object(),audio())
        self.assertEqual(stt.SpeechResultState.ERROR,result.result)
        source.internal_async_process_audio_stream.side_effect=TimeoutError
        with self.assertRaises(TimeoutError):await guard.async_process_audio_stream(object(),audio())
        source.internal_async_process_audio_stream.side_effect=asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):await guard.async_process_audio_stream(object(),audio())

    async def test_missing_unavailable_and_metadata_fail_closed(self):
        guard,source=self.guard()
        source.available=False
        self.assertEqual(stt.SpeechResultState.ERROR,(await guard.async_process_audio_stream(None,audio())).result)
        source.available=True;source.check_metadata=lambda m:False
        self.assertEqual(stt.SpeechResultState.ERROR,(await guard.async_process_audio_stream(None,audio())).result)
        guard._source=lambda:None
        self.assertFalse(guard.available)
        self.assertEqual([],guard.supported_languages)
        self.assertEqual(stt.SpeechResultState.ERROR,(await guard.async_process_audio_stream(None,audio())).result)
        source.internal_async_process_audio_stream.assert_not_awaited()

    def test_source_rename_and_no_nested_guards(self):
        guard=GuardedStt(SimpleNamespace(entry_id='guard',data={'source_registry_id':'uuid'}))
        guard.hass=SimpleNamespace()
        registered=SimpleNamespace(platform='wyoming',entity_id='stt.new_name')
        with patch('custom_components.r1_input_guard.stt.er.async_get') as registry, \
             patch('custom_components.r1_input_guard.stt.stt.async_get_speech_to_text_entity') as lookup:
            registry.return_value.async_get.return_value=registered
            self.assertIs(lookup.return_value,guard._source())
            lookup.assert_called_once_with(guard.hass,'stt.new_name')
            registered.platform='r1_input_guard'
            self.assertIsNone(guard._source())

    async def test_concurrent_results_do_not_cross(self):
        guard,source=self.guard()
        async def recognize(metadata,stream):
            await asyncio.sleep(0)
            return stt.SpeechResult(metadata,stt.SpeechResultState.SUCCESS)
        source.internal_async_process_audio_stream.side_effect=recognize
        results=await asyncio.gather(*(guard.async_process_audio_stream(t,audio()) for t in ['。','开灯','[noise]','5']))
        self.assertEqual(['','开灯','','5'],[r.text for r in results])

    async def test_real_ha_pipeline_never_calls_intent_or_tts_on_ignored_text(self):
        for text,expected in [('。','stt-no-text-recognized'),('[BLANK_AUDIO]','stt-no-text-recognized'),
                              ('现在什么时间？',None),('好',None)]:
            guard,_=self.guard(text)
            events=[]
            run=SimpleNamespace(start_stage=PipelineStage.STT,end_stage=PipelineStage.TTS,
                audio_settings=SimpleNamespace(needs_processor=False,is_vad_enabled=False),
                intent_agent=None,stt_provider=guard,debug_recording_queue=None,tts_stream=None,
                start=lambda **kw:None,process_event=events.append,end=AsyncMock(),
                recognize_intent=AsyncMock(return_value=('下午五点',False)),text_to_speech=AsyncMock())
            run.process_volume_only=lambda stream:stream
            run._speech_to_text_stream=lambda audio_stream,stt_vad:audio_stream
            # Execute the installed HA method unchanged, not a reimplementation of its guard.
            run.speech_to_text=MethodType(PipelineRun.speech_to_text,run)
            metadata=stt.SpeechMetadata(language='zh',format=stt.AudioFormats.WAV,codec=stt.AudioCodecs.PCM,
                bit_rate=stt.AudioBitRates.BITRATE_16,sample_rate=stt.AudioSampleRates.SAMPLERATE_16000,
                channel=stt.AudioChannels.CHANNEL_MONO)
            await PipelineInput(run=run,session=SimpleNamespace(conversation_id='test'),
                                stt_metadata=metadata,stt_stream=audio()).execute()
            if expected:
                run.recognize_intent.assert_not_awaited();run.text_to_speech.assert_not_awaited()
                self.assertEqual([expected],[e.data['code'] for e in events if e.type=='error'])
            else:
                self.assertEqual(text,run.recognize_intent.call_args.args[0])
                run.text_to_speech.assert_awaited_once()
            run.end.assert_awaited_once()

if __name__=='__main__':unittest.main()
