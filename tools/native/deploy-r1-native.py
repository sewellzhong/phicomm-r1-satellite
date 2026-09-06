#!/usr/bin/env python3
"""Verified, reversible installation and exclusive-audio switch for firmware 3448."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("native_admin", Path(__file__).with_name("manage-r1-native.py"))
admin = importlib.util.module_from_spec(spec); spec.loader.exec_module(admin)
PACKAGES = ("com.phicomm.speaker.device", "com.phicomm.speaker.player")
BACKUPS = ROOT / "test-results/2026-09-01-r1-sample01/stage0/current-installed-apps"


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_packages(device):
    expected = {}
    for line in (BACKUPS / "SHA256SUMS").read_text().splitlines():
        sha, filename = line.split(maxsplit=1)
        expected[filename.lstrip('*').removeprefix('./')] = sha
    rows = []
    for package in PACKAGES:
        local = BACKUPS / (package + "-base.apk")
        if digest(local) != expected[local.name]: raise RuntimeError("package_backup_corrupt")
        remote = device.adb("shell", "pm", "path", package).removeprefix("package:").strip()
        if not remote:
            # Hidden packages remain installed; pm path may omit them for user 0.
            dump = device.adb('shell', 'dumpsys', 'package', package)
            code = re.search(r'codePath=(/data/app/' + re.escape(package) + r'-[0-9]+)\s', dump)
            if not code: raise RuntimeError('hidden_package_path_unavailable')
            remote = code[1] + '/base.apk'
        if not re.fullmatch(r"/[A-Za-z0-9_./-]+\.apk", remote): raise RuntimeError("unexpected_package_path")
        remote_hash = device.adb("shell", "busybox", "sha256sum", remote).split()[0]
        if remote_hash != expected[local.name]: raise RuntimeError("installed_package_differs_from_backup")
        rows.append({"package": package, "sha256": expected[local.name], "path": remote})
    return rows


def package_state(device, package):
    info = device.adb('shell', 'dumpsys', 'package', package)
    # First User 0 belongs to the installed update, not the hidden system APK.
    found = re.search(r'User 0:.*?enabled=(\d+)', info)
    if not found or int(found[1]) not in (0, 1, 3):
        raise RuntimeError('unknown_package_enable_state')
    return int(found[1])


def set_package_state(device, package, state):
    if package not in PACKAGES or state not in (0, 1, 3):
        raise RuntimeError('unsupported_package_state')
    if state == 0:
        apk = device.adb('shell', 'pm', 'path', admin.PACKAGE).removeprefix('package:').strip()
        if not re.fullmatch(r'/data/app/dev\.sewellzhong\.r1probe-[0-9]+/base.apk', apk):
            raise RuntimeError('unexpected_satellite_path')
        result = device.adb('shell', 'dalvikvm', '-cp', apk,
                            'dev.sewellzhong.r1probe.FactoryPackageState', package)
        if 'R1_PACKAGE_DEFAULT_RESTORED' not in result:
            raise RuntimeError('default_state_restore_failed')
    else:
        result = device.adb('shell', 'pm', {1: 'enable', 3: 'disable-user'}[state], '--user', '0', package)
        expected = {1: 'enabled', 3: 'disabled-user'}[state]
        if 'SecurityException' in result or 'Error' in result or not re.search(r'new state:\s*' + expected + r'\b', result):
            raise RuntimeError('package_state_change_denied')
    if package_state(device, package) != state:
        raise RuntimeError('package_state_not_confirmed')


def diagnose(device):
    packages = verify_packages(device)
    identity = device.adb('shell', 'id')
    uid = re.search(r'uid=(\d+)', identity)
    if not uid: raise RuntimeError('unknown_adb_identity')
    props = {name: device.adb('shell', 'getprop', name) for name in
             ('ro.build.type', 'ro.debuggable', 'ro.secure', 'ro.adb.secure', 'service.adb.root')}
    processes = device.adb('shell', 'ps')
    rows = []
    for item in packages:
        package = item['package']
        try:
            result = device.adb('shell', 'run-as', package, 'id')
            match = re.search(r'uid=(\d+)', result)
            own_uid = int(match[1]) if match else None
        except subprocess.SubprocessError:
            own_uid = None
        rows.append({**item, 'enabled_state': package_state(device, package),
                     'processes': [line.split()[-1] for line in processes.splitlines()
                                   if line.split() and (line.split()[-1] == package or line.split()[-1].startswith(package + ':'))],
                     'run_as_uid': own_uid})
    return {'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'serial': device.serial,
            'firmware': '3448', 'adb_uid': int(uid[1]), 'selinux': device.adb('shell', 'getenforce'),
            'properties': props, 'packages': rows,
            'standard_adb_root': 'active' if int(uid[1]) == 0 else
                'candidate_not_verified' if props['ro.debuggable'] == '1' else 'not_advertised',
            'package_management': 'not_verified', 'root_attempted': False,
            'recovery': 'not_assessed_by_read_only_diagnosis',
            'persistent_isolation': 'not_verified'}


def package_hidden(device, package):
    info = device.adb('shell', 'dumpsys', 'package', package)
    found = re.search(r'User 0:.*?installed=(true|false).*?hidden=(true|false)', info)
    if not found or found[1] != 'true': raise RuntimeError('installed_package_state_required')
    return found[2] == 'true'


def set_package_hidden(device, package, hidden):
    if package not in PACKAGES or type(hidden) is not bool: raise RuntimeError('unsupported_hide_target')
    result = device.adb('shell', 'pm', 'hide' if hidden else 'unhide', '--user', '0', package)
    if ('SecurityException' in result or 'Error' in result
            or 'new hidden state: ' + str(hidden).lower() not in result):
        raise RuntimeError('package_hide_denied')
    if package_hidden(device, package) != hidden: raise RuntimeError('hidden_state_not_confirmed')


def stop_native_audio(device):
    device.start_control()
    device.control({'action': 'stop'})
    for _ in range(40):
        status = device.control({'action': 'status'})
        health = status.get('health')
        if 'audio' in status and status['audio'] is None and status.get('audio_opened') is False and not (health and health.get('state') == 'running'):
            device.adb('shell', 'am', 'stopservice', '-n', admin.SERVICE)
            return
        time.sleep(.25)
    raise RuntimeError('native_audio_release_not_confirmed')


def hide_packages(device, saved):
    baseline = saved.get('package_hidden_states')
    if baseline != dict.fromkeys(PACKAGES, False): raise RuntimeError('unhidden_baseline_required')
    for package in PACKAGES:
        if package_hidden(device, package): raise RuntimeError('hidden_state_changed_since_baseline')
        if package_state(device, package) != saved['package_states'][package]:
            raise RuntimeError('package_state_changed_since_baseline')
    # Exercise the actual restoration interface before hiding either package.
    for package in PACKAGES: set_package_hidden(device, package, False)
    try:
        for package in PACKAGES: set_package_hidden(device, package, True)
        for _ in range(20):
            processes = device.adb('shell', 'ps')
            if not any(package in processes for package in PACKAGES): break
            time.sleep(.5)
        else: raise RuntimeError('audio_owner_still_running')
        if not all(package_hidden(device, package) for package in PACKAGES):
            raise RuntimeError('hidden_state_not_confirmed')
        verify_packages(device)
    except Exception:
        # Stop our audio before an unhide broadcast can restart original owners.
        stop_native_audio(device)
        restore_packages(device, saved)
        raise


def restore_packages(device, saved):
    for package in PACKAGES:
        current = package_hidden(device, package)
        baseline = saved.get('package_hidden_states', {})
        if package not in baseline and current:
            raise RuntimeError('hidden_restore_baseline_required')
        expected = baseline.get(package, False)
        if type(expected) is not bool: raise RuntimeError('invalid_hidden_baseline')
        if current != expected: set_package_hidden(device, package, expected)
    for package in PACKAGES:
        state=saved['package_states'][package]
        if package_state(device, package) != state:
            set_package_state(device, package, state)
    if saved['package_states'][PACKAGES[1]] != 3 and not saved.get('package_hidden_states', {}).get(PACKAGES[1], False):
        device.adb('shell','am','startservice','-n',PACKAGES[1]+'/.EchoService')
    if saved['package_states'][PACKAGES[0]] != 3 and not saved.get('package_hidden_states', {}).get(PACKAGES[0], False):
        device.adb('shell','am','startservice','-n',PACKAGES[0]+'/.ui.service.WindowsService')
        device.adb('shell','am','start','-n',PACKAGES[0]+'/.ui.MainActivity')
    import time
    for _ in range(20):
        processes=device.adb('shell','ps')
        if all(saved['package_states'][package]==3 or saved.get('package_hidden_states', {}).get(package, False) or package in processes for package in PACKAGES): return
        time.sleep(.5)
    raise RuntimeError('restored_audio_services_not_running')


def verify_deployable_apk(path):
    with zipfile.ZipFile(path) as apk:
        if "assets/HOST_CHECK_ONLY" in apk.namelist():
            raise RuntimeError("host_check_apk_not_deployable")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("diagnose", "install", "isolate", "hide", "restore", "commit", "rollback"))
    parser.add_argument("serial")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--apk", type=Path, default=ROOT / "android/r1-probe/app/build/outputs/apk/debug/app-debug.apk")
    args = parser.parse_args()
    if args.action == "install":
        verify_deployable_apk(args.apk)
    device = admin.Device(args.serial); device.verify()
    args.evidence.mkdir(parents=True, exist_ok=True)
    if args.action == 'diagnose':
        report = diagnose(device)
        (args.evidence / 'isolation-capabilities.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report))
        return
    baseline = args.evidence / 'deployment-baseline.json'
    if args.action == 'install':
        if not args.apk.is_file(): raise RuntimeError('apk_missing')
        packages = verify_packages(device)
        before = device.adb('shell','dumpsys','package',admin.PACKAGE)
        old_path = device.adb('shell','pm','path',admin.PACKAGE).removeprefix('package:').strip()
        if not re.fullmatch(r'/data/app/dev\.sewellzhong\.r1probe-[0-9]+/base.apk',old_path): raise RuntimeError('unexpected_satellite_path')
        old_apk = args.evidence / 'previous-satellite.apk'
        if not baseline.exists():
            device.adb('pull',old_path,str(old_apk))
            package_states = {}
            for package in PACKAGES:
                info = device.adb('shell','dumpsys','package',package)
                enabled = re.search(r'User 0:.*?enabled=(\d+)',info)
                if enabled is None or enabled[1] not in ('0','1','3'): raise RuntimeError('unknown_package_enable_state')
                package_states[package] = int(enabled[1])
            baseline.write_text(json.dumps({'serial':args.serial,'firmware':'3448','packages':packages,
                'package_states':package_states,'package_hidden_states':{p:package_hidden(device,p) for p in PACKAGES},'previous_apk_sha256':digest(old_apk),
                'previous_version':re.search(r'versionCode=(\d+)',before)[1]},indent=2))
        else:
            saved=json.loads(baseline.read_text())
            if saved['serial']!=args.serial or digest(old_apk)!=saved['previous_apk_sha256']:
                raise RuntimeError('deployment_backup_mismatch')
        # The old launcher must have completed its own restoration before upgrade.
        running = device.adb('shell','dumpsys','activity','services',admin.PACKAGE)
        if 'AssistRuntimeService' in running or 'AlexaListeningService' in running:
            raise RuntimeError('stop_old_runtime_cleanly_before_install')
        device.adb('install','-r',str(args.apk.resolve()))
        device.adb('shell','am','start','-W','-n',admin.PACKAGE+'/.MainActivity')
        device.start_control()
        print(json.dumps({'installed':True,'apk_sha256':digest(args.apk),'factory_packages_preserved':True}))
        return
    if not baseline.exists(): raise RuntimeError('verified_deployment_baseline_required')
    saved = json.loads(baseline.read_text())
    if saved['serial'] != args.serial: raise RuntimeError('device_baseline_mismatch')
    verify_packages(device)
    if args.action in ('restore','rollback'):
        installed_info=device.adb('shell','dumpsys','package',admin.PACKAGE)
        if re.search(r'versionCode=(\d+)',installed_info) and int(re.search(r'versionCode=(\d+)',installed_info)[1]) >= 44:
            stop_native_audio(device)
        restore_packages(device, saved)
        if args.action=='rollback':
            old=args.evidence/'previous-satellite.apk'
            if digest(old)!=saved['previous_apk_sha256']:raise RuntimeError('rollback_apk_corrupt')
            device.adb('install','-r','-d',str(old.resolve()))
            device.adb('shell','am','start','-W','-n',admin.PACKAGE+'/.MainActivity')
        for package in PACKAGES:
            info=device.adb('shell','dumpsys','package',package)
            found=re.search(r'User 0:.*?enabled=(\d+)',info)
            if not found or int(found[1])!=saved['package_states'][package]: raise RuntimeError('restore_state_not_confirmed')
        print(json.dumps({'action':args.action,'package_states_restored':True,'native_autostart_disabled':True}))
        return
    if args.action == 'hide':
        hide_packages(device, saved)
        print(json.dumps({'action': 'hide', 'packages_hidden': True, 'audio_packages_stopped': True,
                          'reboot_verified': False, 'root_required': False}))
        return
    if args.action=='commit':
        gate=json.loads((args.evidence/'switch-readiness.json').read_text())
        required=('real_capture','real_playback','boot_entry','health_check','restore_verified')
        if gate.get('serial')!=args.serial or any(gate.get(k) is not True for k in required):
            raise RuntimeError('exclusive_switch_readiness_not_passed')
        if gate.get('apk_sha256') != digest(args.apk): raise RuntimeError('readiness_for_different_apk')
        installed=device.adb('shell','pm','path',admin.PACKAGE).removeprefix('package:').strip()
        if not re.fullmatch(r'/data/app/dev\.sewellzhong\.r1probe-[0-9]+/base.apk',installed): raise RuntimeError('unexpected_satellite_path')
        if device.adb('shell','busybox','sha256sum',installed).split()[0]!=gate['apk_sha256']:
            raise RuntimeError('installed_apk_differs_from_readiness')
        status=device.control({'action':'status'})
        if not status['enabled'] or not status['listen'] or status['status']!='listening':
            raise RuntimeError('native_runtime_not_listening')
        # Verify the actual caller can write each original state before disabling either
        # package. This also exercises DEFAULT restoration on firmware 3448.
        for package in PACKAGES:
            if package_state(device, package) != saved['package_states'][package]:
                raise RuntimeError('package_state_changed_since_baseline')
        for package in PACKAGES:
            set_package_state(device, package, saved['package_states'][package])
        try:
            for package in PACKAGES: set_package_state(device, package, 3)
            for package in PACKAGES:
                info=device.adb('shell','dumpsys','package',package)
                if package_state(device, package) != 3:raise RuntimeError('package_disable_not_confirmed')
            import time
            for attempt in range(20):
                processes=device.adb('shell','ps')
                if not any(package in processes for package in PACKAGES): break
                time.sleep(.5)
            else: raise RuntimeError('audio_owner_still_running')
        except Exception:
            stop_native_audio(device)
            restore_packages(device, saved)
            raise

    else:
        for package in PACKAGES:device.adb('shell','am','force-stop',package)
    processes=device.adb('shell','ps')
    if any(package in processes for package in PACKAGES):raise RuntimeError('audio_owner_still_running')
    print(json.dumps({'action':args.action,'audio_packages_stopped':True,'permanent_disable':args.action=='commit'}))

if __name__=='__main__':
    try:main()
    except Exception as error:
        print('Native deployment failed: '+(str(error) if type(error) is RuntimeError else type(error).__name__),file=sys.stderr)
        sys.exit(1)
