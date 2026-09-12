import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("native_admin", ROOT / "manage-r1-native.py")
admin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin)


class TimerAdminTests(unittest.TestCase):
    def test_shell_only_timer_actions_are_exposed(self):
        self.assertIn("timer-status", admin.ADMIN_ACTIONS)
        self.assertIn("timer-stop", admin.ADMIN_ACTIONS)


if __name__ == "__main__":
    unittest.main()
