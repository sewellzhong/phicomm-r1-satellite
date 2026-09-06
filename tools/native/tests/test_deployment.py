"""Safety regressions for the firmware-3448 deployment tool (no device writes)."""
import importlib.util
from pathlib import Path
import unittest
import tempfile
import zipfile
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('deployment', Path(__file__).parents[1] / 'deploy-r1-native.py')
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)


class Device:
    serial = 'test-device'
    def __init__(self, state=1, denied=False):
        self.calls = []
        self.state = state
        self.denied = denied
    def adb(self, *args):
        self.calls.append(args)
        if args[:3] == ('shell', 'dumpsys', 'package'):
            return f'User 0: installed=true hidden=false enabled={self.state}\nHidden system packages:\nUser 0: enabled=0'
        if args == ('shell', 'id'): return 'uid=2000(shell)'
        if args[:2] == ('shell', 'getprop'): return '1' if args[2] == 'ro.debuggable' else ''
        if args == ('shell', 'getenforce'): return 'Enforcing'
        if args == ('shell', 'ps'): return 'USER PID NAME\nu0_a1 42 com.phicomm.speaker.player:net'
        if args[:2] == ('shell', 'run-as'): return 'run-as: Package is not an application'
        if args[:3] == ('shell', 'pm', 'path'): return 'package:/data/app/dev.sewellzhong.r1probe-2/base.apk'
        if args[:3] == ('shell', 'pm', 'enable'):
            return 'SecurityException: denied' if self.denied else 'Package new state: enabled'
        if args[:3] == ('shell', 'pm', 'disable-user'): return 'Package new state: disabled-user'
        if args[:2] == ('shell', 'dalvikvm'): return 'SecurityException: denied'
        raise AssertionError(args)


class DeploymentTest(unittest.TestCase):
    def test_host_check_apk_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "test.apk"
            with zipfile.ZipFile(apk, "w") as archive:
                archive.writestr("assets/HOST_CHECK_ONLY", "host only")
            with self.assertRaisesRegex(RuntimeError, "host_check_apk_not_deployable"):
                deploy.verify_deployable_apk(apk)

    def test_regular_archive_passes_host_marker_check(self):
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "test.apk"
            with zipfile.ZipFile(apk, "w") as archive:
                archive.writestr("assets/ack/ack-0.wav", b"fixture")
            deploy.verify_deployable_apk(apk)

    def test_hidden_system_state_does_not_override_installed_update(self):
        self.assertEqual(deploy.package_state(Device(state=3), deploy.PACKAGES[0]), 3)

    def test_cli_success_text_requires_state_readback(self):
        with self.assertRaisesRegex(RuntimeError, 'package_state_not_confirmed'):
            deploy.set_package_state(Device(state=1), deploy.PACKAGES[0], 3)

    def test_noop_permission_failure_is_not_success(self):
        with self.assertRaisesRegex(RuntimeError, 'package_state_change_denied'):
            deploy.set_package_state(Device(state=1, denied=True), deploy.PACKAGES[0], 1)

    def test_empty_cli_output_cannot_prove_noop_permission(self):
        device = Device(state=1)
        original = device.adb
        device.adb = lambda *args: '' if args[:3] == ('shell', 'pm', 'enable') else original(*args)
        with self.assertRaisesRegex(RuntimeError, 'package_state_change_denied'):
            deploy.set_package_state(device, deploy.PACKAGES[0], 1)

    def test_default_recovery_requires_helper_success(self):
        with self.assertRaisesRegex(RuntimeError, 'default_state_restore_failed'):
            deploy.set_package_state(Device(state=0), deploy.PACKAGES[1], 0)

    def test_restore_does_not_launch_services_after_failed_state_restore(self):
        device = Device(state=3, denied=True)
        with self.assertRaises(RuntimeError):
            deploy.restore_packages(device, {'package_states': dict.fromkeys(deploy.PACKAGES, 1)})
        self.assertFalse(any(call[:2] == ('shell', 'am') for call in device.calls))

    def test_diagnosis_is_read_only_and_debuggable_is_not_root_proof(self):
        device = Device()
        with patch.object(deploy, 'verify_packages', return_value=[{'package': p} for p in deploy.PACKAGES]):
            report = deploy.diagnose(device)
        self.assertFalse(report['root_attempted'])
        self.assertEqual(report['standard_adb_root'], 'candidate_not_verified')
        self.assertEqual(report['packages'][1]['processes'], ['com.phicomm.speaker.player:net'])
        allowed = {'dumpsys', 'id', 'getprop', 'getenforce', 'ps', 'run-as'}
        self.assertTrue(all(call[0] == 'shell' and call[1] in allowed for call in device.calls))


