"""Tests for the guarded R1 package-manager evidence collector."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "r1_package_manager_evidence",
    Path(__file__).parents[1] / "collect-r1-package-manager-evidence.py",
)
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


class Completed:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


class PackageManagerEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.adb = self.root / "adb"
        self.adb.write_text("fixture")
        self.adb.chmod(0o755)
        self.calls = []
        self.apk_path = "/data/app/dev.sewellzhong.r1probe-1/base.apk"

    def tearDown(self):
        self.temporary.cleanup()

    def runner(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        args = argv[3:]
        if args == ["get-state"]:
            return Completed("device\n")
        if args[:2] == ["shell", "getprop"]:
            values = {
                **collector.EXPECTED_IDENTITY,
                "ro.product.model": "R1",
                "ro.build.fingerprint": "fixture/fingerprint",
            }
            return Completed(values[args[2]] + "\n")
        if args == ["shell", "id"]:
            return Completed("uid=2000(shell) gid=2000(shell) context=u:r:shell:s0\n")
        if args == ["shell", "getenforce"]:
            return Completed("Enforcing\n")
        if args == ["shell", "pm", "path", collector.PACKAGE_NAME]:
            return Completed(f"package:{self.apk_path}\n")
        if args == ["shell", "dumpsys", "package", collector.PACKAGE_NAME]:
            return Completed(
                f"Package [{collector.PACKAGE_NAME}] (fixture):\n"
                "  userId=10123 gids=[3003, 3002]\n"
                "  versionCode=118 targetSdk=22\n"
                "  codePath=/data/app/dev.sewellzhong.r1probe-1\n"
                "  splits=[base]\n"
            )
        if args == ["shell", "sha256sum", self.apk_path]:
            return Completed(f"{'a' * 64}  {self.apk_path}\n")
        if args == ["shell", "pm", "help"]:
            return Completed("usage: pm install [-r] [-d] PATH\n")
        if args == ["shell", "dmesg"]:
            return Completed("noise\ntype=1400 avc: denied { read } for fixture\n")
        if args == ["shell", "logcat", "-d", "-v", "brief"]:
            return Completed("private unrelated line\nI/auditd: avc: denied fixture\n")
        raise AssertionError(args)

    def collect(self, output=None, runner=None):
        return collector.collect_evidence(
            self.adb, "SERIAL", output or self.root / "evidence.json",
            collector.DEVICE_ID, runner=runner or self.runner,
        )

    def test_collects_only_read_only_fixed_commands(self):
        output = self.root / "evidence" / "package.json"
        result = self.collect(output)
        self.assertEqual("pass", result["status"])
        self.assertEqual(118, result["installed_package"]["version_code"])
        self.assertEqual("a" * 64, result["installed_package"]["apk_sha256"])
        self.assertEqual(1, len(result["avc"]["dmesg"]["lines"]))
        self.assertNotIn("private unrelated line", json.dumps(result))
        forbidden = {"install", "uninstall", "push", "pull", "root", "remount"}
        for call, options in self.calls:
            self.assertTrue(forbidden.isdisjoint(call))
            self.assertFalse(options["shell"])
        self.assertEqual(0o600, output.stat().st_mode & 0o777)

    def test_wrong_confirmation_never_invokes_adb(self):
        with self.assertRaisesRegex(collector.EvidenceError, "confirmation"):
            collector.collect_evidence(
                self.adb, "SERIAL", self.root / "out.json", "another-device",
                runner=self.runner,
            )
        self.assertEqual([], self.calls)

    def test_identity_mismatch_stops_before_package_commands(self):
        def mismatch(argv, **kwargs):
            result = self.runner(argv, **kwargs)
            if argv[3:] == ["shell", "getprop", "ro.hardware"]:
                return Completed("unexpected\n")
            return result

        output = self.root / "out.json"
        with self.assertRaisesRegex(collector.EvidenceError, "identity_mismatch"):
            self.collect(output, mismatch)
        self.assertEqual("stopped", json.loads(output.read_text())["status"])
        self.assertFalse(any("pm" in call[0] for call in self.calls))

    def test_non_enforcing_device_stops_before_package_commands(self):
        def permissive(argv, **kwargs):
            result = self.runner(argv, **kwargs)
            if argv[3:] == ["shell", "getenforce"]:
                return Completed("Permissive\n")
            return result

        with self.assertRaisesRegex(collector.EvidenceError, "not_enforcing"):
            self.collect(runner=permissive)
        self.assertFalse(any("pm" in call[0] for call in self.calls))

    def test_package_path_mismatch_fails_closed(self):
        def mismatch(argv, **kwargs):
            result = self.runner(argv, **kwargs)
            if argv[3:5] == ["shell", "dumpsys"]:
                return Completed(
                    f"Package [{collector.PACKAGE_NAME}] (fixture):\n"
                    "  userId=10123 gids=[3003, 3002]\n  versionCode=118 targetSdk=22\n"
                    "  codePath=/data/app/another-package-1\n"
                )
            return result

        with self.assertRaisesRegex(collector.EvidenceError, "path_dump_mismatch"):
            self.collect(runner=mismatch)

    def test_hash_access_limit_is_recorded_without_claiming_hash(self):
        def unavailable(argv, **kwargs):
            if argv[3:5] == ["shell", "sha256sum"]:
                return Completed("/system/bin/sh: sha256sum: not found\n")
            if argv[3:6] == ["shell", "busybox", "sha256sum"]:
                return Completed("/system/bin/sh: busybox: not found\n")
            return self.runner(argv, **kwargs)

        result = self.collect(runner=unavailable)
        self.assertEqual("pass_with_access_limits", result["status"])
        self.assertIsNone(result["installed_package"]["apk_sha256"])

    def test_3448_pm_closed_uses_guarded_dumpsys_and_busybox_fallback(self):
        def legacy_3448(argv, **kwargs):
            args = argv[3:]
            if args == ["shell", "pm", "path", collector.PACKAGE_NAME]:
                return Completed("", 1, "error: closed\n")
            if args == ["shell", "ls", "-l", self.apk_path]:
                return Completed("-rw-r--r-- system system 23641159 base.apk\n")
            if args == ["shell", "sha256sum", self.apk_path]:
                return Completed("/system/bin/sh: sha256sum: not found\n")
            if args == ["shell", "busybox", "sha256sum", self.apk_path]:
                return Completed(f"{'b' * 64}  {self.apk_path}\n")
            return self.runner(argv, **kwargs)

        result = self.collect(runner=legacy_3448)
        package = result["installed_package"]
        self.assertEqual("pass_with_access_limits", result["status"])
        self.assertEqual("dumpsys_base_split", package["apk_path_source"])
        self.assertEqual("device_busybox_sha256sum", package["apk_sha256_source"])
        self.assertEqual("b" * 64, package["apk_sha256"])
        self.assertEqual("pm_path", result["access_limits"][0]["item"])

    def test_pm_closed_fallback_requires_regular_base_apk(self):
        def missing_base(argv, **kwargs):
            args = argv[3:]
            if args == ["shell", "pm", "path", collector.PACKAGE_NAME]:
                return Completed("", 1, "error: closed\n")
            if args == ["shell", "ls", "-l", self.apk_path]:
                return Completed(f"{self.apk_path}: No such file or directory\n")
            return self.runner(argv, **kwargs)

        with self.assertRaisesRegex(collector.EvidenceError, "not_regular_file"):
            self.collect(runner=missing_base)

    def test_optional_logcat_timeout_is_recorded_as_access_limit(self):
        def logcat_timeout(argv, **kwargs):
            if argv[3:] == ["shell", "logcat", "-d", "-v", "brief"]:
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
            return self.runner(argv, **kwargs)

        result = self.collect(runner=logcat_timeout)
        self.assertEqual("pass_with_access_limits", result["status"])
        self.assertFalse(result["avc"]["logcat"]["available"])
        self.assertIn(
            "avc_logcat", {limit["item"] for limit in result["access_limits"]},
        )

    def test_existing_evidence_is_not_overwritten(self):
        output = self.root / "out.json"
        output.write_text("keep")
        with self.assertRaises(FileExistsError):
            self.collect(output)
        self.assertEqual("keep", output.read_text())


if __name__ == "__main__":
    unittest.main()
