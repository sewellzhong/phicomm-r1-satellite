#!/usr/bin/env python3
"""Synthesize fixed app copy using the existing Piper service through authorized SSH."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import wave

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'local-deps/private-prompts/assets/ack'
PHRASES = ['诶，叫我啦？', '来了来了。', '好嘞，什么安排？', '说来听听。', '你说，我接着。', '好，接下来听你的。',
           '我就知道你会叫我。', '终于轮到我啦。', '好巧，我正等着呢。', '小助手到位。']
VOICE = 'zh_CN-huayan-medium'


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    records = []
    for index, text in enumerate(PHRASES):
        event = {'type': 'synthesize', 'data': {'text': text, 'voice': {'name': VOICE}}}
        result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                                 'home-assistant', 'nc -w 5 core-piper 10200'],
                                input=(json.dumps(event, ensure_ascii=False)+'\n').encode(),
                                capture_output=True, check=True, timeout=30)
        stream = io.BytesIO(result.stdout)
        chunks, fmt, ended = [], None, False
        while line := stream.readline():
            header = json.loads(line)
            data = header.get('data', {})
            if header.get('data_length'):
                data.update(json.loads(stream.read(header['data_length'])))
            payload = stream.read(header.get('payload_length', 0))
            if header['type'] == 'audio-start':
                fmt = data
            elif header['type'] == 'audio-chunk':
                chunks.append(payload)
            elif header['type'] == 'audio-stop':
                ended = True
                break
        if not fmt or not ended or sum(map(len, chunks)) > 1024*1024:
            raise RuntimeError('invalid fixed prompt audio')
        target = ASSETS / f'ack-{index}.wav'
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source.wav'
            with wave.open(str(source), 'wb') as wav:
                wav.setnchannels(fmt['channels']); wav.setsampwidth(fmt['width'])
                wav.setframerate(fmt['rate']); wav.writeframes(b''.join(chunks))
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(source),
                            '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(target)], check=True)
        with wave.open(str(target), 'rb') as wav:
            seconds = wav.getnframes() / wav.getframerate()
            if not 0 < seconds < 4:
                raise RuntimeError('prompt duration outside limit')
        records.append({'file': target.name, 'text': text, 'group': 'daily' if index < 6 else 'occasional', 'seconds': seconds,
                        'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    (ASSETS / 'manifest.json').write_text(json.dumps({'source': 'existing HA Piper via SSH',
        'voice': VOICE, 'sample_rate': 16000, 'channels': 1, 'sample_width': 2,
        'contains_recorded_speech': False, 'phrases': records}, ensure_ascii=False, indent=2)+'\n')
    print('Generated', len(records), 'fixed acknowledgements; no microphone recording.')


if __name__ == '__main__':
    main()
