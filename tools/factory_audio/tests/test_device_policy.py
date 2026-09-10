from pathlib import Path
import importlib.util
import json
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
DEVICE = ROOT / "android/factory-audio-agent/device"
SPEC = importlib.util.spec_from_file_location(
    "overlay_renderer", ROOT / "tools/factory_audio/render-device-overlay.py"
)
renderer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renderer)


class DevicePolicyTemplateTest(unittest.TestCase):
    def test_init_drops_root_and_keeps_unproven_shape_as_token(self):
        init = (DEVICE / "init.r1_factory_audio.rc").read_text()
        self.assertIn("--expected-uid 10010", init)
        self.assertIn("--drop-uid 1041 --drop-gid 1041", init)
        self.assertIn("@PROVEN_OUTPUT_CHANNELS@", init)
        self.assertIn("@PROVEN_OUTPUT_CHANNEL@", init)
        self.assertIn("user root", init)
        self.assertIn("disabled", init)

    def test_agent_domain_has_no_network_block_or_permissive_grant(self):
        policy = (DEVICE / "sepolicy/r1_factory_audio.te").read_text()
        self.assertNotIn("permissive r1_factory_audio", policy)
        self.assertNotIn("net_domain(r1_factory_audio)", policy)
        self.assertNotIn("block_device", policy)
        self.assertNotIn("untrusted_app audio_device", policy)
        self.assertIn("SO_PEERCRED", policy)
        self.assertIn("audio_device:chr_file", policy)
        self.assertIn("type_transition r1_factory_audio socket_device:sock_file", policy)

    def test_only_agent_and_socket_receive_new_file_labels(self):
        contexts = (DEVICE / "sepolicy/file_contexts").read_text().splitlines()
        entries = [line for line in contexts if line.strip() and not line.startswith("#")]
        self.assertEqual(2, len(entries))
        self.assertTrue(any("r1_factory_audio_exec" in line for line in entries))
        self.assertTrue(any("r1_factory_audio_socket" in line for line in entries))

    def test_overlay_renderer_refuses_pending_recovery_gate_first(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gate = root / "gate.json"
            gate.write_text(json.dumps({"status": "pending", "device": {"id": "r1-sample01"}}))
            args = SimpleNamespace(
                gate_report=gate, boot_baseline_report=root / "missing-boot-baseline.json",
                preflight=root / "missing-preflight.json",
                abi_report=root / "missing-abi.json", agent=root / "missing-agent",
                vendor_library="/system/lib/libuni4michal.so", output_channels=1,
                output_channel=0, output_dir=root / "output",
            )
            with self.assertRaisesRegex(RuntimeError, "r0_gate_not_passed"):
                renderer.render(args)

    def test_overlay_renderer_refuses_unverified_boot_baseline_before_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gate = root / "gate.json"
            boot = root / "boot.json"
            gate.write_text(json.dumps({
                "status": "pass", "device": {
                    "id": "r1-sample01", "fingerprint": "synthetic/3448"
                }
            }))
            boot.write_text(json.dumps({
                "status": "pending", "device": {
                    "id": "r1-sample01", "fingerprint": "synthetic/3448"
                }
            }))
            args = SimpleNamespace(
                gate_report=gate, boot_baseline_report=boot,
                preflight=root / "missing-preflight.json",
                abi_report=root / "missing-abi.json", agent=root / "missing-agent",
                vendor_library="/system/lib/libuni4michal.so", output_channels=1,
                output_channel=0, output_dir=root / "output",
            )
            with self.assertRaisesRegex(RuntimeError, "boot_baseline_not_passed"):
                renderer.render(args)

    def test_overlay_manifest_binds_verified_boot_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fingerprint = "Android/rk322x_echo/rk322x_echo:5.1.1/LMY49F/3448:user/release-keys"
            reference = json.loads(renderer.BOOT_REFERENCE.read_text())
            values = {
                "gate.json": {"status": "pass", "device": {
                    "id": "r1-sample01", "fingerprint": fingerprint
                }},
                "boot.json": {"status": "pass", "device": {
                    "id": "r1-sample01", "fingerprint": fingerprint
                }, "reference_sha256": renderer.digest(renderer.BOOT_REFERENCE),
                    "baseline_manifest_sha256": reference["baseline_manifest_sha256"]},
                "preflight.json": {"status": "pass", "device": "r1-sample01",
                    "identity": {"ro.build.fingerprint": fingerprint},
                    "satellite": {"uid": 10010}},
                "abi.json": {"status": "pass", "library_name": "libuni4michal.so",
                    "library_sha256": "a" * 64},
            }
            for name, value in values.items():
                (root / name).write_text(json.dumps(value))
            agent = root / "agent"
            agent.write_bytes(b"synthetic-arm-agent")
            args = SimpleNamespace(
                gate_report=root / "gate.json", boot_baseline_report=root / "boot.json",
                preflight=root / "preflight.json", abi_report=root / "abi.json", agent=agent,
                vendor_library="/system/lib/libuni4michal.so", output_channels=2,
                output_channel=1, output_dir=root / "output",
            )
            header = SimpleNamespace(stdout=(
                "Class:                             ELF32\n"
                "Machine:                           ARM\n"
            ))
            with mock.patch.object(renderer.subprocess, "run", return_value=header):
                result = renderer.render(args)
            self.assertEqual(reference["baseline_manifest_sha256"],
                             result["boot_baseline_manifest_sha256"])
            self.assertEqual(renderer.digest(renderer.BOOT_REFERENCE),
                             result["boot_baseline_reference_sha256"])
            written = json.loads((root / "output/manifest.json").read_text())
            self.assertEqual(result, written)


if __name__ == "__main__":
    unittest.main()
