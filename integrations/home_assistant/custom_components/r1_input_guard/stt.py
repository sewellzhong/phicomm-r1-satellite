"""Filter successful STT results before HA's pipeline reaches intent execution."""
import asyncio
from dataclasses import replace
from homeassistant.components import stt
from homeassistant.helpers import entity_registry as er
from . import DOMAIN
from .policy import classify
from .endpoint import CommandStream

RECOGNITION_TIMEOUT = 190

async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([GuardedStt(entry)])

class GuardedStt(stt.SpeechToTextEntity):
    _attr_name = "语音识别（Whisper＋无效输入过滤）"
    _attr_should_poll = False

    def __init__(self, entry):
        self._attr_unique_id = entry.entry_id
        self._source_registry_id = entry.data["source_registry_id"]
        self._last_diagnostic = {}
        self._native = entry.data.get("mode") == "r1_native"
        if self._native:
            self._attr_name = "R1 原生语音识别"
            self._attr_unique_id = entry.entry_id + "-stt"

    def _source(self):
        # Resolve every time: source entity renames/reloads must not leave a stale reference.
        registered = er.async_get(self.hass).async_get(self._source_registry_id)
        if registered is None or registered.platform == DOMAIN:
            return None
        return stt.async_get_speech_to_text_entity(self.hass, registered.entity_id)

    @property
    def available(self):
        source = self._source()
        return source is not None and source.available

    def _capability(self, name):
        source = self._source()
        return list(getattr(source, name)) if source is not None else []

    @property
    def supported_languages(self): return self._capability("supported_languages")
    @property
    def supported_formats(self): return self._capability("supported_formats")
    @property
    def supported_codecs(self): return self._capability("supported_codecs")
    @property
    def supported_bit_rates(self): return self._capability("supported_bit_rates")
    @property
    def supported_sample_rates(self): return self._capability("supported_sample_rates")
    @property
    def supported_channels(self): return self._capability("supported_channels")
    @property
    def audio_processing(self):
        source = self._source()
        processing = source.audio_processing if source is not None else super().audio_processing
        return replace(processing, requires_external_vad=False) if self._native else processing

    async def async_process_audio_stream(self, metadata, stream):
        self._last_diagnostic = {"reason": "processing", "native": self._native}
        source = self._source()
        if source is None or not source.available or not source.check_metadata(metadata):
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        # Forward lazily; no retained audio, transcript, credentials, or global per-run state.
        if self._native:
            if (metadata.format != stt.AudioFormats.WAV or metadata.codec != stt.AudioCodecs.PCM
                    or metadata.sample_rate != stt.AudioSampleRates.SAMPLERATE_16000
                    or metadata.bit_rate != stt.AudioBitRates.BITRATE_16
                    or metadata.channel != stt.AudioChannels.CHANNEL_MONO):
                return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
            bounded = CommandStream(stream)
            try:
                async with asyncio.timeout(RECOGNITION_TIMEOUT):
                    result = await source.internal_async_process_audio_stream(metadata, bounded)
            except (ValueError, TimeoutError):
                self._last_diagnostic = {"reason": "stream_error", "bytes": bounded.bytes_received}
                return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
            self._last_diagnostic = {"reason": "source_result", "bytes": bounded.bytes_received,
                "normal_eof": bounded.normal_eof, "energetic_ms": bounded.energetic_frames * 20}
            if result.result == stt.SpeechResultState.SUCCESS:
                if not bounded.normal_eof:
                    return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
                if bounded.energetic_frames < 4:
                    self._last_diagnostic["reason"] = "no_audio_energy"
                    return stt.SpeechResult("", stt.SpeechResultState.SUCCESS)
        else:
            result = await source.internal_async_process_audio_stream(metadata, stream)
        if result.result != stt.SpeechResultState.SUCCESS:
            return result
        if self._native:
            from .controls import parse_control
            control = parse_control(result.text or "")
            self._last_diagnostic["control_target"] = control.target if control else None
            self._last_diagnostic["control_operation"] = control.operation if control else None
            self._last_diagnostic["speed_homophone"] = "雨速" in (result.text or "")
        reason = classify(result.text, native=self._native)
        self._last_diagnostic["reason"] = reason
        if reason != "accepted":
            # HA 2026.8.2 raises stt-no-text-recognized before intent and TTS.
            return stt.SpeechResult("", stt.SpeechResultState.SUCCESS)
        return result
