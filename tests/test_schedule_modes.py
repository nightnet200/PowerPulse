import json
import tempfile
import tkinter as tk
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from powerpulse import archive, gui, paths, reports, schedule_targets, schedule_txt, store


class ScheduleModesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.assignments = root / "assignments.json"
        self.output = root / "regs"
        self.manifest = root / "manifest.json"
        self.schedules = store.JsonStore(root / "schedules.json", "TEST")
        self.archive = store.JsonStore(root / "historico.json", "TEST")
        for target, attribute, value in (
            (paths, "ASSIGNMENTS_FILE", self.assignments),
            (paths, "SCHEDULES_FILE", self.schedules.path),
            (schedule_txt, "OUTPUT_DIR", self.output),
            (schedule_txt, "MANIFEST_FILE", self.manifest),
            (store, "schedules", self.schedules),
            (store, "archive", self.archive),
        ):
            mock = patch.object(target, attribute, value)
            mock.start()
            self.addCleanup(mock.stop)
        self.write_assignments("10.0.0.1", "10.0.0.2")
        self.day = date.today() + timedelta(days=1)

    def write_assignments(self, *ips):
        self.assignments.write_text(json.dumps([{"ip": ip} for ip in ips]), encoding="utf-8")

    def add_schedule(self, **fields):
        return self.schedules.add({
            "start_date": self.day.isoformat(), "time": "17:00", "repeat": "none",
            "until": None, "weekdays": [], "enabled": True, **fields,
        })

    def test_dynamic_targets_update_and_exclusions_survive_removal(self):
        self.add_schedule(target_mode="all", ips=[], excluded_ips=["10.0.0.2"])
        schedule_txt.generate(self.day)
        path = self.output / f"{self.day.isoformat()}.txt"
        self.assertEqual(path.read_text().splitlines(), [r"\\10.0.0.1"])
        before = gui.App._assignments_signature()
        self.write_assignments("10.0.0.1", "10.0.0.2", "10.0.0.3")
        self.assertNotEqual(before, gui.App._assignments_signature())
        schedule_txt.generate(self.day)
        self.assertEqual(path.read_text().splitlines(), [r"\\10.0.0.1", r"\\10.0.0.3"])
        with patch.object(store.history, "status_map", return_value={}):
            _, _, rows = reports.build_report("schedules", "day", self.day)
        self.assertEqual({row[2] for row in rows}, {"10.0.0.1", "10.0.0.3"})
        self.write_assignments("10.0.0.1")
        schedule_txt.generate(self.day)
        self.write_assignments("10.0.0.1", "10.0.0.2")
        schedule_txt.generate(self.day)
        self.assertEqual(path.read_text().splitlines(), [r"\\10.0.0.1"])

    def test_invalid_assignments_leave_existing_files_untouched(self):
        self.add_schedule(target_mode="all", ips=[], excluded_ips=[])
        schedule_txt.generate(self.day)
        path = self.output / f"{self.day.isoformat()}.txt"
        before, manifest = path.read_bytes(), self.manifest.read_bytes()
        self.assignments.write_text("{", encoding="utf-8")
        with self.assertRaises(ValueError):
            schedule_txt.generate(self.day)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.manifest.read_bytes(), manifest)

    def test_auto_refresh_regenerates_after_assignments_change(self):
        self.add_schedule(target_mode="all", ips=[], excluded_ips=[])
        original_signature = gui.App._assignments_signature()
        self.write_assignments("10.0.0.1", "10.0.0.3")
        calls = []
        app = SimpleNamespace(
            _txt_generation_date=date.today(),
            _txt_assignments_signature=original_signature,
            _assignments_signature=gui.App._assignments_signature,
            refresh_all=lambda: calls.append("refresh"),
            generate_schedule_txts=lambda parent, notify: calls.append("generate"),
            after=lambda delay, callback: calls.append(("after", delay)),
            auto_refresh=lambda: None,
        )
        gui.App.auto_refresh(app)
        self.assertEqual(calls, ["refresh", "generate", ("after", 15000)])

    def test_archive_captures_current_targets(self):
        item = self.add_schedule(target_mode="all", ips=[], excluded_ips=["10.0.0.2"])
        archive.delete_to_history(item["id"])
        saved = self.archive.all()[0]
        self.write_assignments("10.0.0.3")
        self.assertEqual(schedule_targets.included_ips(saved), ["10.0.0.1"])

    def test_legacy_selection_and_single_stay_unchanged(self):
        legacy = {"ip": "10.0.0.9"}
        selected = {"ips": ["10.0.0.1", "10.0.0.2"], "excluded_ips": ["10.0.0.2"]}
        self.write_assignments("10.0.0.3")
        self.assertEqual(schedule_targets.included_ips(legacy), ["10.0.0.9"])
        self.assertEqual(schedule_targets.included_ips(selected), ["10.0.0.1"])

    def test_dialog_modes_and_legacy_edit(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        patcher = patch.object(gui._Dialog, "finish_layout")
        patcher.start()
        self.addCleanup(patcher.stop)
        dialog = gui.ScheduleDialog(root, None, self.day)
        self.addCleanup(dialog.destroy)
        self.assertEqual(dialog.mode.get(), "individual")
        with self.assertRaises(ValueError):
            dialog.collect()
        dialog.individual_picker.select(["10.0.0.1"])
        result = dialog.collect()
        self.assertEqual((result["target_mode"], result["ips"], result["excluded_ips"]),
                         ("individual", ["10.0.0.1"], []))
        dialog.mode.set("all")
        dialog._show_mode()
        dialog.excluded_ips = {"10.0.0.2"}
        result = dialog.collect()
        self.assertEqual((result["target_mode"], result["ips"], result["excluded_ips"]),
                         ("all", [], ["10.0.0.2"]))
        dialog.excluded_ips.add("10.0.0.1")
        with self.assertRaises(ValueError):
            dialog.collect()

        old = self.add_schedule(ips=["10.0.0.1", "10.0.0.2"], excluded_ips=["10.0.0.2"])
        editor = gui.ScheduleDialog(root, old, self.day)
        self.addCleanup(editor.destroy)
        self.assertEqual(editor.mode.get(), "saved")
        result = editor.collect()
        self.assertEqual((result["target_mode"], result["ips"], result["excluded_ips"]),
                         ("selected", ["10.0.0.1", "10.0.0.2"], ["10.0.0.2"]))

    def test_custom_label_persists_on_create_and_edit_and_in_report(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        with patch.object(gui._Dialog, "finish_layout"):
            dialog = gui.ScheduleDialog(root, None, self.day)
            self.addCleanup(dialog.destroy)
            dialog.individual_picker.select(["10.0.0.1"])
            dialog.label.set("  Aula informática  ")
            result = dialog.collect()
            self.assertEqual(result["schedule_label"], "Aula informática")

            app = SimpleNamespace(generate_schedule_txts=lambda *_: None, refresh_all=lambda: None)
            parent = SimpleNamespace(wait_window=lambda _: None)
            with patch.object(gui, "ScheduleDialog", return_value=SimpleNamespace(result=result)):
                gui.schedule_new(app, parent, self.day)
            item = self.schedules.all()[0]
            self.assertEqual(gui._schedule_label(item), "Aula informática")

            editor = gui.ScheduleDialog(root, item, self.day)
            self.addCleanup(editor.destroy)
            self.assertEqual(editor.label.get(), "Aula informática")
            editor.label.set("Laboratorio")
            edited = editor.collect()
            with patch.object(gui, "ScheduleDialog", return_value=SimpleNamespace(result=edited)):
                gui.schedule_edit(app, parent, item["id"])
        item = self.schedules.get(item["id"])
        self.assertEqual(item["schedule_label"], "Laboratorio")
        with patch.object(store.history, "status_map", return_value={}):
            _, _, rows = reports.build_report("schedules", "day", self.day)
        self.assertEqual(rows[0][3], "Laboratorio")
        schedule_txt.generate(self.day)
        self.assertEqual((self.output / f"{self.day.isoformat()}.txt").read_text().splitlines(),
                         [r"\\10.0.0.1"])
        archive.delete_to_history(item["id"])
        self.assertEqual(gui._schedule_label(self.archive.all()[0]), "Laboratorio")

    def test_legacy_label_remains_and_report_fallback_is_unchanged(self):
        item = self.add_schedule(ip="10.0.0.1", label="Asignación anterior")
        self.assertEqual(gui._schedule_label(item), "Asignación anterior")
        with patch.object(store.history, "status_map", return_value={}):
            _, _, rows = reports.build_report("schedules", "day", self.day)
        self.assertEqual(rows[0][3], "Asignación anterior")


if __name__ == "__main__":
    unittest.main()
