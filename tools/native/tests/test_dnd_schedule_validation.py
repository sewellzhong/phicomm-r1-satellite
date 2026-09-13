import importlib.util
from datetime import datetime
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dnd_schedule", ROOT / "validate-dnd-schedule.py")
validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validation)


class DndScheduleValidationTests(unittest.TestCase):
    def test_afternoon_window_crosses_midnight_and_contains_now(self):
        with patch.object(validation, "datetime") as clock:
            clock.now.return_value = datetime(2026, 9, 14, 18, 30)
            start, end = validation.active_cross_midnight("Asia/Hong_Kong")
        self.assertEqual((18 * 60 + 29, 5), (start, end))
        self.assertGreater(start, end)

    def test_morning_window_crosses_midnight_and_contains_now(self):
        with patch.object(validation, "datetime") as clock:
            clock.now.return_value = datetime(2026, 9, 14, 6, 30)
            start, end = validation.active_cross_midnight("Asia/Hong_Kong")
        self.assertEqual((23 * 60 + 55, 6 * 60 + 35), (start, end))
        self.assertGreater(start, end)


if __name__ == "__main__":
    unittest.main()
