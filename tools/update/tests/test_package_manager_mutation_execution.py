"""Tests for the bounded R1 package-manager mutation executor."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "r1_package_manager_mutation_execution",
    Path(__file__).parents[1] / "execute-r1-package-manager-mutation.py",
)
executor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(executor)
planner = executor.planner


class Completed:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


class MutationExecutionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.adb = self.root / "adb"
        self.aapt = self.root / "aapt"
        self.apksigner = self.root / "apksigner"
        for tool in (self.adb, self.aapt, self.apksigner):
            tool.write_text("tool")
        self.candidate = self.root / "candidate.apk"
        self.rollback = self.root / "rollback.apk"
        self.candidate.write_bytes(b"candidate" * 1024)
        self.rollback.write_bytes(b"rollback" * 1024)
        self.candidate_hash = planner.sha256_file(self.candidate)
        self.rollback_hash = planner.sha256_file(self.rollback)
        self.cert = "c" * 64
        self.serial = "SERIAL"
        self.state_version = 102
        self.state_hash = self.rollback_hash
        self.calls = []
        self.fail_upgrade = False
        self.fail_upgrade_after_install = False
        self.fail_first_downgrade = False
        self.downgrade_calls = 0
        self.evidence = self.root / "evidence.json"
        self.evidence.write_text(json.dumps({
            "status": "pass",
            "operation": "read_only_package_manager_evidence",
            "device_id": planner.DEVICE_ID,
            "adb_serial": self.serial,
            "package_name": planner.PACKAGE_NAME,
            "identity": {
                **executor.collector.EXPECTED_IDENTITY,
                "ro.build.fingerprint": "fixture/fingerprint",
            },
            "adb_context": {"selinux": "Enforcing"},
            "installed_package": {
                "version_code": 102, "apk_sha256": self.rollback_hash,
            },
        }))
        self.plan_path = self.root / "plan.json"
        self.plan = planner.prepare_plan(
            self.candidate, self.rollback, self.evidence, self.plan_path,
            planner.DEVICE_ID, self.aapt, self.apksigner, runner=self.runner,
        )
        self.calls.clear()

    def tearDown(self):
        self.temporary.cleanup()

    def runner(self, argv, **kwargs):
        self.calls.append((list(map(str, argv)), kwargs))
        tool = Path(argv[0])
        if tool == self.aapt:
            path = Path(argv[-1])
            version = 118 if path == self.candidate else 102
            return Completed(
                f"package: name='{planner.PACKAGE_NAME}' versionCode='{version}' "
                f"versionName='fixture-{version}'\n"
            )
        if tool == self.apksigner:
            return Completed(
                f"Signer #1 certificate SHA-256 digest: {self.cert}\n"
            )
        if tool != self.adb:
            raise AssertionError(argv)
        args = list(map(str, argv[3:]))
        if args == ["get-state"]:
            return Completed("device\n")
        if args[:2] == ["shell", "getprop"]:
            return Completed(executor.collector.EXPECTED_IDENTITY[args[2]] + "\n")
        if args == ["shell", "id"]:
            return Completed("uid=2000(shell) gid=2000(shell) context=u:r:shell:s0\n")
        if args == ["shell", "getenforce"]:
            return Completed("Enforcing\n")
        if args == ["shell", "dumpsys", "package", planner.PACKAGE_NAME]:
            return Completed(
                f"Package [{planner.PACKAGE_NAME}] (fixture):\n"
                "  userId=10010 gids=[3003]\n"
                f"  versionCode={self.state_version} targetSdk=22\n"
                f"  codePath=/data/app/{planner.PACKAGE_NAME}-1\n"
                "  splits=[base]\n"
            )
        if args[:3] == ["shell", "busybox", "sha256sum"]:
            path = args[3]
            if path.endswith("candidate.apk"):
                digest = self.candidate_hash
            elif path.endswith("rollback.apk"):
                digest = self.rollback_hash
            else:
                digest = self.state_hash
            return Completed(f"{digest}  {path}\n")
        if args[0] == "push":
            return Completed("1 file pushed\n")
        if "com.android.commands.pm.Pm" in args:
            is_downgrade = "-d" in args
            if is_downgrade:
                self.downgrade_calls += 1
                if self.fail_first_downgrade and self.downgrade_calls == 1:
                    return Completed("Failure [fixture]\n", 1)
                self.state_version = 102
                self.state_hash = self.rollback_hash
                return Completed("Success\n")
            if self.fail_upgrade:
                if self.fail_upgrade_after_install:
                    self.state_version = 118
                    self.state_hash = self.candidate_hash
                return Completed("Failure [fixture]\n", 1)
            self.state_version = 118
            self.state_hash = self.candidate_hash
            return Completed("Success\n")
        if args == ["shell", "dmesg"]:
            return Completed("noise\ntype=1400 avc: denied fixture\n")
        if args[:3] == ["shell", "rm", "-f"]:
            return Completed()
        if args[:4] == ["shell", "am", "startservice", "-n"]:
            return Completed("Starting service: fixture\n")
        raise AssertionError(args)

    def execute(self, **changes):
        bound_output = self.plan_path.parent / (
            f"mutation-execution-{self.plan['plan_id'][:16]}.json"
        )
        values = {
            "plan_path": self.plan_path,
            "confirmation": self.plan["execution_confirmation"],
            "output": bound_output,
            "serial": self.serial,
            "execute_enabled": True,
            "adb": self.adb,
            "aapt": self.aapt,
            "apksigner": self.apksigner,
            "runner": self.runner,
            "sleeper": lambda _seconds: None,
        }
        values.update(changes)
        return executor.execute(**values)

    def adb_calls(self):
        return [call for call, _ in self.calls if Path(call[0]) == self.adb]

    def test_success_observes_upgrade_then_explicit_downgrade_and_restores(self):
        result = self.execute()
        self.assertEqual("pass_backend_evidence_only", result["status"])
        self.assertEqual(118, result["upgraded"]["version_code"])
        self.assertEqual(102, result["restored"]["version_code"])
        self.assertTrue(result["rollback_restored"])
        installs = [call for call in self.adb_calls() if "com.android.commands.pm.Pm" in call]
        self.assertEqual(2, len(installs))
        self.assertNotIn("-d", installs[0])
        self.assertIn("-d", installs[1])
        self.assertEqual(0o600, self.execute_output().stat().st_mode & 0o777)

    def test_missing_execute_flag_stops_before_any_tool(self):
        with self.assertRaisesRegex(executor.ExecutionError, "execute_flag"):
            self.execute(execute_enabled=False)
        self.assertEqual([], self.calls)

    def test_wrong_confirmation_stops_before_any_tool(self):
        with self.assertRaisesRegex(executor.ExecutionError, "confirmation_required"):
            self.execute(confirmation="wrong")
        self.assertEqual([], self.calls)

    def test_changed_candidate_stops_before_adb(self):
        self.candidate.write_bytes(b"changed" * 1024)
        with self.assertRaisesRegex(executor.ExecutionError, "candidate_hash_changed"):
            self.execute()
        self.assertEqual([], self.adb_calls())

    def test_live_identity_mismatch_stops_before_push(self):
        original = self.runner

        def mismatch(argv, **kwargs):
            if list(map(str, argv[3:])) == ["shell", "getprop", "ro.hardware"]:
                self.calls.append((list(map(str, argv)), kwargs))
                return Completed("unexpected\n")
            return original(argv, **kwargs)

        with self.assertRaisesRegex(executor.ExecutionError, "identity_mismatch"):
            self.execute(runner=mismatch)
        self.assertFalse(any(call[3] == "push" for call in self.adb_calls()))
        self.assertFalse(any(call[3:6] == ["shell", "rm", "-f"] for call in self.adb_calls()))

    def test_upgrade_failure_attempts_bounded_rollback_and_records_failure(self):
        self.fail_upgrade = True
        with self.assertRaisesRegex(executor.ExecutionError, "upgrade_package_manager_failed"):
            self.execute()
        report = json.loads(self.execute_output().read_text())
        self.assertEqual("failed", report["status"])
        self.assertFalse(report["emergency_rollback_attempted"])
        self.assertTrue(report["rollback_restored"])
        self.assertEqual(0, self.downgrade_calls)

    def execute_output(self):
        return self.plan_path.parent / (
            f"mutation-execution-{self.plan['plan_id'][:16]}.json"
        )

    def test_upgrade_failure_after_state_change_attempts_one_rollback(self):
        self.fail_upgrade = True
        self.fail_upgrade_after_install = True
        with self.assertRaisesRegex(executor.ExecutionError, "upgrade_package_manager_failed"):
            self.execute()
        report = json.loads(self.execute_output().read_text())
        self.assertTrue(report["emergency_rollback_attempted"])
        self.assertTrue(report["rollback_restored"])
        self.assertEqual(1, self.downgrade_calls)

    def test_failed_explicit_downgrade_gets_one_emergency_retry(self):
        self.fail_first_downgrade = True
        with self.assertRaisesRegex(executor.ExecutionError, "downgrade_package_manager_failed"):
            self.execute()
        report = json.loads(self.execute_output().read_text())
        self.assertTrue(report["rollback_restored"])
        self.assertEqual(2, self.downgrade_calls)

    def test_existing_output_stops_before_any_tool(self):
        output = self.execute_output()
        output.write_text("keep")
        with self.assertRaises(FileExistsError):
            self.execute(output=output)
        self.assertEqual("keep", output.read_text())
        self.assertEqual([], self.calls)

    def test_output_name_is_bound_to_plan_before_any_tool(self):
        with self.assertRaisesRegex(executor.ExecutionError, "output_path_not_plan_bound"):
            self.execute(output=self.root / "another.json")
        self.assertEqual([], self.calls)


if __name__ == "__main__":
    unittest.main()
