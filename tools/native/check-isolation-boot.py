#!/usr/bin/env python3
"""Reboot one R1 to verify the fail-closed guard, NOT persistent isolation acceptance.

Requires a listening satellite in temporary isolation. Leaves the satellite blocked
when the factory packages return; never stops those packages or obtains root.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import time
import subprocess

spec = importlib.util.spec_from_file_location('native_admin', Path(__file__).with_name('manage-r1-native.py'))
admin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('serial')
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--reboot', action='store_true', help='Perform one ordinary device reboot')
    args = parser.parse_args()
    if not args.reboot: parser.error('--reboot is required for this device lifecycle check')
    device = admin.Device(args.serial)
    device.verify()
    args.evidence.mkdir(parents=True, exist_ok=True)
    first = device.control({'action': 'status'})
    time.sleep(3)
    second = device.control({'action': 'status'})
    if not (first['enabled'] and first['listen'] and not first['audio_blocked']
            and first['factory_isolation'] == 'temporary_force_stop'
            and first['status'] == second['status'] == 'listening'
            and second['audio']['audio_frames'] > first['audio']['audio_frames']):
        raise RuntimeError('continuous_temporary_capture_required_before_reboot')
    (args.evidence / 'temporary-capture.json').write_text(json.dumps({'first': first, 'second': second}, indent=2) + '\n')
    device.adb('reboot')
    start = time.monotonic()
    samples = []
    while time.monotonic() - start < 150:
        try:
            device.adb('connect', args.serial)
            if device.adb('shell', 'getprop', 'sys.boot_completed') == '1':
                status = device.control({'action': 'status'})
                samples.append({'elapsed_seconds': round(time.monotonic() - start, 2), 'status': status})
                if len(samples) >= 6 and status['connections'] > 0: break
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
            pass  # Expected while adbd and the application restart. Deadline still applies.
        time.sleep(2)
    passed = len(samples) >= 6 and all(
        row['status']['audio_blocked'] and not row['status']['audio_opened']
        and row['status']['last_error'] == 'factory_audio_not_isolated'
        and row['status']['enabled'] and row['status']['listen']
        and row['status']['device_id'] == first['device_id']
        and row['status']['protocol_mac'] == first['protocol_mac'] for row in samples)
    connected = any(row['status']['connections'] > 0 for row in samples)
    report = {'surface': 'R1_API22_real_reboot_guard', 'samples': samples,
              'root_attempted': False, 'passed': passed and connected,
              'ha_connection_observed': connected, 'persistent_isolation_verified': False}
    (args.evidence / 'boot-guard.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'samples'}))
    if not report['passed']: raise RuntimeError('boot_guard_not_verified')


if __name__ == '__main__': main()
