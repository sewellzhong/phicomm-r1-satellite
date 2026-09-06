#!/usr/bin/env python3
"""Generate only approved fixed copy, at all supported R1 speed settings."""
import concurrent.futures
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import wave

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'local-deps/private-prompts/assets'
WAITING = ['我在听呢，你接着说。', '你说吧，我听着呢。', '我还听着呢，不着急。', '好嘞，我听着，你继续。']
ENDING = ['那这次就聊到这儿，有事再叫我。', '好嘞，这轮结束啦，想聊再叫我。', '我先不听啦，有事再叫我。', '咱们先聊到这儿，下次叫我再聊。']


def synthesize(text, target):
    event = {'type':'synthesize','data':{'text':text,'voice':{'name':'zh_CN-huayan-medium'}}}
    result = subprocess.run(['ssh','-o','BatchMode=yes','home-assistant','nc -w 5 core-piper 10200'],
                            input=(json.dumps(event,ensure_ascii=False)+'\n').encode(),capture_output=True,check=True,timeout=30)
    stream=io.BytesIO(result.stdout);chunks=[];fmt=None;ended=False
    while line:=stream.readline():
        header=json.loads(line);data=header.get('data',{})
        if header.get('data_length'):data.update(json.loads(stream.read(header['data_length'])))
        payload=stream.read(header.get('payload_length',0))
        if header['type']=='audio-start':fmt=data
        elif header['type']=='audio-chunk':chunks.append(payload)
        elif header['type']=='audio-stop':ended=True;break
    if not fmt or not ended or sum(map(len,chunks))>1024*1024:raise RuntimeError('invalid_prompt_audio')
    with wave.open(str(target),'wb') as wav:
        wav.setnchannels(fmt['channels']);wav.setsampwidth(fmt['width']);wav.setframerate(fmt['rate']);wav.writeframes(b''.join(chunks))


def main():
    target=ASSETS/'interaction';target.mkdir(exist_ok=True)
    records=[]
    with tempfile.TemporaryDirectory() as temp:
        sources=[('ack',i,ASSETS/'ack'/f'ack-{i}.wav') for i in range(10)]
        for group,phrases in [('waiting',WAITING),('ending',ENDING)]:
            for i,text in enumerate(phrases):
                source=Path(temp)/f'{group}-{i}.wav';synthesize(text,source);sources.append((group,i,source))
        def convert(job):
            group,i,source,rate=job;dest=target/str(rate)/f'{group}-{i}.wav';dest.parent.mkdir(exist_ok=True)
            subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(source),'-af',f'atempo={rate/100:.2f}',
                '-ar','16000','-ac','1','-c:a','pcm_s16le','-threads','1',str(dest)],check=True)
            with wave.open(str(dest),'rb') as wav:
                seconds=wav.getnframes()/wav.getframerate()
                if not 0<seconds<14:raise RuntimeError('prompt_length_invalid')
            return {'file':str(dest.relative_to(target)),'seconds':seconds,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()}
        jobs=[(group,i,source,rate) for group,i,source in sources for rate in range(50,151,5)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:records=list(pool.map(convert,jobs))
    (target/'manifest.json').write_text(json.dumps({'source':'Piper fixed synthetic copy; FFmpeg atempo',
        'waiting':WAITING,'ending':ENDING,'rates_percent':list(range(50,151,5)),'recordings_saved':False,
        'sample_rate':16000,'channels':1,'sample_width':2,'files':records},ensure_ascii=False,indent=2)+'\n')
    print(f'Generated {len(records)} fixed prompt variants')


if __name__=='__main__':main()
