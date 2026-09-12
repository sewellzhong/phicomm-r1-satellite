"""Real HA config-flow/platform lifecycle, with a synthetic source entity only."""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from homeassistant.core import HomeAssistant
from homeassistant import loader
from homeassistant.bootstrap import async_from_config_dict
from homeassistant.components import stt
from homeassistant.helpers import entity_registry as er

async def main():
    with TemporaryDirectory() as directory:
        Path(directory,'custom_components').symlink_to('/work/integrations/home_assistant/custom_components')
        hass=HomeAssistant(directory)
        loader.async_setup(hass)
        try:
            assert await async_from_config_dict({'stt': {}},hass) is hass
            registry=er.async_get(hass)
            class Source(stt.SpeechToTextEntity):
                _attr_name='Synthetic'
                _attr_unique_id='synthetic-test-source'
                @property
                def supported_languages(self):return ['zh']
                @property
                def supported_formats(self):return [stt.AudioFormats.WAV]
                @property
                def supported_codecs(self):return [stt.AudioCodecs.PCM]
                @property
                def supported_bit_rates(self):return [stt.AudioBitRates.BITRATE_16]
                @property
                def supported_sample_rates(self):return [stt.AudioSampleRates.SAMPLERATE_16000]
                @property
                def supported_channels(self):return [stt.AudioChannels.CHANNEL_MONO]
                async def async_process_audio_stream(self,metadata,stream):
                    async for _ in stream:pass
                    return stt.SpeechResult('。',stt.SpeechResultState.SUCCESS)
            source=Source();source.entity_id='stt.synthetic'
            await hass.data[stt.DATA_COMPONENT].async_add_entities([source])
            result=await hass.config_entries.flow.async_init('r1_input_guard',context={'source':'user'},
                data={'source_entity_id':source.entity_id})
            assert result['type']=='create_entry',(result['type'],result.get('errors'),source.entity_id,registry.async_get(source.entity_id))
            entry=result['result']
            await hass.async_block_till_done()
            assert entry.state.value=='loaded',entry.state.value
            guards=[e for e in hass.data[stt.DATA_COMPONENT].entities if e.entity_id != source.entity_id]
            assert len(guards)==1
            guard=guards[0]
            assert guard.available and guard.supported_languages==['zh']
            duplicate=await hass.config_entries.flow.async_init('r1_input_guard',context={'source':'user'},
                data={'source_entity_id':source.entity_id})
            assert duplicate['type']=='abort' and duplicate['reason']=='already_configured'
            nested=await hass.config_entries.flow.async_init('r1_input_guard',context={'source':'user'},
                data={'source_entity_id':guard.entity_id})
            assert nested['type']=='form' and nested['errors']['base']=='invalid_source'
            router=registry.async_get_or_create('conversation','conversation_router','fixture-router',suggested_object_id='router')
            native=await hass.config_entries.flow.async_init('r1_input_guard',context={'source':'user'},
                data={'source_entity_id':source.entity_id,'mode':'r1_native','conversation_entity_id':router.entity_id})
            assert native['type']=='create_entry',native.get('errors')
            native_entry=native['result']
            await hass.async_block_till_done()
            assert native_entry.state.value=='loaded',native_entry.state.value
            mac='5a:ab:ea:2d:d4:c3'
            source_registered=registry.async_get(source.entity_id)
            hass.config_entries.async_update_entry(native_entry,data={**native_entry.data,
                'interaction_mac':mac,'tts_source_registry_id':source_registered.id})
            assert await hass.config_entries.async_reload(native_entry.entry_id)
            await hass.async_block_till_done()
            assert native_entry.state.value=='loaded',native_entry.state.value
            natives=[e for e in hass.data[stt.DATA_COMPONENT].entities if getattr(e,'_native',False)]
            assert len(natives)==1 and not natives[0].audio_processing.requires_external_vad
            assert guard.audio_processing.requires_external_vad
            assert any(e.domain=='conversation' for e in registry.entities.values() if e.config_entry_id==native_entry.entry_id)
            sensor_entries=[e for e in registry.entities.values()
                            if e.domain=='sensor' and e.config_entry_id==native_entry.entry_id]
            assert len(sensor_entries)==2
            assert {e.unique_id.rsplit('-',1)[-1] for e in sensor_entries} == {'alarms','disturb'}
            assert hass.services.has_service('r1_input_guard','alarm_put')
            assert hass.services.has_service('r1_input_guard','dnd_set')
            # HA 2026.8 per-integration device registry: no DeviceInfo for the bridge.
            from homeassistant.helpers import device_registry as dr
            from custom_components.r1_input_guard.interaction import Interaction
            devices = dr.async_get(hass)
            physical=devices.async_get_or_create(config_entry_id=entry.entry_id,
                connections={('mac',mac)},name='R1 原生语音')
            orphan=devices.async_get_or_create(config_entry_id=native_entry.entry_id,
                identifiers={('r1_input_guard',mac)})
            registry.async_get_or_create('select','esphome',mac+'-pipeline',config_entry=entry,
                device_id=physical.id)
            registry.async_get_or_create('media_player','r1_input_guard','test-speaker',config_entry=native_entry,
                device_id=physical.id)
            from custom_components.r1_input_guard.interaction import bridge
            owner=bridge(hass,native_entry.entry_id)
            assert owner is not None
            owner.resolve();owner.reconcile_device()
            assert owner.device_info is None
            assert devices.async_get(orphan.id) is None
            assert devices.async_get(physical.id) is not None
            owner.reconcile_device()  # idempotent, no empty device recreated
            assert len(devices.devices)==1
            # Friendly name and Area use HA's real registries while preserving identity.
            from homeassistant.helpers import area_registry as ar
            from custom_components.r1_input_guard.device_voice import DeviceVoiceCommand, execute_device_voice
            areas=ar.async_get(hass)
            study=areas.async_create('书房')
            assert '已改为书房音箱' in await execute_device_voice(owner,DeviceVoiceCommand('set_name','书房音箱'))
            assert '已分配到书房' in await execute_device_voice(owner,DeviceVoiceCommand('set_area','书房'))
            confirmed=devices.async_get(physical.id)
            assert confirmed.id==physical.id and confirmed.name_by_user=='书房音箱' and confirmed.area_id==study.id
            assert '书房音箱' in await execute_device_voice(owner,DeviceVoiceCommand('query_name'))
            assert '书房区域' in await execute_device_voice(owner,DeviceVoiceCommand('query_area'))
            devices.async_update_device(physical.id,name_by_user='HA页面名称')
            assert 'HA页面名称' in await execute_device_voice(owner,DeviceVoiceCommand('query_name'))
            assert await hass.config_entries.async_unload(native_entry.entry_id)
            assert await hass.config_entries.async_unload(entry.entry_id)
            assert stt.async_get_speech_to_text_entity(hass,guard.entity_id) is None
            print(json.dumps({'surface':'HA_2026.8.2_container','config_flow':'passed','platform_setup':'passed',
                              'duplicate_guard':'rejected','nested_guard':'rejected','unload':'passed','native_entry_and_conversation_platform':'passed','standard_entry_preserved':'passed',
                              'alarm_sensor_platform':'passed','alarm_entity_actions':'registered',
                              'dnd_sensor_platform':'passed','dnd_entity_actions':'registered',
                              'device_registry_name_area':'passed','device_identity_preserved':True,
                              'real_microphone':False,'production_HA':False}))
        finally:
            await hass.async_stop()

asyncio.run(main())
