#!/usr/bin/env python3
"""Passive, bounded observation. It never starts/stops the satellite or records speech."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import time

spec=importlib.util.spec_from_file_location('admin',Path(__file__).with_name('manage-r1-native.py'))
admin=importlib.util.module_from_spec(spec);spec.loader.exec_module(admin)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('serial');parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--hours',type=float,default=72);parser.add_argument('--interval',type=int,default=60)
    args=parser.parse_args()
    if not 0<args.hours<=72 or not 10<=args.interval<=300:parser.error('invalid observation window')
    args.output.mkdir(parents=True,exist_ok=True)
    device=admin.Device(args.serial);device.verify()
    start=time.monotonic();duration=args.hours*3600
    summary={'started_at':datetime.now(timezone.utc).isoformat(),'planned_hours':args.hours,
             'samples':0,'unavailable_samples':0,'max_pss_kib':0,'observation_complete':False,
             'formal_stability_acceptance':'pending_review','audio_saved':False}
    if (args.output/'samples.jsonl').exists():raise RuntimeError('observation_output_already_exists')
    try:
        with (args.output/'samples.jsonl').open('x') as stream:
            while time.monotonic()-start<duration:
                row={'at':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':round(time.monotonic()-start)}
                try:
                    row['runtime']=device.control({'action':'status'})
                    memory=device.adb('shell','dumpsys','meminfo',admin.PACKAGE)
                    match=re.search(r'^\s*TOTAL\s+(\d+)',memory,re.M)
                    row['pss_kib']=int(match[1]) if match else None
                    if match:summary['max_pss_kib']=max(summary['max_pss_kib'],int(match[1]))
                except Exception as error:
                    row['unavailable']=type(error).__name__;summary['unavailable_samples']+=1
                stream.write(json.dumps(row,ensure_ascii=False)+'\n');stream.flush()
                summary['samples']+=1;summary['elapsed_seconds']=row['elapsed_seconds']
                (args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
                time.sleep(min(args.interval,max(0,duration-(time.monotonic()-start))))
        summary['observation_complete']=True
    finally:
        summary['last_updated_at']=datetime.now(timezone.utc).isoformat()
        (args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
