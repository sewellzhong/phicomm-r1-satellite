#!/usr/bin/env python3
"""Summarize numeric silence diagnostics without listening to or transcribing recordings."""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import statistics
import struct

spec=importlib.util.spec_from_file_location('decoder',Path(__file__).with_name('decode-audio-diagnostic.py'))
decoder=importlib.util.module_from_spec(spec); spec.loader.exec_module(decoder)

def analyze(directory):
    directory=Path(directory)
    metadata=json.loads((directory/'capture.r1diag.json').read_text())
    snapshots=json.loads((directory/'snapshots.json').read_text())
    before=json.loads((directory/'before.json').read_text())['audio']
    context_path=directory/'capture-context.json'
    trigger=json.loads(context_path.read_text()).get('trigger','local') if context_path.exists() else 'local'
    last=snapshots[-1]['state']
    after=last['audio']
    rows=[]
    for seq,nanos,kind,detail,pcm in decoder.records(directory/'capture.r1diag'):
        info=dict(item.split('=',1) for item in detail.split(',') if '=' in item)
        samples=struct.unpack('<'+'h'*(len(pcm)//2),pcm)
        mean=sum(samples)/len(samples) if samples else 0
        rms=math.sqrt(sum((v-mean)**2 for v in samples)/len(samples)) if samples else 0
        rows.append({'sequence':seq,'time':nanos,'kind':kind,'info':info,'samples':len(samples),'rms':rms})
    opened=next((r['time'] for r in rows if 'window_open' in r['info']),None)
    ended=next((r['time'] for r in rows if 'window_timeout' in r['info']),None)
    boundary=[]
    if opened is not None:
        for r in rows:
            if r['kind']=='processed' and opened<=r['time']<opened+300_000_000:
                boundary.append({'ms_after_window_open':round((r['time']-opened)/1e6,3),
                    'rms_ac':round(r['rms'],3),'vad':r['info'].get('vad'),
                    'speech':r['info'].get('speech'),'correlation':r['info'].get('correlation'),
                    'delay_samples':r['info'].get('delay_samples')})
    raw=[r for r in rows if r['kind']=='raw']
    intervals=[(b['time']-a['time'])/1e6 for a,b in zip(raw,raw[1:])]
    read_durations=[(r['time']-int(r['info']['read_started_ns']))/1e6 for r in raw if 'read_started_ns' in r['info']]
    keys=('commands','stt_results','tts_streams','no_input_windows','ending_prompts')
    delta={key:after[key]-before[key] for key in keys}
    result={'capture_complete':metadata['complete'],'capture_reason':metadata['reason'],
        'kws_bypassed':trigger!='alexa','scope':'one real Alexa first-command silence window' if trigger=='alexa' else 'one local-admin first-command silence window',
        'wake_delta':after.get('wake_detections',0)-before.get('wake_detections',0),
        'window_source':after.get('window_source'),
        'counter_delta':delta,'final_state':last['status'],
        'initial_prompt':next((r['info'].get('prompt') for r in rows if r['kind']=='processed' and opened is not None and r['time']>=opened),None),
        'no_upload_observed':delta['commands']==0 and after['input_bytes']==0,
        'window_wall_ms':round((ended-opened)/1e6,3) if ended and opened else None,
        'boundary_frames':boundary,
        'reference_max_us_observed':max(s['state']['audio']['reference_max_us'] for s in snapshots),
        'reference_over_budget_frames_observed':max(s['state']['audio']['reference_over_budget_frames'] for s in snapshots),
        'max_queue_offer_us':metadata['max_offer_us'],
        'raw_samples':sum(r['samples'] for r in raw),
        'raw_read_interval_ms_median':statistics.median(intervals) if intervals else None,
        'raw_read_interval_ms_max':max(intervals,default=0),
        'raw_blocking_read_ms_max':max(read_durations,default=0),
        'timing_caveat':'AudioRecord read-completion timestamps show batching; they are not hardware sample timestamps or proof of dropped samples.',
        'silence_behavior_passed':opened is not None and ended is not None and (ended-opened)/1e6 >= json.loads((directory/'before.json').read_text())['wait_seconds']*1000-600 and delta=={'commands':0,'stt_results':0,'tts_streams':0,'no_input_windows':1,'ending_prompts':1} and last['status']=='listening',
        'fault_fixed':False}
    if trigger=='alexa':
        result['silence_behavior_passed'] = (result['silence_behavior_passed'] and result['wake_delta']==1
            and result['window_source']=='alexa' and after.get('window_id',0)-before.get('window_id',0)==1)
    result['diagnostic_budget_passed'] = (metadata.get('max_offer_us',0)<=20000
        and metadata.get('max_producer_us',0)<=20000 and metadata.get('producer_over_budget',0)==0
        and result['reference_over_budget_frames_observed']==0)
    result['silence_regression_passed'] = (result['capture_complete'] and result['diagnostic_budget_passed']
        and result['silence_behavior_passed'])
    result['window_observed'] = opened is not None
    result['outcome'] = ('no_wake_window' if trigger=='alexa' and result['wake_delta']==0 and opened is None
        else 'passed' if result['silence_regression_passed'] else 'not_passed')
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('directory',type=Path)
    args=parser.parse_args(); result=analyze(args.directory)
    (args.directory/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
