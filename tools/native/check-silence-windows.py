#!/usr/bin/env python3
"""Explicit real-microphone endpoint check; bypasses KWS and saves statistics only."""
import argparse
import importlib.util
import json
from pathlib import Path
import time

spec=importlib.util.spec_from_file_location('admin',Path(__file__).with_name('manage-r1-native.py'))
admin=importlib.util.module_from_spec(spec);spec.loader.exec_module(admin)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('serial');parser.add_argument('--rounds',type=int,default=10)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not 1 <= args.rounds <= 10:parser.error('rounds must be 1..10')
    device=admin.Device(args.serial);device.verify()
    report={'surface':'R1_real_microphone_local_admin_windows','kws_bypassed':True,
            'audio_saved':False,'human_speech_verified':False,'results':[]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    for followup in (False,True):
        for index in range(args.rounds):
            before=device.control({'action':'status'})
            if before['status']!='listening':raise RuntimeError('idle_required')
            wait_seconds = before['followup_wait_seconds'] if followup else before['wait_seconds']
            device.control({'action':'diagnostic-window','followup':followup})
            start=time.monotonic();waiting_at=None;ending_at=None;deadline=start+wait_seconds+25
            snapshots=[]
            while time.monotonic()<deadline:
                status=device.control({'action':'status'})
                elapsed=round(time.monotonic()-start,2)
                if status['status'] in ('waiting_command','waiting_followup') and waiting_at is None:
                    waiting_at=time.monotonic()
                if status['status']=='ending_conversation' and ending_at is None:
                    ending_at=time.monotonic()
                audio=status.get('audio') or {}
                snapshots.append({'elapsed':elapsed,'status':status['status'],'audio':audio})
                if audio.get('commands',0)>before['audio']['commands']:break
                if status['status']=='listening' and audio.get('no_input_windows',0)>before['audio']['no_input_windows']:break
                time.sleep(.25)
            passed=(audio.get('commands')==before['audio']['commands']
                and audio.get('no_input_windows')==before['audio']['no_input_windows']+1
                and audio.get('end_reason')=='no_input_timeout'
                and (followup or audio.get('microphone_warm_at_prompt_end') is True)
                and audio.get('ending_prompts')==before['audio'].get('ending_prompts',0)+1
                and audio.get('input_bytes')==0 and audio.get('onset_ms')==-1
                and audio.get('stt_results')==before['audio']['stt_results']
                and audio.get('tts_streams')==before['audio']['tts_streams']
                and waiting_at is not None and ending_at is not None and ending_at-waiting_at >= wait_seconds-.6)
            result={'wait_seconds':wait_seconds,'followup':followup,'round':index+1,'passed':passed,'snapshots':snapshots}
            report['results'].append(result);report['passed']=all(r['passed'] for r in report['results'])
            args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
            print(json.dumps({'followup':followup,'round':index+1,'passed':passed,'elapsed':elapsed,
                'end_reason':audio.get('end_reason'),'onset_ms':audio.get('onset_ms')}),flush=True)
            if not passed:raise RuntimeError('silence_window_failed_see_evidence')
    print('SILENCE_WINDOWS_PASSED',flush=True)

if __name__=='__main__':main()
