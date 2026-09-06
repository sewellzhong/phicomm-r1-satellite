#!/usr/bin/env python3
"""Capture one explicitly agreed silent window; preserve raw evidence locally."""
import argparse
import importlib.util
import json
from pathlib import Path
import time

spec=importlib.util.spec_from_file_location('admin',Path(__file__).with_name('manage-r1-native.py'))
admin=importlib.util.module_from_spec(spec); spec.loader.exec_module(admin)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('serial'); parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--prompt-index',type=int,choices=range(10))
    parser.add_argument('--trigger',choices=('local','alexa'),default='local')
    args=parser.parse_args()
    if args.trigger=='alexa' and args.prompt_index is not None:
        parser.error('real Alexa uses normal random prompt selection')
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'capture-context.json').write_text(json.dumps({'trigger':args.trigger,
        'purpose':'real Alexa followed by agreed silence' if args.trigger=='alexa' else 'local prompt followed by agreed silence',
        'start_policy':'on_device_wake' if args.trigger=='alexa' else 'immediate',
        'prompt_index_requested':args.prompt_index},indent=2)+'\n')
    device=admin.Device(args.serial); device.verify()
    before=device.control({'action':'status'})
    (args.output/'before.json').write_text(json.dumps(before,indent=2)+'\n')
    device.control({'action':'diagnostic-arm' if args.trigger=='alexa' else 'diagnostic-start','seconds':30})
    snapshots=[{'elapsed':0,'state':before}]
    start=time.monotonic()
    try:
        if args.trigger=='alexa':
            print('ARMED_FOR_ONE_REAL_ALEXA',flush=True)
        else:
            time.sleep(5)
            if device.control({'action':'diagnostic-status'})['active']:
                device.control({'action':'diagnostic-window','followup':False,
                                'prompt_index':args.prompt_index if args.prompt_index is not None else -1})
        limit=125 if args.trigger=='alexa' else 30
        while time.monotonic()-start<limit:
            capture_state=device.control({'action':'diagnostic-status'})
            if not capture_state['active'] and not capture_state.get('armed',False): break
            state=device.control({'action':'status'})
            snapshots.append({'elapsed':round(time.monotonic()-start,3),'state':state})
            audio=state.get('audio') or {}
            if (state['status']=='listening' and
                    audio.get('ending_prompts',0)>before['audio']['ending_prompts']):
                time.sleep(1); break
            time.sleep(.4)
    finally:
        device.control({'action':'diagnostic-stop'})
        (args.output/'snapshots.json').write_text(json.dumps(snapshots,indent=2)+'\n')
    for _ in range(30):
        state=device.control({'action':'diagnostic-status'})
        if state['ready']: break
        time.sleep(.1)
    result=admin.export_diagnostic(device,args.output/'capture.r1diag')
    (args.output/'export.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)


if __name__=='__main__': main()
