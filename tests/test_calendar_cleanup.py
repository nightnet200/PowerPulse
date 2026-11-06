import json
import tempfile
import tkinter as tk
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from powerpulse import archive, gui, paths, schedule_txt, store


class CalendarCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.output = root / "regs"
        self.logs = root / "logs"
        self.logs.mkdir()
        self.manifest = root / "manifest.json"
        self.schedules_path = root / "schedules.json"
        self.schedules = store.JsonStore(self.schedules_path, "TEST")
        self.archive = store.JsonStore(root / "archive.json", "TEST")
        patches = [
            patch.object(paths, "SCHEDULES_FILE", self.schedules_path),
            patch.object(paths, "CALENDAR_LOG_DIR", self.logs),
            patch.object(schedule_txt, "OUTPUT_DIR", self.output),
            patch.object(schedule_txt, "MANIFEST_FILE", self.manifest),
            patch.object(store, "schedules", self.schedules),
            patch.object(store, "archive", self.archive),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def add_schedule(self, day, ip, repeat="none", until=None):
        return self.schedules.add({
            "ip": ip, "start_date": day, "time": "17:00", "repeat": repeat,
            "until": until, "weekdays": [], "enabled": True,
        })

    def write_log(self, day):
        (self.logs / f"up_{day}.log").write_text("registrado", encoding="utf-8")

    def test_cleanup_removes_elapsed_without_logs_and_preserves_pending(self):
        self.add_schedule("2026-11-04", "10.0.0.1")
        self.add_schedule("2026-11-05", "10.0.0.2")
        self.add_schedule("2026-11-06", "10.0.0.3")
        self.add_schedule("2026-11-07", "10.0.0.4")
        schedule_txt.generate(now=datetime(2026, 11, 4, 8))
        now = datetime(2026, 11, 6, 12)
        schedule_txt.generate(now=now, cleanup_elapsed=True)
        self.assertFalse((self.output / "2026-11-04.txt").exists())
        self.assertFalse((self.output / "2026-11-05.txt").exists())
        self.assertTrue((self.output / "2026-11-06.txt").is_file())
        self.assertTrue((self.output / "2026-11-07.txt").is_file())
        self.assertEqual(set(json.loads(self.manifest.read_text())),
                         {"2026-11-06.txt", "2026-11-07.txt"})
        self.assertEqual(archive.archive_finished(now), 2)
        self.assertEqual({s["ip"] for s in self.schedules.all()},
                         {"10.0.0.3", "10.0.0.4"})
        self.assertEqual(self.archive.all()[0]["final_status"], "Hora superada (sin confirmar)")

    def test_series_kept_until_last_occurrence_time_passes(self):
        item = self.add_schedule("2026-11-03", "10.0.0.1", "daily", "2026-11-06")
        self.assertFalse(archive.is_elapsed(item, datetime(2026, 11, 6, 17)))
        self.assertEqual(archive.archive_finished(datetime(2026, 11, 6, 17)), 0)
        self.assertEqual(archive.archive_finished(datetime(2026, 11, 6, 17, 0, 1)), 1)
        self.assertEqual(self.schedules.all(), [])
        self.assertEqual(len(self.archive.all()), 1)

    def test_shared_daily_file_and_unowned_files_are_protected(self):
        first = self.add_schedule("2026-11-07", "10.0.0.1")
        self.add_schedule("2026-11-07", "10.0.0.2")
        schedule_txt.generate(now=datetime(2026, 11, 6, 8))
        archive.delete_to_history(first["id"])
        schedule_txt.generate(now=datetime(2026, 11, 6, 8))
        self.assertEqual((self.output / "2026-11-07.txt").read_text().splitlines(),
                         [r"\\10.0.0.2"])
        self.assertEqual(self.archive.all()[0]["final_status"], "Eliminada")
        self.assertEqual(archive.as_schedules(), [])
        (self.output / "2026-11-08.txt").write_text("ajeno", encoding="ascii")
        self.add_schedule("2026-11-08", "10.0.0.3")
        with self.assertRaises(FileExistsError):
            schedule_txt.generate(now=datetime(2026, 11, 6, 8))
        self.assertEqual((self.output / "2026-11-08.txt").read_text(), "ajeno")

    def test_disabled_elapsed_archived_and_indefinite_remains(self):
        disabled = self.add_schedule("2026-11-03", "10.0.0.1")
        self.schedules.update(disabled["id"], {"enabled": False})
        self.add_schedule("2026-11-03", "10.0.0.2", "daily")
        self.assertEqual(archive.archive_finished(datetime(2026, 11, 6, 12)), 1)
        self.assertEqual(len(self.schedules.all()), 1)
        self.assertEqual(self.schedules.all()[0]["repeat"], "daily")

    def test_today_shared_file_keeps_only_pending_equipment(self):
        earlier = self.add_schedule("2026-11-06", "10.0.0.1")
        self.schedules.update(earlier["id"], {"time": "10:00"})
        elapsed_only = self.add_schedule("2026-11-06", "10.0.0.3")
        self.schedules.update(elapsed_only["id"], {"time": "10:00"})
        self.add_schedule("2026-11-06", "10.0.0.2")
        self.add_schedule("2026-11-06", "10.0.0.1")
        schedule_txt.generate(now=datetime(2026, 11, 6, 9))
        path = self.output / "2026-11-06.txt"
        self.assertEqual(path.read_text().splitlines(), [r"\\10.0.0.1", r"\\10.0.0.2", r"\\10.0.0.3"])
        now = datetime(2026, 11, 6, 11)
        schedule_txt.generate(now=now, cleanup_elapsed=True)
        self.assertEqual(path.read_text().splitlines(), [r"\\10.0.0.1", r"\\10.0.0.2"])
        self.assertEqual(archive.archive_finished(now), 2)
        schedule_txt.generate(now=datetime(2026, 11, 6, 17, 0, 1), cleanup_elapsed=True)
        self.assertFalse(path.exists())

    def test_refresh_invokes_cleanup_then_archives_with_same_time(self):
        elapsed = self.add_schedule("2026-11-06", "10.0.0.1")
        self.schedules.update(elapsed["id"], {"time": "10:00"})
        self.add_schedule("2026-11-06", "10.0.0.2")
        schedule_txt.generate(now=datetime(2026, 11, 6, 9))
        events = []
        app = SimpleNamespace(
            generate_schedule_txts=lambda parent, notify, now, cleanup_elapsed:
                (schedule_txt.generate(now=now, cleanup_elapsed=cleanup_elapsed), True)[1],
            refresh_all=lambda: events.append("refresh"),
        )
        with patch("powerpulse.gui.datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 11, 6, 11)
            gui.App.refresh_and_cleanup(app)
        self.assertEqual(events, ["refresh"])
        self.assertEqual([s["ip"] for s in self.schedules.all()], ["10.0.0.2"])
        self.assertEqual((self.output / "2026-11-06.txt").read_text().splitlines(), [r"\\10.0.0.2"])
        self.assertEqual(self.archive.all()[0]["schedule_id"], elapsed["id"])

    def test_history_shows_pending_and_manually_deleted(self):
        pending = self.add_schedule("2026-11-07", "10.0.0.1")
        deleted = self.add_schedule("2026-11-08", "10.0.0.2")
        archive.delete_to_history(deleted["id"])
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app = SimpleNamespace(refresh_all=lambda: None, refresh_and_cleanup=lambda: None)
        tab = gui.ArchiveTab(root, app)
        tab.refresh()
        self.assertEqual(len(tab.rows), 2)
        self.assertEqual({row[8] for row in tab.rows}, {"Pendiente", "Eliminada"})
        self.assertTrue(tab.tree.exists("activa:" + pending["id"]))

    def test_log_view_reads_selected_calendar_file(self):
        self.write_log("2026-11-05")
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        tab = gui.LogTab(root, SimpleNamespace(refresh_and_cleanup=lambda: None))
        tab.refresh()
        self.assertEqual(tab.files.item(tab.files.selection()[0])["values"], ["up_2026-11-05.log"])
        self.assertEqual(tab.text.get("1.0", "end-1c"), "registrado")
        tab.filter.set("ausente")
        self.assertEqual(tab.text.get("1.0", "end-1c"), "")


if __name__ == "__main__":
    unittest.main()
