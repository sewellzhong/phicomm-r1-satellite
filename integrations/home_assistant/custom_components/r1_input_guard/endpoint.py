"""R1 owns the endpoint; the STT result is accepted only after bounded normal EOF."""
import asyncio
import time
import struct

class InputStreamError(ValueError):
    """Incomplete or unsupported command audio (no transcript in the error)."""

class CommandStream:
    MAX_BYTES = 3872000  # 121 seconds (120s plus onset prebuffer), 16 kHz, mono, S16LE
    IDLE_SECONDS = 5
    INPUT_SECONDS = 130

    def __init__(self, stream):
        self._stream = stream.__aiter__()
        self._deadline = time.monotonic() + self.INPUT_SECONDS
        self.bytes_received = 0
        self.normal_eof = False
        self.energetic_frames = 0
        self._frame = bytearray()

    def __aiter__(self):
        return self

    async def __anext__(self):
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise InputStreamError("input_deadline")
        try:
            chunk = await asyncio.wait_for(anext(self._stream), min(self.IDLE_SECONDS, remaining))
        except StopAsyncIteration:
            self.normal_eof = True
            raise
        except TimeoutError as err:
            raise InputStreamError("input_stalled") from err
        if not isinstance(chunk, bytes) or len(chunk) % 2:
            raise InputStreamError("invalid_pcm")
        self.bytes_received += len(chunk)
        if self.bytes_received > self.MAX_BYTES:
            raise InputStreamError("input_too_long")
        self._frame.extend(chunk)
        consumed = len(self._frame) // 640 * 640
        for offset in range(0, consumed, 640):
            values = struct.unpack_from('<320h', self._frame, offset)
            mean = sum(values) / 320
            variance = sum(v*v for v in values) / 320 - mean*mean
            if variance >= 576: self.energetic_frames += 1
        del self._frame[:consumed]
        return chunk
