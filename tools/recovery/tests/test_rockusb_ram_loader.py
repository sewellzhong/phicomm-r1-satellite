"""Safety tests for the bounded RK3229 RAM-loader workflow."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "r1_rockusb_ram_loader", Path(__file__).parents[1] / "r1-rockusb-ram-loader.py"
)
loader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(loader)


class Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class RamLoaderTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.tool = self.root / "rkdeveloptool"
        self.tool.write_bytes(b"reviewed-tool")
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        self.loader_file = self.bundle / "loader.bin"
        self.loader_file.write_bytes(b"loader")
        self.history = self.root / "history"
        self.history.mkdir()
        self.calls = []

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def device():
        return [{"sysfs_name": "1-1", "vid_pid": loader.VID_PID, "mode": "Maskrom"}]

    def validator(self, bundle_dir, command_runner):
        return (
            self.loader_file,
            hashlib.sha256(self.loader_file.read_bytes()).hexdigest(),
            loader.CANDIDATE_CANONICAL_SHA256,
        )

    def runner(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        command = argv[-1]
        if "list" in argv:
            return Completed(stdout="DevNo=1 Vid=0x2207,Pid=0x320b Loader\n")
        if command == "read-flash-info":
            return Completed(stdout="Flash Info:\n\tFlash Size: 7456 MB\n")
        if command == "read-capability":
            return Completed(stdout="\n".join(loader.REQUIRED_CAPABILITIES) + "\n")
        return Completed(stdout="OK\n")

    def run_fixture(self, **overrides):
        original = loader.RKDEVELOPTOOL_SHA256
        loader.RKDEVELOPTOOL_SHA256 = hashlib.sha256(self.tool.read_bytes()).hexdigest()
        options = {
            "tool": self.tool,
            "bundle_dir": self.bundle,
            "output_dir": self.root / "evidence",
            "attempt_history": self.history,
            "device_provider": self.device,
            "command_runner": self.runner,
            "bundle_validator": self.validator,
        }
        options.update(overrides)
        try:
            return loader.run_load_probe(**options)
        finally:
            loader.RKDEVELOPTOOL_SHA256 = original

    def test_success_sequence_contains_only_boot_and_reads(self):
        first_list = True

        def runner(argv, **kwargs):
            nonlocal first_list
            self.calls.append((argv, kwargs))
            if argv[-1] == "list":
                mode = "Maskrom" if first_list else "Loader"
                first_list = False
                return Completed(stdout=f"DevNo=1 {mode}\n")
            if argv[-1] == "read-flash-info":
                return Completed(stdout="Flash Size: 7456 MB\n")
            if argv[-1] == "read-capability":
                return Completed(stdout="\n".join(loader.REQUIRED_CAPABILITIES) + "\n")
            return Completed(stdout="OK\n")

        result = self.run_fixture(command_runner=runner)
        self.assertEqual("pass", result["status"])
        commands = [call[0][-1] if call[0][-2] != "boot" else "boot" for call in self.calls]
        self.assertEqual(
            ["list", "boot", "list", *loader.READ_COMMANDS, "list-partitions"], commands
        )
        self.assertFalse(any(command in loader.FORBIDDEN_COMMANDS for command in commands))
        self.assertTrue(all(call[1]["shell"] is False for call in self.calls))

    def test_initial_mode_must_be_maskrom(self):
        calls = 0

        def loader_device():
            nonlocal calls
            calls += 1
            return [{"sysfs_name": "1-1", "vid_pid": loader.VID_PID,
                     "mode": "Maskrom" if calls == 1 else "Loader"}]

        with self.assertRaisesRegex(loader.LoaderError, "expected_maskrom_mode"):
            self.run_fixture(device_provider=loader_device)
        self.assertEqual(1, len(self.calls))

    def test_sysfs_loader_mode_prevents_ram_loader_command(self):
        with self.assertRaisesRegex(loader.LoaderError, "initial_usb_mode_not_maskrom:Loader"):
            self.run_fixture(device_provider=lambda: [{
                "sysfs_name": "1-1", "vid_pid": loader.VID_PID, "mode": "Loader"
            }])
        self.assertEqual([], self.calls)

    def test_boot_failure_stops_before_read_commands(self):
        first = True

        def runner(argv, **kwargs):
            nonlocal first
            self.calls.append((argv, kwargs))
            if argv[-1] == "list" and first:
                first = False
                return Completed(stdout="Maskrom\n")
            if "boot" in argv:
                return Completed(returncode=1, stderr="failed")
            return Completed(stdout="Loader\n")

        with self.assertRaisesRegex(loader.LoaderError, "command_failed:boot"):
            self.run_fixture(command_runner=runner)
        self.assertEqual(1, sum("boot" in call[0] for call in self.calls))

    def test_unexpected_capacity_stops_before_partition_read(self):
        first = True

        def runner(argv, **kwargs):
            nonlocal first
            self.calls.append((argv, kwargs))
            if argv[-1] == "list":
                mode = "Maskrom" if first else "Loader"
                first = False
                return Completed(stdout=mode)
            if argv[-1] == "read-flash-info":
                return Completed(stdout="Flash Size: 1024 MB")
            if argv[-1] == "read-capability":
                return Completed(stdout="\n".join(loader.REQUIRED_CAPABILITIES))
            return Completed(stdout="OK")

        with self.assertRaisesRegex(loader.LoaderError, "flash_capacity_unexpected"):
            self.run_fixture(command_runner=runner)
        self.assertFalse(any(call[0][-1] == "list-partitions" for call in self.calls))

    def test_timeout_stops_without_retry(self):
        first = True

        def runner(argv, **kwargs):
            nonlocal first
            self.calls.append((argv, kwargs))
            if argv[-1] == "list":
                mode = "Maskrom" if first else "Loader"
                first = False
                return Completed(stdout=mode)
            if "boot" in argv:
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
            return Completed(stdout="OK")

        with self.assertRaisesRegex(loader.LoaderError, "command_timeout:boot"):
            self.run_fixture(command_runner=runner)
        self.assertEqual(1, sum("boot" in call[0] for call in self.calls))

    def test_missing_first4m_capability_stops_before_partition_listing(self):
        first = True

        def runner(argv, **kwargs):
            nonlocal first
            self.calls.append((argv, kwargs))
            if argv[-1] == "list":
                mode = "Maskrom" if first else "Loader"
                first = False
                return Completed(stdout=mode)
            if argv[-1] == "read-capability":
                return Completed(stdout="Direct LBA:\tenabled\nRead LBA:\tenabled\n")
            if argv[-1] == "read-flash-info":
                return Completed(stdout="Flash Size: 7456 MB\n")
            return Completed(stdout="OK")

        with self.assertRaisesRegex(loader.LoaderError, "required_capability_missing"):
            self.run_fixture(command_runner=runner)
        self.assertFalse(any(call[0][-1] == "list-partitions" for call in self.calls))

    def test_sudo_uses_root_side_timeout(self):
        first = True

        def runner(argv, **kwargs):
            nonlocal first
            self.calls.append((argv, kwargs))
            if argv[-1] == "list":
                mode = "Maskrom" if first else "Loader"
                first = False
                return Completed(stdout=mode)
            if argv[-1] == "read-capability":
                return Completed(stdout="\n".join(loader.REQUIRED_CAPABILITIES))
            if argv[-1] == "read-flash-info":
                return Completed(stdout="Flash Size: 7456 MB\n")
            return Completed(stdout="OK")

        self.run_fixture(command_runner=runner, use_sudo=True)
        self.assertTrue(all("/usr/bin/timeout" in call[0] for call in self.calls))

    def test_wrong_device_count_prevents_transport(self):
        with self.assertRaisesRegex(loader.LoaderError, "found_0"):
            self.run_fixture(device_provider=lambda: [])
        self.assertEqual([], self.calls)

    def write_attempt(self, loader_hash, commands=None, candidate_id=None,
                      canonical_hash=None):
        attempt_dir = self.history / f"attempt-{len(list(self.history.iterdir()))}"
        attempt_dir.mkdir()
        evidence = {
            "device_id": loader.DEVICE_ID,
            "loader_sha256": loader_hash,
            "commands": commands if commands is not None else [
                {"arguments": ["boot", "/private/loader.bin"]}
            ],
        }
        if candidate_id is not None:
            evidence["candidate_id"] = candidate_id
        if canonical_hash is not None:
            evidence["loader_canonical_sha256"] = canonical_hash
        (attempt_dir / "ram-loader-probe.json").write_text(json.dumps(evidence))

    def test_same_loader_attempt_is_rejected_before_usb(self):
        loader_hash = hashlib.sha256(self.loader_file.read_bytes()).hexdigest()
        self.write_attempt(loader_hash)
        with self.assertRaisesRegex(loader.LoaderError, "loader_candidate_already_attempted"):
            self.run_fixture(device_provider=lambda: self.fail("USB must not be accessed"))
        self.assertEqual([], self.calls)

    def test_different_loader_attempt_does_not_block_candidate(self):
        self.write_attempt("0" * 64)
        first_list = True

        def runner(argv, **kwargs):
            nonlocal first_list
            self.calls.append((argv, kwargs))
            if argv[-1] == "list":
                mode = "Maskrom" if first_list else "Loader"
                first_list = False
                return Completed(stdout=mode)
            if argv[-1] == "read-capability":
                return Completed(stdout="\n".join(loader.REQUIRED_CAPABILITIES))
            if argv[-1] == "read-flash-info":
                return Completed(stdout="Flash Size: 7456 MB")
            return Completed(stdout="OK")

        self.assertEqual("pass", self.run_fixture(command_runner=runner)["status"])

    def test_same_candidate_with_different_build_hash_is_rejected(self):
        self.write_attempt(
            "1" * 64,
            candidate_id=loader.CANDIDATE_ID,
            canonical_hash=loader.CANDIDATE_CANONICAL_SHA256,
        )
        with self.assertRaisesRegex(loader.LoaderError, "loader_candidate_already_attempted"):
            self.run_fixture(device_provider=lambda: self.fail("USB must not be accessed"))
        self.assertEqual([], self.calls)

    def test_malformed_attempt_history_fails_closed_before_usb(self):
        attempt_dir = self.history / "malformed"
        attempt_dir.mkdir()
        (attempt_dir / "ram-loader-probe.json").write_text("not-json")
        with self.assertRaisesRegex(loader.LoaderError, "attempt_history_invalid"):
            self.run_fixture(device_provider=lambda: self.fail("USB must not be accessed"))
        self.assertEqual([], self.calls)

    def test_padded_payload_allows_only_zero_padding(self):
        original = self.root / "original"
        unpacked = self.root / "unpacked"
        original.write_bytes(b"abc")
        unpacked.write_bytes(b"abc\0\0")
        loader.validate_padded_payload(unpacked, original)
        unpacked.write_bytes(b"abc\0x")
        with self.assertRaisesRegex(loader.LoaderError, "padding_not_zero"):
            loader.validate_padded_payload(unpacked, original)

    def test_cli_has_no_arbitrary_transport_command(self):
        commands = set(loader.parser()._subparsers._group_actions[0].choices)
        self.assertEqual({"prepare", "load-probe"}, commands)

    def test_candidate_constants_match_reviewed_bundle(self):
        self.assertEqual("rk322x-v1.07.238", loader.CANDIDATE_ID)
        self.assertEqual(
            "0f0dfe0653c810474d892fc6cc95788b4007d17dd60581359d15748e34d747e1",
            loader.CANDIDATE_CANONICAL_SHA256,
        )

    def test_canonical_hash_ignores_only_release_time_and_trailing_crc(self):
        first = self.root / "first.bin"
        second = self.root / "second.bin"
        first_content = bytearray(b"BOOT" + b"x" * 28)
        second_content = bytearray(first_content)
        first_content[14:21] = b"1234567"
        second_content[14:21] = b"7654321"
        first_content[-4:] = b"aaaa"
        second_content[-4:] = b"bbbb"
        first.write_bytes(first_content)
        second.write_bytes(second_content)
        self.assertEqual(
            loader.canonical_loader_sha256(first),
            loader.canonical_loader_sha256(second),
        )
        second_content[8] = ord("y")
        second.write_bytes(second_content)
        self.assertNotEqual(
            loader.canonical_loader_sha256(first),
            loader.canonical_loader_sha256(second),
        )


if __name__ == "__main__":
    unittest.main()
