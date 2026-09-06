"""Explicit local configuration-admin test; fixed copy only, no saved audio."""
import asyncio
import io
import math
import wave
from homeassistant.components import tts, conversation
from homeassistant.core import Context
from homeassistant.helpers import entity_registry as er
from .interaction import bridge

async def verify(hass, entry):
    owner = bridge(hass, entry.entry_id)
    if owner is None: raise ValueError('interaction_not_loaded')
    keys = ('wait_seconds','followup_wait_seconds','quiet_seconds','command_seconds','speech_speed','volume')
    original = {key: owner.number(key) for key in keys}
    if any(value is None for value in original.values()): raise ValueError('numbers_not_ready')
    report = {'baseline': original, 'numbers': {}, 'tts_durations': {}, 'audio_saved': False}
    async def set_number(key, value):
        if key == 'volume': return await owner.set_volume(value, Context())
        target = owner.entity(key)
        await hass.services.async_call('number','set_value',{'entity_id':target,'value':value},blocking=True,context=Context())
        for _ in range(50):
            current = owner.number(key)
            if current is not None and abs(current-value)<.002:return current
            await asyncio.sleep(.1)
        raise ValueError('number_readback_failed')
    try:
        for key,value in [('wait_seconds',23),('followup_wait_seconds',27),('quiet_seconds',2.4),('command_seconds',42),('speech_speed',1.05)]:
            report['numbers'][key] = await set_number(key,value)
        target = 30 if original['volume'] > 40 else 50
        report['volume_percentages'] = {str(v): await set_number('volume',v) for v in (0,35,45,100)}
        report['numbers']['volume'] = await set_number('volume',target)
        registry=er.async_get(hass)
        entities=er.async_entries_for_config_entry(registry,entry.entry_id)
        speech=next(e for e in entities if e.domain=='tts')
        provider=hass.data[tts.DATA_COMPONENT].get_entity(speech.entity_id)
        for speed in (.5,1.5):
            await set_number('speech_speed',speed)
            ext,data=await provider.async_get_tts_audio('这是一条固定语速测试。','zh_CN',{'voice':'zh_CN-huayan-medium'})
            with wave.open(io.BytesIO(data),'rb') as wav:
                rate,channels,width=wav.getframerate(),wav.getnchannels(),wav.getsampwidth()
                count=len(wav.readframes(wav.getnframes()))
            if (rate,channels,width)!=(16000,1,2):raise ValueError('tts_format_mismatch')
            report['tts_durations'][str(speed)]=count/32000
        if not 2.5 < report['tts_durations']['0.5']/report['tts_durations']['1.5'] < 3.5:raise ValueError('tts_speed_not_effective')
        agent=next(e for e in entities if e.domain=='conversation')
        before=owner.number('volume')
        report['fixed_text_controls'] = []
        session = None
        for text, key, expected in [('音量调到35%', 'volume', 35), ('音量小一点', 'volume', 25),
                ('再小一点', 'volume', 15), ('语速调到80%', 'speech_speed', .8),
                ('语速慢一点', 'speech_speed', .75), ('再慢一点', 'speech_speed', .7),
                ('语速快一点', 'speech_speed', .75), ('正常语速', 'speech_speed', 1),
                ('唤醒后等我二十秒','wait_seconds',20), ('持续对话时等我三十秒','followup_wait_seconds',30),
                ('首次等待时间长一点','wait_seconds',25), ('续听等待时间缩短五秒','followup_wait_seconds',25),
                ('恢复首次等待时间默认值','wait_seconds',10), ('恢复续听等待时间默认值','followup_wait_seconds',15)]:
            result = await conversation.async_converse(hass, text=text, conversation_id=session, context=Context(),
                language='zh-CN', agent_id=agent.entity_id, device_id=owner.device_id,
                satellite_id=owner.entity('assist_satellite','assist_satellite'))
            session = result.conversation_id
            actual = owner.number(key)
            if actual is None or abs(actual-expected) > .002: raise ValueError('control_readback_failed')
            # Fixed administrator-supplied sentences only; never collect household transcripts.
            report['fixed_text_controls'].append({'command':text,'actual':actual,
                'reply':result.response.speech['plain']['speech']})
        await set_number('volume', before)
        await conversation.async_converse(hass,text='声音小一点',conversation_id=None,context=Context(),
            language='zh-CN',agent_id=agent.entity_id,device_id=owner.device_id,
            satellite_id=owner.entity('assist_satellite','assist_satellite'))
        after=owner.number('volume')
        if after is None or after>=before:raise ValueError('voice_volume_not_effective')
        report['volume_intent']={'before':before,'after':after,'surface':'HA_fixed_text_not_microphone'}
        await owner.refresh(None)
        report['disabled']={suffix:registry.async_get(owner.entity(suffix,'select')).disabled_by
            for suffix in ('pipeline_2','wake_word_2','vad_sensitivity')}
        report['wake_word']=hass.states.get(owner.entity('wake_word','select')).state
        if report['wake_word']!='Alexa' or not all(report['disabled'].values()):raise ValueError('config_ui_not_ready')
        volume_id = owner.entity('volume')
        report['volume_ui'] = {'state':hass.states.get(volume_id).state,
            'attributes':dict(hass.states.get(volume_id).attributes),
            'options':dict(registry.async_get(volume_id).options)}
        if report['volume_ui']['attributes']['step'] != 1: raise ValueError('volume_step_wrong')
        if report['volume_ui']['options'].get('number',{}).get('display_precision') != 0: raise ValueError('volume_precision_wrong')
        from homeassistant.helpers import device_registry as dr
        report['devices'] = [{'id':d.id,'name':d.name,'config_entry_id':d.config_entry_id} for d in dr.async_get(hass).devices.values()
            if d.id == owner.device_id or ('r1_input_guard',owner.mac) in d.identifiers]
        if len(report['devices']) != 1: raise ValueError('duplicate_device_remaining')
        # Real Whisper + actual HA pipeline, driven by fixed synthetic speech, not household audio.
        from homeassistant.components import stt
        from homeassistant.components.assist_pipeline import async_pipeline_from_audio_stream
        from homeassistant.components.assist_pipeline import pipeline as pipelines
        pipeline = next(p for p in hass.data[pipelines.KEY_ASSIST_PIPELINE].pipeline_store.async_items()
                        if p.conversation_engine == agent.entity_id)
        await set_number('speech_speed', 1)
        _, encoded = await provider.async_get_tts_audio('把音量调到百分之三十五。', 'zh_CN', {'voice':'zh_CN-huayan-medium'})
        with wave.open(io.BytesIO(encoded), 'rb') as wav:
            pcm = wav.readframes(wav.getnframes())
        metadata = stt.SpeechMetadata(language='zh', format=stt.AudioFormats.WAV, codec=stt.AudioCodecs.PCM,
            bit_rate=stt.AudioBitRates.BITRATE_16, sample_rate=stt.AudioSampleRates.SAMPLERATE_16000,
            channel=stt.AudioChannels.CHANNEL_MONO)
        async def audio():
            for offset in range(0,len(pcm),640): yield pcm[offset:offset+640]
        events=[]
        await async_pipeline_from_audio_stream(hass,context=Context(),event_callback=events.append,
            stt_metadata=metadata,stt_stream=audio(),pipeline_id=pipeline.id,
            device_id=owner.device_id,satellite_id=owner.entity('assist_satellite','assist_satellite'))
        report['synthetic_speech_pipeline']={'surface':'Piper_fixture_to_real_Whisper_HA_pipeline',
            'stages':[str(e.type) for e in events], 'volume':owner.number('volume'),
            'errors':[e.data.get('code') for e in events if e.type == pipelines.PipelineEventType.ERROR]}
        if report['synthetic_speech_pipeline']['errors'] or abs(owner.number('volume')-35)>.002:
            raise ValueError('synthetic_speech_pipeline_failed')
        report['passed']=True
    finally:
        for key,value in original.items(): await set_number(key,value)
        report['restored']={key:owner.number(key) for key in keys}
    return report

