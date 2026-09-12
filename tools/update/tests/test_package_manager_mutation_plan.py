"""Tests for the host-only R1 package-manager mutation plan sealer."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "r1_package_manager_mutation_plan",
    Path(__file__).parents[1] / "prepare-r1-package-manager-mutation.py",
)
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)


class Completed:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


class MutationPlanTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.aapt = self.root / "aapt"
        self.apksigner = self.root / "apksigner"
        self.aapt.write_text("tool")
        self.apksigner.write_text("tool")
        self.candidate = self.root / "candidate.apk"
        self.rollback = self.root / "rollback.apk"
        self.candidate.write_bytes(b"candidate" * 1024)
        self.rollback.write_bytes(b"rollback" * 1024)
        self.cert = "c" * 64
        self.evidence = self.root / "read-only.json"
        self.write_evidence()
        self.calls = []

    def tearDown(self):
        self.temporary.cleanup()

    def write_evidence(self, **package_changes):
        package = {
            "version_code": 102,
            "apk_sha256": planner.sha256_file(self.rollback),
        }
        package.update(package_changes)
        self.evidence.write_text(json.dumps({
            "status": "pass_with_access_limits",
            "operation": "read_only_package_manager_evidence",
            "device_id": planner.DEVICE_ID,
            "adb_serial": "SERIAL",
            "package_name": planner.PACKAGE_NAME,
            "identity": {
                "ro.build.version.incremental": planner.FIRMWARE,
                "ro.build.version.sdk": planner.SDK,
                "ro.build.fingerprint": "fixture/fingerprint",
            },
            "adb_context": {"selinux": "Enforcing"},
            "installed_package": package,
        }))

    def runner(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        path = Path(argv[-1])
        version = 118 if path == self.candidate else 102
        if argv[1:3] == ["dump", "badging"]:
            return Completed(
                f"package: name='{planner.PACKAGE_NAME}' versionCode='{version}' "
                f"versionName='fixture-{version}'\n"
            )
        if argv[1:3] == ["verify", "--print-certs"]:
            return Completed(
                "Signer #1 certificate DN: CN=Fixture\n"
                f"Signer #1 certificate SHA-256 digest: {self.cert}\n"
                "Signer #1 certificate SHA-1 digest: fixture\n"
            )
        raise AssertionError(argv)

    def prepare(self, **changes):
        values = {
            "candidate": self.candidate,
            "rollback": self.rollback,
            "evidence": self.evidence,
            "output": self.root / "plan.json",
            "confirm_device": planner.DEVICE_ID,
            "aapt": self.aapt,
            "apksigner": self.apksigner,
            "runner": self.runner,
        }
        values.update(changes)
        return planner.prepare_plan(**values)

    def test_seals_exact_upgrade_and_downgrade_contract_without_adb(self):
        result = self.prepare()
        self.assertEqual(118, result["candidate"]["version_code"])
        self.assertEqual(102, result["rollback"]["version_code"])
        self.assertIn("v102->v118->v102", result["execution_confirmation"])
        self.assertEqual("no_device_mutation", result["execution_contract"]["default_mode"])
        self.assertTrue(all(call[1]["shell"] is False for call in self.calls))
        self.assertFalse(any("adb" in str(call[0][0]) for call in self.calls))
        self.assertEqual(0o600, (self.root / "plan.json").stat().st_mode & 0o777)

    def test_wrong_device_confirmation_stops_before_tools(self):
        with self.assertRaisesRegex(planner.PlanError, "confirmation"):
            self.prepare(confirm_device="other")
        self.assertEqual([], self.calls)

    def test_requires_rollback_hash_to_equal_live_evidence(self):
        self.write_evidence(apk_sha256="a" * 64)
        with self.assertRaisesRegex(planner.PlanError, "rollback_hash_not_current"):
            self.prepare()

    def test_requires_rollback_version_to_equal_live_evidence(self):
        self.write_evidence(version_code=101)
        with self.assertRaisesRegex(planner.PlanError, "rollback_version_not_current"):
            self.prepare()

    def test_rejects_non_newer_candidate(self):
        def old_candidate(argv, **kwargs):
            result = self.runner(argv, **kwargs)
            if argv[1:3] == ["dump", "badging"] and Path(argv[-1]) == self.candidate:
                return Completed(
                    f"package: name='{planner.PACKAGE_NAME}' versionCode='102' "
                    "versionName='old'\n"
                )
            return result
        with self.assertRaisesRegex(planner.PlanError, "not_newer"):
            self.prepare(runner=old_candidate)

    def test_rejects_signer_mismatch(self):
        def mismatched(argv, **kwargs):
            result = self.runner(argv, **kwargs)
            if argv[1:3] == ["verify", "--print-certs"] and Path(argv[-1]) == self.candidate:
                return Completed(f"Signer #1 certificate SHA-256 digest: {'d' * 64}\n")
            return result
        with self.assertRaisesRegex(planner.PlanError, "signer_mismatch"):
            self.prepare(runner=mismatched)

    def test_rejects_multiple_signers(self):
        def multiple(argv, **kwargs):
            result = self.runner(argv, **kwargs)
            if argv[1:3] == ["verify", "--print-certs"] and Path(argv[-1]) == self.candidate:
                return Completed(
                    f"Signer #1 certificate SHA-256 digest: {self.cert}\n"
                    f"Signer #2 certificate SHA-256 digest: {'d' * 64}\n"
                )
            return result
        with self.assertRaisesRegex(planner.PlanError, "single_signer"):
            self.prepare(runner=multiple)

    def test_rejects_host_check_marker(self):
        self.candidate.write_bytes(b"assets/HOST_CHECK_ONLY" + b"x" * 4096)
        with self.assertRaisesRegex(planner.PlanError, "host_check"):
            self.prepare()

    def test_does_not_overwrite_plan(self):
        output = self.root / "plan.json"
        output.write_text("keep")
        with self.assertRaises(FileExistsError):
            self.prepare(output=output)
        self.assertEqual("keep", output.read_text())


if __name__ == "__main__":
    unittest.main()
