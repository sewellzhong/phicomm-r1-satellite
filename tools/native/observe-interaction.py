#!/usr/bin/env python3
"""Passive interaction diagnostics. No audio, transcript, configuration writes, or service starts."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import time
import subprocess

spec=importlib.util.spec_from_file_location('admin',Path(__file__).with_name('manage-r1-native.py'))
admin=importlib.util.module_from_spec(spec);spec.loader.exec_module(admin)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('serial');parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=900)
    args=parser.parse_args()
    if not 1<=args.seconds<=1800:parser.error('seconds must be 1..1800')
    device=admin.Device(args.serial);device.verify()
    deadline=time.monotonic()+args.seconds;previous=None
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as stream:
        while time.monotonic()<deadline:
            try:
                state=device.control({'action':'status'})
                state['observed_at']=datetime.now(timezone.utc).isoformat()
                stream.write(json.dumps(state,ensure_ascii=False)+'\n');stream.flush()
                audio=state.get('audio') or {}
                key=(state['status'],state.get('volume_percent'),state.get('speech_speed'),audio.get('window_id'))
                if key!=previous:
                    print(json.dumps({'at':state['observed_at'],'state':key,'audio':audio},ensure_ascii=False),flush=True)
                    previous=key
            except (OSError,ValueError,RuntimeError,subprocess.SubprocessError):
                print('observation_temporarily_unavailable',flush=True)
            time.sleep(.5)

if __name__=='__main__':main()
