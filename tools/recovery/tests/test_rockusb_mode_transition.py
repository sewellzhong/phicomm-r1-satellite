"""Safety tests for the one-shot software Maskrom transition."""

import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "r1_rockusb_mode_transition",
    Path(__file__).parents[1] / "r1-rockusb-mode-transition.py",
)
transition = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(transition)


class Completed:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


class ModeTransitionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.adb = self.root / "adb"
        self.adb.write_text("adb")
        self.adb.chmod(0o755)
        self.tool = self.root / "rkdeveloptool"
        self.tool.write_text("reviewed")
        self.tool.chmod(0o755)
        self.original_hash = transition.RKDEVELOPTOOL_SHA256
        transition.RKDEVELOPTOOL_SHA256 = hashlib.sha256(self.tool.read_bytes()).hexdigest()
        self.calls = []

    def tearDown(self):
        transition.RKDEVELOPTOOL_SHA256 = self.original_hash
        self.temporary.cleanup()

    def runner(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if argv[-1] == "get-state":
            return Completed("device\n")
        if "getprop" in argv:
            name = argv[-1]
            return Completed(transition.EXPECTED_IDENTITY[name] + "\n")
        return Completed()

    @staticmethod
    def waiter(expected, timeout, device_provider):
        version = "2.01" if expected == "Loader" else "2.00"
        return {"mode": expected, "usb_version": version, "vid_pid": "2207:320b"}

    def run_fixture(self, **overrides):
        options = {
            "adb": self.adb,
            "tool": self.tool,
            "serial": transition.ADB_SERIAL,
            "output_dir": self.root / "evidence",
            "confirm_device": "r1-sample01",
            "command_runner": self.runner,
            "device_provider": lambda: [],
            "mode_waiter": self.waiter,
        }
        options.update(overrides)
        return transition.transition(**options)

    def test_fixed_transition_sequence_uses_no_shell(self):
        result = self.run_fixture(use_sudo=True)
        self.assertEqual("pass", result["status"])
        self.assertTrue(all(call[1]["shell"] is False for call in self.calls))
        self.assertEqual(1, sum(call[0][-2:] == ["reboot", "bootloader"] for call in self.calls))
        reset = [call[0] for call in self.calls if call[0][-1] == "reboot-maskrom"]
        self.assertEqual(1, len(reset))
        self.assertIn("/usr/bin/timeout", reset[0])

    def test_wrong_target_stops_before_commands(self):
        with self.assertRaisesRegex(transition.TransitionError, "confirmation"):
            self.run_fixture(serial="another")
        self.assertEqual([], self.calls)

    def test_identity_mismatch_stops_before_reboot(self):
        def runner(argv, **kwargs):
            result = self.runner(argv, **kwargs)
            if argv[-1] == "ro.hardware":
                return Completed("wrong\n")
            return result

        with self.assertRaisesRegex(transition.TransitionError, "identity_mismatch"):
            self.run_fixture(command_runner=runner)
        self.assertFalse(any(call[0][-2:] == ["reboot", "bootloader"] for call in self.calls))

    def test_maskrom_command_failure_is_recorded(self):
        def runner(argv, **kwargs):
            result = self.runner(argv, **kwargs)
            if argv[-1] == "reboot-maskrom":
                return Completed(returncode=124)
            return result

        with self.assertRaisesRegex(transition.TransitionError, "reboot_maskrom_failed"):
            self.run_fixture(command_runner=runner)
        evidence = (self.root / "evidence" / "mode-transition.json").read_text()
        self.assertIn('"status": "stopped"', evidence)

    def test_existing_evidence_is_not_overwritten(self):
        evidence = self.root / "evidence"
        evidence.mkdir()
        with self.assertRaises(FileExistsError):
            self.run_fixture()


if __name__ == "__main__":
    unittest.main()
