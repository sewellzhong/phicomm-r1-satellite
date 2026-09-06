#!/usr/bin/env python3
"""Decode local R1D1 evidence. WAVs concatenate records, NOT a gap-free shared timeline.
Use records.jsonl monotonic timestamps and recorder events for alignment.
"""
import argparse
import array
import json
import math
from pathlib import Path
import struct
import sys
import wave


def records(path):
    with Path(path).open('rb') as source:
        if source.read(4) != b'R1D1': raise ValueError('invalid_header')
        index = 0
        while True:
            header = source.read(16)
            if not header: return
            sequence, nanos = struct.unpack('>qq', header)
            if sequence != index: raise ValueError('invalid_sequence')
            index += 1
            def utf():
                length, = struct.unpack('>H', source.read(2))
                data = source.read(length)
                if len(data) != length: raise ValueError('truncated_metadata')
                return data.decode('ascii')  # Current metadata is deliberately ASCII only.
            kind, detail = utf(), utf()
            length, = struct.unpack('>i', source.read(4))
            if not 0 <= length <= 2048 or length % 2: raise ValueError('invalid_pcm_size')
            pcm = source.read(length)
            if len(pcm) != length: raise ValueError('truncated_pcm')
            yield sequence, nanos, kind, detail, pcm


def decode(source, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    streams = {}
    counts = {}
    try:
        with (destination/'records.jsonl').open('w') as metadata:
            for sequence, nanos, kind, detail, pcm in records(source):
                if kind not in ('raw','processed','playback','event'): raise ValueError('unknown_kind')
                offset = counts.get(kind, 0)
                values = array.array('h',pcm)
                if sys.byteorder != 'little': values.byteswap()
                rms = math.sqrt(sum(v*v for v in values)/len(values)) if values else 0
                if pcm:
                    if kind not in streams:
                        output = wave.open(str(destination/(kind+'.wav')),'wb')
                        output.setparams((1,2,16000,0,'NONE','not compressed')); streams[kind]=output
                    streams[kind].writeframesraw(pcm)
                    counts[kind] = offset+len(values)
                metadata.write(json.dumps({'sequence':sequence,'monotonic_ns':nanos,'kind':kind,
                    'detail':detail,'wav_sample_offset':offset,'samples':len(values),'rms':rms})+'\n')
        return counts
    finally:
        for output in streams.values(): output.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    print(json.dumps(decode(args.source,args.destination)))
