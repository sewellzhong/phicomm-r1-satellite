"""Safety tests for the guarded RockUSB read-only probe."""

import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "r1_rockusb_readonly", Path(__file__).parents[1] / "r1-rockusb-readonly.py"
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class Completed:
    returncode = 0
    stdout = "read-only result\n"
    stderr = ""


class RockUsbReadonlyTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.binary = self.root / "rkdeveloptool"
        self.binary.write_text("reviewed fixture")
        self.binary.chmod(0o755)
        self.digest = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        self.approved = {self.digest: {"package": "fixture"}}
        self.calls = []

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def one_device():
        return [{"sysfs_name": "1-1", "vid_pid": "2207:320b",
                 "mode": "Loader", "usb_version": "2.01"}]

    def runner(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return Completed()

    def run_fixture_probe(self, **overrides):
        options = {
            "binary": self.binary,
            "output_dir": self.root / "evidence",
            "approved_binaries": self.approved,
            "device_provider": self.one_device,
            "command_runner": self.runner,
        }
        options.update(overrides)
        return probe.run_probe(**options)

    def test_fixed_sequence_uses_no_shell(self):
        result = self.run_fixture_probe()
        self.assertEqual("pass", result["status"])
        self.assertEqual(list(probe.COMMANDS), [call[0][-1] for call in self.calls])
        self.assertTrue(all(call[1]["shell"] is False for call in self.calls))

    def test_sudo_cannot_add_an_arbitrary_command(self):
        self.run_fixture_probe(use_sudo=True)
        self.assertTrue(all(call[0][:2] == ["sudo", "--"] for call in self.calls))
        self.assertEqual(list(probe.COMMANDS), [call[0][-1] for call in self.calls])

    def test_unapproved_binary_is_rejected_before_device_access(self):
        with self.assertRaisesRegex(probe.ProbeError, "unapproved_tool_sha256"):
            probe.run_probe(
                self.binary, self.root / "evidence", approved_binaries={},
                device_provider=lambda: self.fail("device access must not occur"),
                command_runner=self.runner,
            )
        self.assertFalse((self.root / "evidence").exists())

    def test_wrong_device_count_stops_without_transport_command(self):
        with self.assertRaisesRegex(probe.ProbeError, "found_0"):
            self.run_fixture_probe(device_provider=lambda: [])
        self.assertEqual([], self.calls)
        self.assertTrue((self.root / "evidence" / "probe.json").is_file())

    def test_nonzero_read_query_is_recorded_and_sequence_continues(self):
        class Unsupported(Completed):
            returncode = 255
            stderr = "not supported\n"

        def runner(argv, **kwargs):
            self.calls.append((argv, kwargs))
            return Unsupported() if argv[-1] == "read-chip-info" else Completed()

        result = self.run_fixture_probe(command_runner=runner)
        self.assertEqual("partial", result["status"])
        self.assertEqual(["read-chip-info"], result["unsupported_or_failed_commands"])
        self.assertEqual(len(probe.COMMANDS), len(self.calls))

    def test_timeout_stops_before_later_commands(self):
        def runner(argv, **kwargs):
            self.calls.append((argv, kwargs))
            if argv[-1] == "read-chip-info":
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
            return Completed()

        with self.assertRaisesRegex(probe.ProbeError, "command_timeout"):
            self.run_fixture_probe(command_runner=runner)
        self.assertEqual(["list", "read-chip-info"], [call[0][-1] for call in self.calls])
        evidence = (self.root / "evidence" / "probe.json").read_text()
        self.assertIn('"usb_after"', evidence)

    def test_existing_evidence_directory_is_not_overwritten(self):
        evidence = self.root / "evidence"
        evidence.mkdir()
        marker = evidence / "keep"
        marker.write_text("unchanged")
        with self.assertRaises(FileExistsError):
            self.run_fixture_probe()
        self.assertEqual("unchanged", marker.read_text())

    def test_cli_exposes_only_probe(self):
        commands = set(probe.parser()._subparsers._group_actions[0].choices)
        self.assertEqual(
            {"probe", "loader-storage", "loader-known-header", "loader-direct-header",
             "loader-image-tail", "loader-image-copy", "loader-image-alignment",
             "loader-direct-alignment", "verify-image-copy", "loader-first4m"},
            commands,
        )

    def android_inventory(self):
        path = self.root / "android-inventory.json"
        path.write_text(__import__("json").dumps({
            "device_id": "r1-sample01",
            "status": "pass_with_access_limits",
            "emmc": {"sectors": 15269888, "logical_block_bytes": 512},
            "partitions": [
                {"end_sector_exclusive": number if number < 16 else 15269888}
                for number in range(1, 17)
            ],
        }))
        return path

    def test_known_header_reads_only_fixed_range_twice(self):
        def runner(argv, **kwargs):
            self.calls.append((argv, kwargs))
            if argv[-1] == "list":
                return type("Result", (), {"returncode": 0, "stdout": "Loader\n", "stderr": ""})()
            Path(argv[-1]).write_bytes(b"h" * probe.LOADER_STORAGE_HEADER_BYTES)
            return Completed()

        result = probe.run_loader_known_header(
            self.binary, self.android_inventory(), self.root / "evidence",
            approved_binaries=self.approved, device_provider=self.one_device,
            command_runner=runner,
        )
        self.assertEqual("pass", result["status"])
        self.assertEqual(3, len(self.calls))
        reads = [call[0][-4:] for call in self.calls[1:]]
        self.assertTrue(all(read[:3] == ["read", "0", "17408"] for read in reads))

    def test_known_header_rejects_wrong_geometry_before_usb(self):
        path = self.android_inventory()
        value = __import__("json").loads(path.read_text())
        value["emmc"]["sectors"] = 1
        path.write_text(__import__("json").dumps(value))
        with self.assertRaisesRegex(probe.ProbeError, "geometry_mismatch"):
            probe.run_loader_known_header(
                self.binary, path, self.root / "evidence",
                approved_binaries=self.approved,
                device_provider=lambda: self.fail("USB must not be accessed"),
                command_runner=self.runner,
            )
        self.assertEqual([], self.calls)

    def test_direct_and_standard_binary_allowlists_are_disjoint(self):
        self.assertTrue(probe.DIRECT_READ_BINARIES)
        self.assertTrue(set(probe.DIRECT_READ_BINARIES).isdisjoint(probe.APPROVED_BINARIES))

    def test_alignment_reads_only_two_fixed_ranges_twice(self):
        def runner(argv, **kwargs):
            self.calls.append((argv, kwargs))
            if argv[-1] == "list":
                return type("Result", (), {"returncode": 0, "stdout": "Loader\n", "stderr": ""})()
            Path(argv[-1]).write_bytes(b"a" * int(argv[-2]))
            return Completed()

        result = probe.run_loader_alignment(
            self.binary, self.android_inventory(), self.root / "evidence",
            approved_binaries=self.approved, device_provider=self.one_device,
            command_runner=runner,
        )
        self.assertEqual("pass", result["status"])
        reads = [call[0][-4:-1] for call in self.calls[1:]]
        self.assertEqual(
            [["read", "8192", "4096"], ["read", "8192", "4096"],
             ["read", "16384", "4096"], ["read", "16384", "4096"]],
            reads,
        )

    def test_image_copy_uses_contiguous_fixed_chunks_and_rereads(self):
        def runner(argv, **kwargs):
            self.calls.append((argv, kwargs))
            if argv[-1] == "list":
                return type("Result", (), {"returncode": 0, "stdout": "Loader\n", "stderr": ""})()
            Path(argv[-1]).write_bytes(bytes([int(argv[-3]) // 2]) * int(argv[-2]))
            return Completed()

        result = probe.run_loader_image_copy(
            self.binary, self.android_inventory(), self.root / "evidence",
            approved_binaries=self.approved, device_provider=self.one_device,
            command_runner=runner, image_offset_sectors=15269884, chunk_bytes=1024,
        )
        self.assertEqual("pass", result["status"])
        self.assertEqual([0, 2], [chunk["start_sector"] for chunk in result["chunks"]])
        self.assertEqual([1024, 1024], [chunk["bytes"] for chunk in result["chunks"]])
        self.assertEqual(5, len(self.calls))
        self.assertTrue(all(
            (self.root / "evidence" / copy["file"]).stat().st_mode & 0o777 == 0o600
            for chunk in result["chunks"] for copy in chunk["copies"]
        ))

    def test_secure_local_file_rejects_symlink(self):
        target = self.root / "target"
        target.write_text("data")
        link = self.root / "link"
        link.symlink_to(target)
        with self.assertRaisesRegex(probe.ProbeError, "not_regular"):
            probe.secure_local_file(link, use_sudo=False)

    def test_image_copy_accepts_relative_output_path(self):
        relative = Path(__import__("os").path.relpath(self.root / "relative-evidence", Path.cwd()))

        def runner(argv, **kwargs):
            if argv[-1] == "list":
                return type("Result", (), {"returncode": 0, "stdout": "Loader\n", "stderr": ""})()
            Path(argv[-1]).write_bytes(b"r" * int(argv[-2]))
            return Completed()

        result = probe.run_loader_image_copy(
            self.binary, self.android_inventory(), relative,
            approved_binaries=self.approved, device_provider=self.one_device,
            command_runner=runner, image_offset_sectors=15269886, chunk_bytes=1024,
        )
        self.assertEqual("pass", result["status"])

    def test_offline_verifier_rehashes_both_copies(self):
        evidence_dir = self.root / "copy-evidence"
        payload = b"same" * 128
        for label in ("a", "b"):
            directory = evidence_dir / f"copy-{label}"
            directory.mkdir(parents=True)
            (directory / "chunk-0000.bin").write_bytes(payload)
            (directory / "chunk-0000.bin").chmod(0o600)
        digest = hashlib.sha256(payload).hexdigest()
        evidence = evidence_dir / "loader-image-copy.json"
        evidence.write_text(__import__("json").dumps({
            "device_id": "r1-sample01",
            "operation": "loader-image-copy",
            "status": "pass",
            "address_space": {"image_bytes": 512},
            "chunks": [{
                "index": 0, "start_sector": 0, "bytes": 512,
                "copies": [
                    {"storage_id": "local-copy-a", "file": "copy-a/chunk-0000.bin", "size": 512, "sha256": digest},
                    {"storage_id": "local-copy-b", "file": "copy-b/chunk-0000.bin", "size": 512, "sha256": digest},
                ],
            }],
        }))
        output = evidence_dir / "verification.json"
        result = probe.verify_loader_image_copy(evidence, output)
        self.assertEqual("pass", result["status"])
        self.assertEqual(digest, result["overall_sha256"]["local-copy-a"])

    def ram_probe(self):
        path = self.root / "ram-probe.json"
        path.write_text(__import__("json").dumps({
            "device_id": "r1-sample01",
            "candidate_id": probe.RAM_LOADER_CANDIDATE_ID,
            "status": "pass",
            "loader_sha256": "per-build-loader-hash",
            "loader_canonical_sha256": probe.RAM_LOADER_CANONICAL_SHA256,
            "required_capabilities": {
                "expected": ["Direct LBA:\tenabled", "First 4m Access:\tenabled", "Read LBA:\tenabled"],
                "missing": [],
            },
        }))
        return path

    def test_first4m_is_fixed_reread_with_parameter_crosscheck(self):
        def runner(argv, **kwargs):
            self.calls.append((argv, kwargs))
            if argv[-1] == "list":
                return type("Result", (), {"returncode": 0, "stdout": "Loader\n", "stderr": ""})()
            target = Path(argv[-1])
            length = int(argv[-2])
            if argv[-3] == "8192":
                target.write_bytes(b"p" * length)
            else:
                target.write_bytes(b"f" * length)
            return Completed()

        original_size = probe.FIRST4M_BYTES
        original_parameter = probe.KNOWN_PARAMETER_SHA256
        probe.FIRST4M_BYTES = 1024
        probe.KNOWN_PARAMETER_SHA256 = hashlib.sha256(
            b"p" * probe.LOADER_STORAGE_HEADER_BYTES
        ).hexdigest()
        try:
            result = probe.run_loader_first4m(
                self.binary, self.android_inventory(), self.ram_probe(),
                self.root / "evidence", approved_binaries=self.approved,
                device_provider=self.one_device, command_runner=runner,
            )
        finally:
            probe.FIRST4M_BYTES = original_size
            probe.KNOWN_PARAMETER_SHA256 = original_parameter
        self.assertEqual("pass", result["status"])
        reads = [call[0][-4:-1] for call in self.calls[1:]]
        self.assertEqual(
            [["read", "0", "1024"], ["read", "0", "1024"],
             ["read", "8192", "17408"], ["read", "8192", "17408"]],
            reads,
        )

    def test_first4m_rejects_incomplete_capability_before_usb(self):
        path = self.ram_probe()
        value = __import__("json").loads(path.read_text())
        value["required_capabilities"]["missing"] = ["First 4m Access"]
        path.write_text(__import__("json").dumps(value))
        with self.assertRaisesRegex(probe.ProbeError, "capability_missing"):
            probe.run_loader_first4m(
                self.binary, self.android_inventory(), path, self.root / "evidence",
                approved_binaries=self.approved,
                device_provider=lambda: self.fail("USB must not be accessed"),
                command_runner=self.runner,
            )

    def test_loader_storage_fixed_sequence_and_matching_headers(self):
        first = self.root / "evidence" / "first-34-sectors-a.bin"
        second = self.root / "evidence" / "first-34-sectors-b.bin"

        def runner(argv, **kwargs):
            self.calls.append((argv, kwargs))
            if argv[-1] == "list":
                return type("Result", (), {"returncode": 0, "stdout": "Loader\n", "stderr": ""})()
            if argv[-1] == "read-flash-info":
                return type("Result", (), {"returncode": 0, "stdout": "Flash Size: 7456 MB\n", "stderr": ""})()
            if "read" in argv:
                Path(argv[-1]).write_bytes(b"x" * probe.LOADER_STORAGE_HEADER_BYTES)
            return Completed()

        result = probe.run_loader_storage(
            self.binary, self.root / "evidence",
            approved_binaries=self.approved, device_provider=self.one_device,
            command_runner=runner,
        )
        self.assertEqual("pass", result["status"])
        self.assertEqual(first.read_bytes(), second.read_bytes())
        commands = [call[0][-1] if "read" not in call[0] else "read" for call in self.calls]
        self.assertEqual(["list", "read-flash-info", "read", "read", "list-partitions"], commands)

    def test_loader_storage_flash_timeout_stops_before_reads(self):
        def runner(argv, **kwargs):
            self.calls.append((argv, kwargs))
            if argv[-1] == "list":
                return type("Result", (), {"returncode": 0, "stdout": "Loader\n", "stderr": ""})()
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

        with self.assertRaisesRegex(probe.ProbeError, "read-flash-info"):
            probe.run_loader_storage(
                self.binary, self.root / "evidence",
                approved_binaries=self.approved, device_provider=self.one_device,
                command_runner=runner,
            )
        self.assertEqual(2, len(self.calls))

    def test_loader_storage_requires_2_01_loader(self):
        with self.assertRaisesRegex(probe.ProbeError, "expected_loader_2.01"):
            probe.run_loader_storage(
                self.binary, self.root / "evidence",
                approved_binaries=self.approved,
                device_provider=lambda: [{"mode": "Maskrom", "usb_version": "2.00"}],
                command_runner=self.runner,
            )
        self.assertEqual([], self.calls)


if __name__ == "__main__":
    unittest.main()
