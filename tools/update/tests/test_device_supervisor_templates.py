from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
DEVICE = ROOT / "android/update-agent/device"
JAVA = ROOT / (
    "android/update-agent/java/dev/sewellzhong/r1update/PackageIdentityHelper.java"
)


class DeviceSupervisorTemplateTest(unittest.TestCase):
    def test_init_is_device_uid_bound_and_uses_inherited_seqpacket(self):
        value = (DEVICE / "init.r1_update_supervisor.rc").read_text()
        self.assertIn("service r1_update /sbin/r1-update-supervisor", value)
        self.assertNotIn("service r1_update_supervisor ", value)
        self.assertIn("mkdir /data/misc/r1_update 0700 root root", value)
        self.assertIn("seclabel u:r:r1_update_supervisor:s0", value)
        self.assertIn("socket r1_update_supervisor seqpacket 0600 10010 10010", value)
        self.assertIn("disabled", value)
        self.assertNotIn("permissive", value)

    def test_policy_has_no_expansive_device_or_network_permission(self):
        value = (DEVICE / "sepolicy/r1_update_supervisor.te").read_text()
        self.assertIn("type r1_update_supervisor;", value)
        self.assertIn("unix_stream_socket", value)
        self.assertNotIn("unix_seqpacket_socket", value)
        self.assertNotIn("r1_factory_audio", value)
        for forbidden in (
            "block_device", "tcp_socket", "udp_socket", "net_domain(",
            "mount ", "ptrace", "permissive r1_update_supervisor",
        ):
            self.assertNotIn(forbidden, value)

    def test_helper_uses_binder_and_local_parser_not_candidate_process(self):
        value = JAVA.read_text()
        self.assertIn('getService.invoke(null, "package")', value)
        self.assertIn('Class.forName("android.content.pm.PackageParser")', value)
        self.assertIn("signatures.length != 1", value)
        self.assertNotIn("ActivityThread", value)
        self.assertNotIn("Runtime.getRuntime", value)

    def test_supervisor_startup_failures_are_observable_in_android_log(self):
        value = (ROOT / "android/update-agent/src/supervisor_main.cpp").read_text()
        cmake = (ROOT / "android/update-agent/CMakeLists.txt").read_text()
        self.assertIn("__android_log_write", value)
        self.assertIn('"R1UpdateSupervisor"', value)
        self.assertIn("r1-update-policy log", cmake)
        self.assertIn("listen(fd, 4)", value)


if __name__ == "__main__":
    unittest.main()
