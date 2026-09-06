import asyncio
import io
import math
import unittest
import wave
from custom_components.r1_input_guard.volume import parse_volume
from custom_components.r1_input_guard.tts import tempo_stream
from custom_components.r1_input_guard.endpoint import CommandStream

class VolumeTest(unittest.TestCase):
    def test_percent_and_relative(self):
        self.assertEqual(('absolute',30),parse_volume('把R1音量调到百分之三十。'))
        self.assertEqual(('absolute',70),parse_volume('音量设置为70%'))
        self.assertEqual(('relative',10),parse_volume('声音大一点'))
        self.assertEqual(('relative',-10),parse_volume('小声一点'))
    def test_no_other_device_or_discussion_match(self):
        for text in ['电视音量调到30%','为什么声音大一点会更清楚','音量调到150%','音量调到百分之一百一']:
            self.assertIsNone(parse_volume(text))

class AudioTest(unittest.IsolatedAsyncioTestCase):
    async def test_long_input_and_absolute_bound(self):
        async def source(n):
            for _ in range(n):yield bytes(640)
        stream=CommandStream(source(6000))
        self.assertEqual(3840000,sum([len(x) async for x in stream]))
        self.assertTrue(stream.normal_eof)
        with self.assertRaises(ValueError):
            async for _ in CommandStream(source(6051)):pass
    async def test_tempo_changes_duration_but_keeps_format_and_pitch(self):
        raw=bytearray()
        for i in range(16000):raw.extend(int(7000*math.sin(2*math.pi*440*i/16000)).to_bytes(2,'little',signed=True))
        buf=io.BytesIO()
        with wave.open(buf,'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(raw)
        for speed in (.5,.85,1.5):
            async def source():yield buf.getvalue()
            encoded=b''.join([x async for x in tempo_stream(source(),speed)])
            with wave.open(io.BytesIO(encoded),'rb') as w:
                self.assertEqual((16000,1,2),(w.getframerate(),w.getnchannels(),w.getsampwidth()))
                samples=w.readframes(w.getnframes())
            duration=len(samples)/32000
            self.assertAlmostEqual(1/speed,duration,delta=.12)
            values=[int.from_bytes(samples[i:i+2],'little',signed=True) for i in range(0,len(samples),2)]
            crossings=sum(a<=0<b for a,b in zip(values,values[1:]))
            self.assertAlmostEqual(440,crossings/duration,delta=15)

class BridgeTest(unittest.IsolatedAsyncioTestCase):
    async def test_reload_unloads_only_platforms_that_were_loaded(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from homeassistant.const import Platform
        from custom_components.r1_input_guard import async_unload_entry
        old=[Platform.STT,Platform.CONVERSATION]
        hass=SimpleNamespace(data={'r1_input_guard_platforms':{'entry':old}},
            config_entries=SimpleNamespace(async_unload_platforms=AsyncMock(return_value=True)))
        entry=SimpleNamespace(entry_id='entry',data={'mode':'r1_native','interaction_mac':'00:00:00:00:00:01'})
        self.assertTrue(await async_unload_entry(hass,entry))
        hass.config_entries.async_unload_platforms.assert_awaited_once_with(entry,old)
    async def test_native_number_registry_format_matches_only_bound_device(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from custom_components.r1_input_guard.interaction import Interaction
        mac='5a:ab:ea:2d:d4:c3'
        def row(domain,uid,entity_id,device='r1'):
            return SimpleNamespace(platform='esphome',unique_id=uid,entity_id=entity_id,device_id=device,domain=domain)
        rows=[row('select',mac+'-pipeline','select.r1'),row('number',mac.upper()+'/0/number/语速','number.speed'),
              row('number',mac.upper()+'/0/number/语速','number.other','other')]
        registry=SimpleNamespace(entities=dict(enumerate(rows)))
        owner=Interaction.__new__(Interaction);owner.hass=SimpleNamespace();owner.mac=mac
        with patch('custom_components.r1_input_guard.interaction.er.async_get',return_value=registry):
            self.assertEqual('number.speed',owner.entity('speech_speed'))
            self.assertIsNone(owner.entity('volume'))
    async def test_volume_uses_exact_integer_percent(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from custom_components.r1_input_guard.interaction import Interaction
        owner=Interaction.__new__(Interaction)
        owner.entity=lambda suffix:'number.volume'
        owner.number=lambda suffix:35
        owner.hass=SimpleNamespace(states=SimpleNamespace(get=lambda key:SimpleNamespace(attributes={'step':6.666667})),
            services=SimpleNamespace(async_call=AsyncMock()))
        self.assertEqual(35,await owner.set_volume(35))
    async def test_nonfinite_volume_is_rejected_before_service_call(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from homeassistant.exceptions import HomeAssistantError
        from custom_components.r1_input_guard.interaction import Interaction
        owner=Interaction.__new__(Interaction);owner.entity=lambda suffix:'number.volume';owner.number=lambda suffix:40
        owner.hass=SimpleNamespace(services=SimpleNamespace(async_call=AsyncMock()))
        with self.assertRaises(HomeAssistantError):await owner.set_volume(float('nan'))
        owner.hass.services.async_call.assert_not_awaited()


class SatelliteUiCompatibilityTest(unittest.TestCase):
    def test_disabled_vad_select_keeps_actual_satellite_pipeline_startable(self):
        from types import SimpleNamespace
        from homeassistant.components.assist_satellite.entity import AssistSatelliteEntity
        from custom_components.r1_input_guard.interaction import Interaction
        class Satellite(AssistSatelliteEntity):
            async def async_get_configuration(self): return None
            async def async_set_configuration(self, config): pass
            def on_pipeline_event(self, event): pass
            @property
            def vad_sensitivity_entity_id(self): return 'select.disabled_vad'
        satellite=Satellite();satellite.hass=SimpleNamespace(states=SimpleNamespace(get=lambda key:None))
        with self.assertRaisesRegex(RuntimeError, 'VAD sensitivity entity not found'):
            satellite._resolve_vad_sensitivity()
        owner=Interaction.__new__(Interaction)
        owner._adapted_satellite=None;owner._original_vad_resolver=None;owner._vad_resolver=None
        owner.number=lambda key:2.4
        owner.adapt_satellite(satellite)
        self.assertEqual(2.4,satellite._resolve_vad_sensitivity())
        owner.number=lambda key:1.8
        owner.adapt_satellite(satellite)
        self.assertEqual(1.8,satellite._resolve_vad_sensitivity())
        owner.restore_satellite()
        with self.assertRaises(RuntimeError):satellite._resolve_vad_sensitivity()