class HiddenDevice(Device):
    def __init__(self, fail_player=False, stale_readback=False):
        super().__init__()
        self.hidden = dict.fromkeys(deploy.PACKAGES, False)
        self.fail_player = fail_player
        self.stale_readback = stale_readback
        self.stopped = False
    def adb(self, *args):
        self.calls.append(args)
        if args[:3] == ('shell', 'dumpsys', 'package'):
            package = args[3]
            state = 1 if package == deploy.PACKAGES[0] else 0
            return f'User 0: installed=true hidden={str(self.hidden[package]).lower()} enabled={state}\nHidden system packages:\nUser 0: installed=true hidden=false enabled=0'
        if args[:2] == ('shell', 'pm') and args[2] in ('hide', 'unhide'):
            hidden = args[2] == 'hide'
            package = args[-1]
            if hidden and package == deploy.PACKAGES[1] and self.fail_player:
                return 'SecurityException: denied'
            if not hidden and self.hidden[package] and self.fail_player:
                if not self.stopped: raise AssertionError('native_must_stop_before_unhide')
            if not self.stale_readback: self.hidden[package] = hidden
            return 'Package new hidden state: ' + str(hidden).lower()
        if args == ('shell', 'ps'):
            return '\n'.join('u0_a1 10 ' + p for p, hidden in self.hidden.items() if not hidden)
        if args[:2] == ('shell', 'am'): return ''
        raise AssertionError(args)
    def start_control(self): pass
    def control(self, command):
        if command == {'action': 'stop'}: self.stopped = True
        return {'audio': None, 'audio_opened': False, 'health': None}


class HiddenDeploymentTest(unittest.TestCase):
    def baseline(self):
        return {'package_hidden_states': dict.fromkeys(deploy.PACKAGES, False),
                'package_states': dict(zip(deploy.PACKAGES, [1, 0]))}

    def test_hidden_readback_uses_installed_update(self):
        device = HiddenDevice()
        device.hidden[deploy.PACKAGES[1]] = True
        self.assertTrue(deploy.package_hidden(device, deploy.PACKAGES[1]))

    def test_hide_success_output_without_state_change_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'hidden_state_not_confirmed'):
            deploy.set_package_hidden(HiddenDevice(stale_readback=True), deploy.PACKAGES[0], True)

    def test_unrelated_package_cannot_be_hidden(self):
        device = HiddenDevice()
        with self.assertRaisesRegex(RuntimeError, 'unsupported_hide_target'):
            deploy.set_package_hidden(device, 'android', True)
        self.assertEqual(device.calls, [])

    def test_missing_restore_baseline_prevents_mutation(self):
        device = HiddenDevice()
        with self.assertRaisesRegex(RuntimeError, 'unhidden_baseline_required'):
            deploy.hide_packages(device, {})
        self.assertEqual(device.calls, [])

    def test_second_package_failure_restores_first_after_native_stops(self):
        device = HiddenDevice(fail_player=True)
        with self.assertRaisesRegex(RuntimeError, 'package_hide_denied'):
            deploy.hide_packages(device, self.baseline())
        self.assertTrue(device.stopped)
        self.assertFalse(any(device.hidden.values()))

    def test_unknown_audio_status_does_not_allow_original_restart(self):
        device = HiddenDevice()
        device.control = lambda command: {}
        with patch.object(deploy.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'native_audio_release_not_confirmed'):
                deploy.stop_native_audio(device)
        self.assertFalse(any(call[:2] == ('shell', 'am') for call in device.calls))

    def test_restore_hidden_baseline_does_not_start_original_services(self):
        device = HiddenDevice()
        device.hidden = dict.fromkeys(deploy.PACKAGES, True)
        baseline = self.baseline()
        baseline['package_hidden_states'] = dict(device.hidden)
        deploy.restore_packages(device, baseline)
        self.assertFalse(any(call[:2] == ('shell', 'am') for call in device.calls))

    def test_success_requires_both_hidden_and_preserved_apks(self):
        device = HiddenDevice()
        with patch.object(deploy, 'verify_packages') as verify:
            deploy.hide_packages(device, self.baseline())
            verify.assert_called_once_with(device)
        self.assertTrue(all(device.hidden.values()))


if __name__ == '__main__': unittest.main()
