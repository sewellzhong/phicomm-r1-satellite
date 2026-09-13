import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class DevicePolicyTest(unittest.TestCase):
    def test_agent_is_narrow_and_authenticated(self):
        policy = (ROOT / "device/sepolicy/r1_system_control.te").read_text()
        init = (ROOT / "device/init.r1_system_control.rc").read_text()
        self.assertIn("self:capability sys_boot", policy)
        self.assertIn("sysfs:file { open read write getattr }", policy)
        self.assertIn("untrusted_app r1_system_control:unix_stream_socket connectto", policy)
        for forbidden in ("block_device", "tcp_socket", "udp_socket", "system_data_file",
                          "shell_exec", "mount", "execute_no_trans"):
            self.assertNotIn(forbidden, policy)
        self.assertIn("socket r1_system_control seqpacket 0600 10010 10010", init)
        self.assertIn("service r1_sysctl /sbin/r1-system-control-agent", init)
        self.assertNotIn("service r1_system_control ", init)
        self.assertIn("seclabel u:r:r1_system_control:s0", init)


if __name__ == "__main__":
    unittest.main()
