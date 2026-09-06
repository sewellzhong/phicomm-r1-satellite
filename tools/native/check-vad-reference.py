#!/usr/bin/env python3
"""Offline numeric-only replay of the existing consented R1 acceptance fixtures."""
import ctypes
import json
import math
from pathlib import Path
import struct
import wave

ROOT=Path(__file__).resolve().parents[2]
lib=ctypes.CDLL(str(ROOT/'local-deps/build/fvad-host/libfvad.so'))
lib.fvad_new.restype=ctypes.c_void_p
lib.fvad_free.argtypes=[ctypes.c_void_p]
lib.fvad_set_mode.argtypes=[ctypes.c_void_p,ctypes.c_int]
lib.fvad_set_sample_rate.argtypes=[ctypes.c_void_p,ctypes.c_int]
lib.fvad_process.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_int16),ctypes.c_size_t]
source=ROOT/'test-results/2026-09-03T044732-r1-sample01/stage1/processed-speech-acceptance/audio'
report={'source':str(source.relative_to(ROOT)),'purpose':'offline VAD gain comparison; no audio copied','rows':[]}
for name in ('silence-raw.wav','speech-raw.wav'):
 with wave.open(str(source/name),'rb') as w:
  assert (w.getnchannels(),w.getsampwidth(),w.getframerate())==(1,2,16000)
  pcm=w.readframes(w.getnframes())
 for gain in (1,4,8,16):
  vad=lib.fvad_new();lib.fvad_set_mode(vad,2);lib.fvad_set_sample_rate(vad,16000)
  bits=strong=voiced=0;starts=[];first=None
  for off in range(0,len(pcm)-639,640):
   frame=struct.unpack_from('<320h',pcm,off);mean=sum(frame)/320
   rms=math.sqrt(max(0,sum(v*v for v in frame)/320-mean*mean))
   scaled=(ctypes.c_int16*320)(*(max(-32768,min(32767,v*gain)) for v in frame))
   active=lib.fvad_process(vad,scaled,320)==1;voiced+=active
   speech=active and rms>=28
   bits=((bits<<1)|speech)&0x7fff;strong=strong+1 if speech and rms>=56 else 0
   if bits.bit_count()>=10 or strong>=6:
    starts.append(off//32)
  lib.fvad_free(vad)
  report['rows'].append({'file':name,'gain':gain,'vad_ms':voiced*20,'qualified_frames':len(starts),'first_qualified_ms':starts[0] if starts else None})
print(json.dumps(report,ensure_ascii=False,indent=2))