async def observe(hass, entry):
    """15-minute, explicitly requested diagnostic export. Never export event payloads wholesale."""
    from pathlib import Path
    from .commissioning import write_report
    from homeassistant.components.assist_pipeline import pipeline as pipelines
    from homeassistant.components import stt
    from datetime import datetime, timezone
    for _ in range(180):
        owner = bridge(hass, entry.entry_id)
        if owner is None: return
        data = hass.data[pipelines.KEY_ASSIST_PIPELINE]
        runs = []
        for pipeline_id, history in data.pipeline_debug.items():
            for run_id, run in history.items():
                events = []
                for event in run.events:
                    detail = event.data or {}
                    safe = {'type':str(event.type)}
                    for key in ('pipeline','satellite_id','engine','code'):
                        if key in detail: safe[key] = detail[key]
                    if event.type == pipelines.PipelineEventType.STT_END:
                        safe['text_length'] = len(detail.get('stt_output',{}).get('text',''))
                    events.append(safe)
                runs.append({'pipeline_id':pipeline_id,'run_id':run_id,'timestamp':run.timestamp,'events':events})
        registry = er.async_get(hass)
        entries = er.async_entries_for_config_entry(registry, entry.entry_id)
        stt_id = next((e.entity_id for e in entries if e.domain == 'stt'), None)
        source = stt.async_get_speech_to_text_entity(hass, stt_id) if stt_id else None
        agent_id = next((e.entity_id for e in entries if e.domain == 'conversation'), None)
        agent = hass.data[conversation.DATA_COMPONENT].get_entity(agent_id) if agent_id else None
        report = {'timestamp':datetime.now(timezone.utc).isoformat(),'runs':runs,
            'stt':getattr(source,'_last_diagnostic',{}), 'control':getattr(agent,'_last_control_diagnostic',{}),
            'entities':[{'entity_id':e.entity_id,'device_id':e.device_id,'disabled_by':e.disabled_by,
                'state':hass.states.get(e.entity_id).state if hass.states.get(e.entity_id) else None}
                for e in registry.entities.values() if e.device_id == owner.device_id]}
        await hass.async_add_executor_job(write_report,Path(hass.config.path('.r1_interaction_observation.json')),report)
        await asyncio.sleep(5)
