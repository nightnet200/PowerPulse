import tempfile
import unittest
from pathlib import Path

from powerpulse import paths


class CalendarPathsTests(unittest.TestCase):
    def test_ensure_calendar_directories_creates_all_required_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "Calendario"

            paths.ensure_calendar_directories(root)

            self.assertEqual(
                {path.name for path in root.iterdir()},
                {"logs", "regs", "logs7", "regs7"},
            )
            self.assertTrue(all(path.is_dir() for path in root.iterdir()))

    def test_missing_calendar_scripts_reports_names_without_copying(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            self.assertEqual(paths.missing_calendar_scripts(root),
                             ["downcal7.bat", "downcal17.bat"])
            (root / "downcal7.bat").write_text("script", encoding="utf-8")
            self.assertEqual(paths.missing_calendar_scripts(root), ["downcal17.bat"])


if __name__ == "__main__":
    unittest.main()
