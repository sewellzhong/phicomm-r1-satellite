#!/usr/bin/env python3
"""Verify hidden original packages and real native capture across three R1 reboots.

Uses read-only observations after each reboot; never starts or repairs the satellite.
Does not substitute for human speech, acoustic, network or 72-hour acceptance.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import time

spec = importlib.util.spec_from_file_location('deployment', Path(__file__).with_name('deploy-r1-native.py'))
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


def sample(device):
    states = {p: deploy.package_hidden(device, p) for p in deploy.PACKAGES}
    processes = [line.split()[-1] for line in device.adb('shell', 'ps').splitlines()
                 if any(p in line for p in deploy.PACKAGES)]
    return {'runtime': device.control({'action': 'status'}), 'packages_hidden': states, 'processes': processes}


def valid(row):
    status = row['runtime']
    return (all(row['packages_hidden'].values()) and not row['processes']
            and status['enabled'] and status['listen'] and not status['audio_blocked']
            and status['last_error'] is None and status['status'] == 'listening'
            and status['factory_isolation'] == 'packages_hidden' and status['audio_opened'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('serial')
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--reboot', action='store_true')
    args = parser.parse_args()
    if not args.reboot: parser.error('--reboot is required (three ordinary reboots)')
    args.evidence.mkdir(parents=True, exist_ok=True)
    output = args.evidence / 'three-reboots.json'
    if output.exists(): raise RuntimeError('reboot_evidence_already_exists')
    device = deploy.admin.Device(args.serial)
    device.verify()
    baseline = sample(device)
    if not valid(baseline): raise RuntimeError('hidden_listening_baseline_required')
    identity = baseline['runtime']['device_id']
    report = {'serial': args.serial, 'baseline': baseline, 'cycles': [], 'passed': False}
    def save(): output.write_text(json.dumps(report, indent=2) + '\n')
    save()
    try:
        for number in range(1, 4):
            cycle = {'number': number, 'samples': [], 'passed': False}
            report['cycles'].append(cycle)
            save()
            start = time.monotonic()
            device.adb('reboot')
            previous = None
            while time.monotonic() - start < 150:
                try:
                    subprocess.run(['adb', 'connect', args.serial], capture_output=True, timeout=8)
                    device.verify()
                    if device.adb('shell', 'getprop', 'sys.boot_completed') == '1':
                        row = sample(device)
                        row['elapsed_seconds'] = round(time.monotonic() - start, 2)
                        cycle['samples'].append(row)
                        if row['processes'] or not all(row['packages_hidden'].values()):
                            raise AssertionError('original_package_returned')
                        if row['runtime']['device_id'] != identity:
                            raise AssertionError('satellite_identity_changed')
                        if valid(row) and previous is not None and valid(previous):
                            if row['runtime']['audio']['audio_frames'] > previous['runtime']['audio']['audio_frames']:
                                cycle['passed'] = True
                                cycle['capture_recovered_seconds'] = row['elapsed_seconds']
                                save()
                                print(json.dumps({'cycle': number, 'passed': True,
                                                  'capture_recovered_seconds': row['elapsed_seconds']}), flush=True)
                                break
                        previous = row
                        save()
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                    previous = None  # ADB and the app may be unavailable during boot.
                time.sleep(3)
            if not cycle['passed']: raise RuntimeError('continuous_capture_not_recovered')
        deploy.verify_packages(device)
        report['passed'] = True
    finally:
        save()
    print(json.dumps({'three_reboots_passed': report['passed'], 'human_voice_acceptance': 'not_tested'}))


if __name__ == '__main__': main()
