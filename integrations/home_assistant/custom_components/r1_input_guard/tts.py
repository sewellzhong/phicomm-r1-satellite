"""R1-only pitch-preserving tempo conversion; no change to shared Piper options."""
import asyncio
from dataclasses import replace
from homeassistant.components import tts
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from .interaction import bridge


async def tempo_stream(source, speed):
    if not .5 <= speed <= 1.5: raise HomeAssistantError('r1_speed_invalid')
    process = await asyncio.create_subprocess_exec('/usr/bin/ffmpeg', '-hide_banner', '-loglevel', 'error',
        '-i', 'pipe:0', '-af', f'atempo={speed:.2f}', '-ar', '16000', '-ac', '1',
        '-c:a', 'pcm_s16le', '-f', 'wav', 'pipe:1', stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    async def feed():
        count = 0
        try:
            async for chunk in source:
                count += len(chunk)
                if count > 32 * 1024 * 1024: raise HomeAssistantError('r1_tts_input_limit')
                for offset in range(0, len(chunk), 32768):
                    process.stdin.write(chunk[offset:offset+32768])
                    await process.stdin.drain()
        finally:
            process.stdin.close()
    writer = asyncio.create_task(feed())
    try:
        async with asyncio.timeout(300):
            count = 0
            while chunk := await process.stdout.read(32768):
                count += len(chunk)
                if count > 10 * 1024 * 1024: raise HomeAssistantError('r1_tts_output_limit')
                yield chunk
            await writer
            if await process.wait() != 0 or count < 44: raise HomeAssistantError('r1_tts_conversion_failed')
    finally:
        writer.cancel()
        await asyncio.gather(writer, return_exceptions=True)
        if hasattr(source, 'aclose'): await source.aclose()
        if process.returncode is None:
            process.kill()
        await process.wait()


async def async_setup_entry(hass, entry, async_add_entities):
    owner = bridge(hass, entry.entry_id)
    if owner: async_add_entities([R1Speech(owner)])


class R1Speech(tts.TextToSpeechEntity):
    _attr_name = 'R1 中文回应'
    _attr_should_poll = False
    _attr_supported_languages = ['zh_CN']
    _attr_default_language = 'zh_CN'
    _attr_supported_options = ['voice', 'speaker', 'audio_output', 'r1_speed']
    _attr_default_options = {'voice': 'zh_CN-huayan-medium'}
    @property
    def default_options(self):
        speed = self.owner.number('speech_speed')
        return {'voice': 'zh_CN-huayan-medium', 'r1_speed': round(speed, 2) if speed is not None else .85}
    def __init__(self, owner):
        self.owner = owner
        self._attr_unique_id = owner.entry.entry_id + '-tts'
    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.owner.listeners.add(self.async_write_ha_state)
        self.async_on_remove(lambda: self.owner.listeners.discard(self.async_write_ha_state))
    def _source(self):
        registry = er.async_get(self.hass)
        registered = registry.async_get(self.owner.entry.data['tts_source_registry_id'])
        component = self.hass.data.get(tts.DATA_COMPONENT)
        source = component.get_entity(registered.entity_id) if registered and component else None
        if source is self: return None
        return source
    @property
    def available(self):
        source = self._source()
        return source is not None and source.available and self.owner.number('speech_speed') is not None
    def async_get_supported_voices(self, language):
        source = self._source()
        return source.async_get_supported_voices(language) if source else None
    def async_supports_streaming_input(self): return True
    async def async_stream_tts_audio(self, request):
        source = self._source()
        speed = request.options.get('r1_speed', self.owner.number('speech_speed'))
        if source is None or not source.available or speed is None: raise HomeAssistantError('r1_tts_unavailable')
        forwarded = replace(request, options={k:v for k,v in request.options.items() if k != 'r1_speed'})
        result = await source.internal_async_stream_tts_audio(forwarded)
        return tts.TTSAudioResponse('wav', tempo_stream(result.data_gen, speed))
    async def async_get_tts_audio(self, message, language, options):
        async def text(): yield message
        request = tts.TTSAudioRequest(language=language, options=options, message_gen=text())
        response = await self.async_stream_tts_audio(request)
        data = bytearray()
        async for chunk in response.data_gen: data.extend(chunk)
        return 'wav', bytes(data)
