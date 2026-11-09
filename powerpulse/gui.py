import calendar
import hashlib
import os
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, ttk

from . import __version__, archive, background, backup, paths, reports, schedule_txt, store, theme
from . import dialogs as messagebox
from .schedule_targets import included_ips, scope_ips
from .occurrences import (REPEATS, WEEKDAYS, dates_for, fmt_date, in_range, parse_time,
                          parse_user_date, period_range, status_for, weekdays_text)

MONTHS = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
          "Septiembre", "Octubre", "Noviembre", "Diciembre"]
REPEAT_BY_NAME = {v: k for k, v in REPEATS.items()}


def _selected_id(tree: ttk.Treeview) -> str | None:
    sel = tree.selection()
    return sel[0] if sel else None


def _make_tree(parent, columns: dict[str, int]) -> ttk.Treeview:
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True)
    tree = ttk.Treeview(frame, columns=list(columns), show="headings", selectmode="browse")
    for name, width in columns.items():
        tree.heading(name, text=name)
        tree.column(name, width=width, anchor="w")
    sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return tree


def _search_box(bar, var: tk.StringVar, width: int = 24):
    ttk.Label(bar, text="Buscar:").pack(side="left", padx=(16, 4))
    ttk.Entry(bar, textvariable=var, width=width).pack(side="left")


def _matches(needle: str, values) -> bool:
    return not needle or needle.lower() in " ".join(str(v) for v in values).lower()


def _schedule_equipment_text(item: dict) -> str:
    if item.get("target_mode") == "all":
        count = len(item.get("excluded_ips", []))
        return f"Todos ({count} excluidos)" if count else "Todos"
    if "ips" not in item:
        return item.get("ip", "")
    if item.get("target_mode") == "individual" and len(included_ips(item)) == 1:
        return included_ips(item)[0]
    excluded = len(item.get("excluded_ips", []))
    count = len(included_ips(item))
    noun = "equipo" if count == 1 else "equipos"
    suffix = f" ({excluded} excluidos)" if excluded else ""
    return f"{count} {noun}{suffix}"


def _schedule_search_values(item: dict) -> list[str]:
    return [_schedule_equipment_text(item), *scope_ips(item)]


def _schedule_label(item: dict) -> str:
    return item.get("schedule_label") or item.get("label", "")


class EquipmentPicker(ttk.Frame):
    """Lista de equipos con buscador; conserva la selección al filtrar."""

    def __init__(self, parent, selectmode: str, height: int = 10):
        super().__init__(parent)
        self.mode = selectmode
        self.assignments = store.load_assignments()
        self.selected: set[str] = set()
        self.visible: list[dict] = []
        self.needle = tk.StringVar()
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 4))
        ttk.Label(top, text="Buscar:").pack(side="left")
        ttk.Entry(top, textvariable=self.needle).pack(side="left", fill="x", expand=True, padx=4)
        self.count = ttk.Label(self)
        if selectmode != "browse":
            ttk.Button(top, text="Seleccionar todos",
                       command=lambda: self.select(a["ip"] for a in self.assignments)).pack(side="left")
            ttk.Button(top, text="Marcar visibles", command=self.mark_visible).pack(side="left")
            ttk.Button(top, text="Quitar todos", command=lambda: self.select([])).pack(side="left", padx=4)
            self.count.pack(anchor="w")
        box = ttk.Frame(self)
        box.pack(fill="both", expand=True)
        p = theme.pal()
        self.lb = tk.Listbox(box, selectmode=selectmode, height=height, exportselection=False, width=60,
                             bg=p["field"], fg=p["fg"], selectbackground=p["sel"],
                             selectforeground=p["selfg"], highlightthickness=0, borderwidth=0)
        sb = ttk.Scrollbar(box, command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.lb.bind("<<ListboxSelect>>", self._on_select)
        self.needle.trace_add("write", lambda *_: self._fill())
        self._fill()

    def _fill(self):
        n = self.needle.get().lower()
        self.visible = [a for a in self.assignments if n in store.equipment_text(a).lower()]
        self.lb.delete(0, "end")
        for i, a in enumerate(self.visible):
            self.lb.insert("end", store.equipment_text(a))
            if a["ip"] in self.selected:
                self.lb.selection_set(i)

    def _on_select(self, _=None):
        chosen = {self.visible[i]["ip"] for i in self.lb.curselection()}
        if self.mode == "browse":
            self.selected = chosen
        else:
            self.selected -= {a["ip"] for a in self.visible}
            self.selected |= chosen
        self.count.config(text=f"{len(self.selected)} equipo(s) seleccionado(s)")

    def mark_visible(self):
        self.lb.selection_set(0, "end")
        self._on_select()
    def select(self, ips):
        self.selected = set(ips)
        self._fill()
        self.count.config(text=f"{len(self.selected)} equipo(s) seleccionado(s)")
        first = next((i for i, a in enumerate(self.visible) if a["ip"] in self.selected), None)
        if first is not None:
            self.lb.see(first)

    def selected_assignments(self) -> list[dict]:
        return [a for a in self.assignments if a["ip"] in self.selected]


class _CalendarPopup(tk.Toplevel):
    def __init__(self, owner, start: date, allow_empty: bool, var: tk.StringVar):
        super().__init__(owner)
        self.title("Seleccionar fecha")
        self.configure(bg=theme.pal()["bg"])
        self.resizable(False, False)
        self.owner_top = owner.winfo_toplevel()
        self.transient(self.owner_top)
        self.var, self.sel, self.view = var, start, start.replace(day=1)
        head = ttk.Frame(self, padding=6)
        head.pack(fill="x")
        for text, step, side in (("<<", -12, "left"), ("<", -1, "left"), (">>", 12, "right"), (">", 1, "right")):
            ttk.Button(head, text=text, width=3, command=lambda s=step: self.shift(s)).pack(side=side)
        self.title_lbl = ttk.Label(head, anchor="center", font=("Segoe UI", 10, "bold"))
        self.title_lbl.pack(fill="x", expand=True)
        self.grid_frame = tk.Frame(self, bg=theme.pal()["bg"])
        self.grid_frame.pack(padx=6)
        foot = ttk.Frame(self, padding=6)
        foot.pack(fill="x")
        ttk.Button(foot, text="Hoy", command=lambda: self.pick(date.today())).pack(side="left")
        if allow_empty:
            ttk.Button(foot, text="Borrar", command=lambda: self.pick(None)).pack(side="left", padx=4)
        ttk.Button(foot, text="Cancelar", command=self.close).pack(side="right")
        self.draw()
        self.geometry(f"+{owner.winfo_rootx()}+{owner.winfo_rooty() + owner.winfo_height()}")
        self.wait_visibility()
        theme.style_titlebar(self)
        self.grab_set()
        self.bind("<Escape>", lambda e: self.close())

    def shift(self, months: int):
        y, m = divmod(self.view.year * 12 + self.view.month - 1 + months, 12)
        self.view = date(y, m + 1, 1)
        self.draw()

    def draw(self):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.title_lbl.config(text=f"{MONTHS[self.view.month - 1]} {self.view.year}")
        p = theme.pal()
        for c, name in enumerate(WEEKDAYS):
            tk.Label(self.grid_frame, text=name, bg=p["bg"], fg=p["fg"],
                     font=("Segoe UI", 9, "bold"), width=4).grid(row=0, column=c)
        today = date.today()
        for r, week in enumerate(calendar.Calendar(0).monthdayscalendar(self.view.year, self.view.month), 1):
            for c, day in enumerate(week):
                if not day:
                    continue
                d = date(self.view.year, self.view.month, day)
                bg = p["sel"] if d == self.sel else p["today"] if d == today else p["idle"]
                lbl = tk.Label(self.grid_frame, text=str(day), bg=bg, cursor="hand2", width=4, height=2,
                               fg=p["selfg"] if d == self.sel else p["fg"], relief="ridge")
                lbl.grid(row=r, column=c, padx=1, pady=1)
                lbl.bind("<Button-1>", lambda e, d=d: self.pick(d))

    def pick(self, d: date | None):
        self.var.set(fmt_date(d) if d else "")
        self.close()

    def close(self):
        self.destroy()
        if isinstance(self.owner_top, _Dialog):
            self.owner_top.grab_set()


class DatePicker(ttk.Frame):
    """Campo de fecha editable con selector de calendario."""

    def __init__(self, parent, var: tk.StringVar, width: int = 12, allow_empty: bool = False):
        super().__init__(parent)
        self.var, self.allow_empty = var, allow_empty
        ttk.Entry(self, textvariable=var, width=width).pack(side="left")
        ttk.Button(self, text="▾", width=3, command=self.open).pack(side="left", padx=(2, 0))

    def open(self):
        try:
            start = parse_user_date(self.var.get())
        except ValueError:
            start = date.today()
        _CalendarPopup(self, start, self.allow_empty, self.var)


class TimePicker(ttk.Frame):
    """Hora HH:MM (24 h) con selectores de hora y minutos."""

    def __init__(self, parent, var: tk.StringVar):
        super().__init__(parent)
        self.var = var
        try:
            h, m = parse_time(var.get()).split(":")
        except ValueError:
            h, m = "08", "00"
        self.h, self.m = tk.StringVar(value=h), tk.StringVar(value=m)
        ttk.Spinbox(self, from_=0, to=23, width=3, wrap=True, format="%02.0f",
                    textvariable=self.h, command=self.sync).pack(side="left")
        ttk.Label(self, text=":").pack(side="left")
        ttk.Spinbox(self, from_=0, to=59, width=3, wrap=True, format="%02.0f",
                    textvariable=self.m, command=self.sync).pack(side="left")
        for v in (self.h, self.m):
            v.trace_add("write", lambda *_: self.sync())
        self.sync()

    def sync(self):
        try:
            self.var.set(f"{int(self.h.get()):02d}:{int(self.m.get()):02d}")
        except ValueError:
            pass


class TimingForm(ttk.Frame):
    """Campos de fecha/hora/repetición para las programaciones del calendario."""

    def __init__(self, parent, item: dict | None, default_date: date, *, date_only: bool = False,
                 fixed_time: str = "17:00"):
        super().__init__(parent)
        item = item or {}
        self.date_only = date_only
        self.fixed_time = fixed_time
        self.date = tk.StringVar(value=fmt_date(item.get("start_date") or default_date))
        self.time = tk.StringVar(value=item.get("time", "08:00"))
        self.repeat = tk.StringVar(value=REPEATS[item.get("repeat", "none")])
        self.until = tk.StringVar(value=fmt_date(item.get("until")))
        self.enabled = tk.BooleanVar(value=item.get("enabled", True))
        days = item.get("weekdays", [])
        self.wd = [tk.BooleanVar(value=i in days) for i in range(7)]

        ttk.Label(self, text="Fecha:" if date_only else "Fecha / desde:").grid(
            row=0, column=0, sticky="w", pady=2)
        DatePicker(self, self.date, 14).grid(row=0, column=1, sticky="w")
        if date_only:
            ttk.Label(self, text="Hasta (opcional):").grid(row=1, column=0, sticky="w", pady=2)
            DatePicker(self, self.until, 14, allow_empty=True).grid(row=1, column=1, sticky="w")
            ttk.Checkbutton(self, text="Activa", variable=self.enabled).grid(
                row=2, column=0, sticky="w")
            return
        self.until_lbl = ttk.Label(self)
        self.until_lbl.grid(row=0, column=2, sticky="w", padx=(12, 0))
        DatePicker(self, self.until, 14, allow_empty=True).grid(row=0, column=3, sticky="w")
        self._update_until_label()
        wdf = ttk.Frame(self)
        wdf.grid(row=2, column=0, columnspan=4, sticky="w", pady=2)
        ttk.Label(wdf, text="Días (semanal):").pack(side="left")
        for i, v in enumerate(self.wd):
            ttk.Checkbutton(wdf, text=WEEKDAYS[i], variable=v).pack(side="left", padx=2)
        ttk.Checkbutton(self, text="Activa", variable=self.enabled).grid(row=3, column=0, sticky="w")

    def _update_until_label(self):
        is_range = REPEAT_BY_NAME[self.repeat.get()] == "range"
        self.until_lbl.config(text="Hasta (obligatoria):" if is_range else "Hasta (opcional):")

    def values(self) -> dict:
        start = parse_user_date(self.date.get())
        if self.date_only:
            until = parse_user_date(self.until.get()) if self.until.get().strip() else None
            if until and until < start:
                raise ValueError("'Hasta' no puede ser anterior a la fecha de inicio")
            return {"start_date": start.isoformat(), "time": self.fixed_time, "repeat": "daily",
                    "until": until.isoformat() if until else None,
                    "weekdays": [], "enabled": self.enabled.get()}
        until = parse_user_date(self.until.get()) if self.until.get().strip() else None
        if until and until < start:
            raise ValueError("'Hasta' no puede ser anterior a la fecha de inicio")
        repeat = REPEAT_BY_NAME[self.repeat.get()]
        if repeat == "range" and not until:
            raise ValueError("Indique la fecha 'Hasta' para el rango de días")
        weekdays = [i for i, v in enumerate(self.wd) if v.get()] if repeat == "weekly" else []
        return {"start_date": start.isoformat(), "time": parse_time(self.time.get()),
                "repeat": repeat, "until": until.isoformat() if until else None,
                "weekdays": weekdays, "enabled": self.enabled.get()}


class _Dialog(tk.Toplevel):
    def __init__(self, parent, title: str):
        super().__init__(parent)
        self.title(title)
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        self.configure(bg=theme.pal()["bg"])
        try:
            self.iconbitmap(paths.ICON_FILE)
        except tk.TclError:
            pass
        self.result = None
        self.body = ttk.Frame(self, padding=10)
        self.body.pack(fill="both", expand=True)

    def finish_layout(self):
        bar = ttk.Frame(self, padding=(10, 0, 10, 10))
        bar.pack(fill="x")
        ttk.Button(bar, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="Guardar", command=self._ok).pack(side="right", padx=6)
        self.grab_set()
        self.wait_visibility()
        theme.style_titlebar(self)
        self.focus_set()

    def _ok(self):
        try:
            self.result = self.collect()
        except ValueError as exc:
            messagebox.showerror("Datos no válidos", str(exc), parent=self)
            return
        self.destroy()


class ScheduleDialog(_Dialog):
    def __init__(self, parent, item: dict | None, default_date: date, *, fixed_time: str = "17:00"):
        super().__init__(parent, "Editar programación" if item else "Nueva programación")
        old_scope = scope_ips(item) if item else []
        if item and item.get("target_mode") == "all":
            initial_mode = "all"
        elif len(old_scope) > 1 or (item and item.get("excluded_ips")):
            initial_mode = "saved"
        else:
            initial_mode = "individual"
        self.mode = tk.StringVar(value=initial_mode)
        choices = ttk.Frame(self.body)
        choices.pack(fill="x")
        ttk.Radiobutton(choices, text="Individual", variable=self.mode, value="individual",
                        command=self._show_mode).pack(side="left")
        ttk.Radiobutton(choices, text="Todos con exclusiones", variable=self.mode, value="all",
                        command=self._show_mode).pack(side="left", padx=12)
        if initial_mode == "saved":
            ttk.Radiobutton(choices, text="Selección guardada", variable=self.mode, value="saved",
                            command=self._show_mode).pack(side="left")
        self.target_area = ttk.Frame(self.body)
        self.target_area.pack(fill="both", expand=True, pady=(6, 0))
        self.individual_frame = ttk.Frame(self.target_area)
        ttk.Label(self.individual_frame, text="Seleccione un equipo:").pack(anchor="w")
        self.individual_picker = EquipmentPicker(self.individual_frame, "browse")
        self.individual_picker.pack(fill="both", expand=True)
        if initial_mode == "individual" and old_scope:
            self.individual_picker.select(old_scope)
        self.saved_frame = ttk.Frame(self.target_area)
        if initial_mode == "saved":
            ttk.Label(self.saved_frame, text="Equipos de la selección guardada:").pack(anchor="w")
            self.saved_picker = EquipmentPicker(self.saved_frame, "extended")
            self.saved_picker.pack(fill="both", expand=True)
            self.saved_picker.select(old_scope)
        self.all_frame = ttk.Frame(self.target_area)
        ttk.Label(self.all_frame, text="Incluye los equipos actuales y los que se añadan a MapPulse.",
                  wraplength=500).pack(anchor="w")
        self.excluded_ips = set((item or {}).get("excluded_ips", []))
        self.all_summary = self._exclusions_bar(self.all_frame)
        self.saved_summary = self._exclusions_bar(self.saved_frame) if initial_mode == "saved" else None
        self._update_exclusion_summary()
        self._show_mode()
        self.timing = TimingForm(self.body, item, default_date, date_only=item is None,
                                 fixed_time=fixed_time)
        self.timing.pack(fill="x", pady=8)
        ttk.Label(self.body, text="Etiqueta personalizada (opcional):").pack(anchor="w")
        self.label = tk.StringVar(value=(item or {}).get("schedule_label", ""))
        ttk.Entry(self.body, textvariable=self.label).pack(fill="x")
        ttk.Label(self.body, text="Notas:").pack(anchor="w")
        self.notes = tk.StringVar(value=(item or {}).get("notes", ""))
        ttk.Entry(self.body, textvariable=self.notes).pack(fill="x")
        self.finish_layout()

    def _exclusions_bar(self, parent):
        exclusions = ttk.Frame(parent)
        exclusions.pack(fill="x", pady=(5, 0))
        ttk.Button(exclusions, text="Gestionar excluidos…", command=self.manage_exclusions).pack(side="left")
        summary = ttk.Label(exclusions)
        summary.pack(side="left", padx=8)
        return summary

    def _show_mode(self):
        for frame in (self.individual_frame, self.all_frame, self.saved_frame):
            frame.pack_forget()
        frame = {"individual": self.individual_frame, "all": self.all_frame,
                 "saved": self.saved_frame}[self.mode.get()]
        frame.pack(fill="both", expand=True)

    def manage_exclusions(self):
        dlg = ExcludedEquipmentDialog(self, self.excluded_ips)
        self.wait_window(dlg)
        if dlg.result is not None:
            self.excluded_ips = set(dlg.result)
            self._update_exclusion_summary()

    def _update_exclusion_summary(self):
        count = len(self.excluded_ips)
        noun = "equipo" if count == 1 else "equipos"
        status = "excluido" if count == 1 else "excluidos"
        text = f"{count} {noun} {status}" if count else "Ninguno"
        self.all_summary.config(text=text)
        if self.saved_summary is not None:
            self.saved_summary.config(text=text)

    def collect(self):
        mode = self.mode.get()
        if mode == "individual":
            scope = self.individual_picker.selected
            if len(scope) != 1:
                raise ValueError("Seleccione un equipo para la programación individual")
            excluded = set()
        elif mode == "saved":
            scope = self.saved_picker.selected
            excluded = self.excluded_ips
            if not scope:
                raise ValueError("Seleccione al menos un equipo para la programación")
            if excluded - scope:
                raise ValueError("Los equipos excluidos deben estar dentro de los equipos seleccionados")
            if not scope - excluded:
                raise ValueError("No puede excluir todos los equipos seleccionados")
        else:
            scope = set()
            excluded = self.excluded_ips
            assignments = store.load_assignments_strict()
            if not {a["ip"] for a in assignments} - excluded:
                raise ValueError("Debe haber al menos un equipo de MapPulse sin excluir")
        timing = self.timing.values()
        if archive.is_finished(timing):
            raise ValueError("La programación ya habría finalizado (fechas pasadas). Indique una fecha futura.")
        return {"target_mode": "all" if mode == "all" else "individual" if mode == "individual" else "selected",
                "ips": sorted(scope), "excluded_ips": sorted(excluded),
                "timing": timing,
                "schedule_label": self.label.get().strip(),
                "notes": self.notes.get().strip()}


class ExcludedEquipmentDialog(_Dialog):
    def __init__(self, parent, excluded_ips: set[str]):
        super().__init__(parent, "Equipos excluidos")
        ttk.Label(self.body, text="Seleccione los equipos que no deben incluirse:").pack(anchor="w")
        self.picker = EquipmentPicker(self.body, "extended", height=12)
        self.picker.pack(fill="both", expand=True)
        self.picker.select(excluded_ips)
        self.finish_layout()

    def collect(self):
        return sorted(self.picker.selected)


def _crud_buttons(parent, app, new, edit, delete):
    bar = ttk.Frame(parent)
    bar.pack(fill="x", pady=(0, 6))
    ttk.Button(bar, text="Nuevo", command=new).pack(side="left")
    ttk.Button(bar, text="Editar", command=edit).pack(side="left", padx=4)
    ttk.Button(bar, text="Borrar", command=delete).pack(side="left")
    ttk.Button(bar, text="Actualizar", command=app.refresh_and_cleanup).pack(side="left", padx=4)
    return bar


def schedule_new(app, parent, default_date: date, profile: str = "5pm"):
    fixed_time = "07:00" if profile == "7am" else "17:00"
    dlg = ScheduleDialog(parent, None, default_date, fixed_time=fixed_time)
    parent.wait_window(dlg)
    if dlg.result:
        store.schedules.add({"target_mode": dlg.result["target_mode"], "ips": dlg.result["ips"],
                             "excluded_ips": dlg.result["excluded_ips"],
                             "profile": profile,
                             "schedule_label": dlg.result["schedule_label"],
                             "notes": dlg.result["notes"], **dlg.result["timing"]})
        app.generate_schedule_txts(parent, profile=profile)
        app.refresh_all()


def schedule_edit(app, parent, item_id: str | None, profile: str = "5pm"):
    item = item_id and store.schedules.get(item_id)
    if not item or item.get("profile", "5pm") != profile:
        messagebox.showinfo("PowerPulse", "Seleccione una programación.", parent=parent)
        return
    dlg = ScheduleDialog(parent, item, date.today())
    parent.wait_window(dlg)
    if dlg.result:
        legacy_label = item.get("label", "") if (
            dlg.result["target_mode"] == "individual" and
            dlg.result["ips"] == scope_ips(item)) else ""
        store.schedules.update(item_id, {"target_mode": dlg.result["target_mode"], "ips": dlg.result["ips"],
                                         "excluded_ips": dlg.result["excluded_ips"],
                                         "ip": None, "label": legacy_label,
                                         "schedule_label": dlg.result["schedule_label"],
                                         "notes": dlg.result["notes"], **dlg.result["timing"]})
        app.generate_schedule_txts(parent, profile=profile)
        app.refresh_all()


def schedule_delete(app, parent, item_id: str | None, profile: str = "5pm"):
    item = item_id and store.schedules.get(item_id)
    if not item or item.get("profile", "5pm") != profile:
        messagebox.showinfo("PowerPulse", "Seleccione una programación.", parent=parent)
        return
    extra = "\nSe eliminará toda la serie repetida." if item["repeat"] != "none" else ""
    targets = included_ips(item)
    count = len(targets)
    noun = "equipo" if count == 1 else "equipos"
    target_text = item.get("ip") or f"{count} {noun}"
    if messagebox.askyesno("Borrar", f"¿Borrar la programación de {target_text}?{extra}", parent=parent):
        try:
            archive.delete_to_history(item_id)
        except (OSError, ValueError, KeyError) as exc:
            store.log.exception("No se pudo conservar la programación eliminada en el histórico")
            messagebox.showerror("Borrar", f"No se pudo borrar la programación:\n{exc}", parent=parent)
            return
        app.generate_schedule_txts(parent, profile=profile)
        app.refresh_all()


class ScheduleTab(ttk.Frame):
    COLS = {"Fecha": 90, "Hora": 60, "Equipos": 120, "Etiqueta": 180, "Repetición": 90,
            "Días": 140, "Hasta": 90, "Activa": 60, "Estado": 110, "Notas": 200}

    def __init__(self, parent, app, profile: str = "5pm"):
        super().__init__(parent, padding=8)
        self.app = app
        self.profile = profile
        self.fixed_time = "07:00" if profile == "7am" else "17:00"
        self.output_dir = schedule_txt.OUTPUT_DIR_7AM if profile == "7am" else schedule_txt.OUTPUT_DIR
        bar = _crud_buttons(self, app, lambda: schedule_new(app, self, date.today(), profile),
                            lambda: schedule_edit(app, self, _selected_id(self.tree), profile),
                            lambda: schedule_delete(app, self, _selected_id(self.tree), profile))
        ttk.Button(bar, text="Generar TXT",
                   command=lambda: app.generate_schedule_txts(self, notify=True, profile=profile)).pack(
            side="left", padx=4)
        ttk.Label(self, text=f"Archivos diarios a las {self.fixed_time} en: {self.output_dir} "
                             f"(365 días para repeticiones sin fecha final)").pack(anchor="w", pady=(0, 6))
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *_: self.refresh())
        _search_box(bar, self.filter)
        self.tree = _make_tree(self, self.COLS)
        tag = "schedule_7am" if profile == "7am" else "schedule_5pm"
        self.tree.tag_configure(tag, foreground=theme.pal()[tag])
        self.row_tag = tag
        self.tree.bind("<Double-1>", lambda e: schedule_edit(app, self, _selected_id(self.tree), profile))

    def refresh(self):
        sel = _selected_id(self.tree)
        self.tree.delete(*self.tree.get_children())
        hist = store.history.status_map()
        needle = self.filter.get()
        schedules = (s for s in store.schedules.all()
                     if s.get("profile", "5pm") == self.profile)
        for s in sorted(schedules, key=lambda s: (s["start_date"], s["time"])):
            hits = [k.split("|")[1] for k in hist if k.startswith(s["id"])]
            status = hist[f"{s['id']}|{max(hits)}"]["status"] if hits else (
                "Pendiente" if s.get("enabled", True) else "Desactivada")
            row = (fmt_date(s["start_date"]), s["time"], _schedule_equipment_text(s), _schedule_label(s),
                   REPEATS[s["repeat"]], weekdays_text(s), fmt_date(s.get("until")),
                   "Sí" if s.get("enabled", True) else "No", status, s.get("notes", ""))
            if not _matches(needle, [*row, *_schedule_search_values(s)]):
                continue
            self.tree.insert("", "end", iid=s["id"], values=row, tags=(self.row_tag,))
        if sel and self.tree.exists(sel):
            self.tree.selection_set(sel)


class CalendarTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=8)
        self.app = app
        self.sel = date.today()
        self.mode = tk.StringVar(value="month")

        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Button(bar, text="<", width=3, command=lambda: self.shift(-1)).pack(side="left")
        ttk.Button(bar, text="Hoy", command=self.today).pack(side="left", padx=4)
        ttk.Button(bar, text=">", width=3, command=lambda: self.shift(1)).pack(side="left")
        self.title = ttk.Label(bar, font=("Segoe UI", 13, "bold"))
        self.title.pack(side="left", padx=16)
        for text, val in (("Día", "day"), ("Mes", "month"), ("Año", "year")):
            ttk.Radiobutton(bar, text=text, value=val, variable=self.mode,
                            command=self.refresh).pack(side="right", padx=2)

        self.grid_frame = ttk.Frame(self)
        self.grid_frame.pack(fill="x", pady=8)

        self.panel = ttk.LabelFrame(self, text="Programaciones del día", padding=6)
        self.panel.pack(fill="both", expand=True)
        bar = _crud_buttons(self.panel, app, lambda: schedule_new(app, self, self.sel),
                            lambda: schedule_edit(app, self, self._sel_id()),
                            lambda: schedule_delete(app, self, self._sel_id()))
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *_: self.refresh())
        ttk.Button(bar, text="Ir a la fecha", command=self.goto_result).pack(side="left")
        _search_box(bar, self.filter)
        self.tree = _make_tree(self.panel, {"Hora": 60, "Equipos": 120, "Etiqueta": 200,
                                            "Repetición": 90, "Estado": 110, "Notas": 250})
        for tag in ("schedule_5pm", "schedule_7am"):
            self.tree.tag_configure(tag, foreground=theme.pal()[tag])
        self.tree.bind("<Double-1>", lambda e: schedule_edit(app, self, _selected_id(self.tree)))
        self.stree = _make_tree(self.panel, {"Fecha": 90, "Hora": 60, "Equipos": 110, "Etiqueta": 170,
                                             "Repetición": 90, "Desde": 90, "Hasta": 90, "Activa": 55,
                                             "Estado": 100, "Notas": 200})
        for tag in ("schedule_5pm", "schedule_7am"):
            self.stree.tag_configure(tag, foreground=theme.pal()[tag])
        self.stree.bind("<Double-1>", lambda e: schedule_edit(app, self, _selected_id(self.stree)))
        self.stree.master.pack_forget()

    def _searching(self) -> bool:
        return bool(self.filter.get().strip())

    def _sel_id(self):
        return _selected_id(self.stree if self._searching() else self.tree)

    @staticmethod
    def _focus_date(s: dict) -> date:
        """Próxima fecha de la programación o, si ya pasó, la última."""
        today = date.today()
        ahead = dates_for(s, today, today + timedelta(days=366))
        if ahead:
            return ahead[0]
        start = date.fromisoformat(s["start_date"])
        if s.get("until"):
            past = dates_for(s, start, date.fromisoformat(s["until"]))
            return past[-1] if past else start
        return start

    def goto_result(self):
        item = self._sel_id() and store.schedules.get(self._sel_id())
        if not item:
            return messagebox.showinfo("Calendario", "Seleccione un resultado de la búsqueda.", parent=self)
        self.sel = self._focus_date(item)
        self.filter.set("")
        self.refresh()

    def today(self):
        self.sel = date.today()
        self.refresh()

    def shift(self, step: int):
        mode = self.mode.get()
        if mode == "day":
            self.sel += timedelta(days=step)
        else:
            months = step * (1 if mode == "month" else 12)
            m = self.sel.year * 12 + self.sel.month - 1 + months
            y, mo = divmod(m, 12)
            day = min(self.sel.day, calendar.monthrange(y, mo + 1)[1])
            self.sel = date(y, mo + 1, day)
        self.refresh()

    def pick(self, d: date):
        self.sel = d
        self.refresh()

    def refresh(self):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        mode = self.mode.get()
        d0, d1 = period_range(mode if mode != "day" else "month", self.sel)
        data = in_range(store.schedules.all(), d0, d1)
        if mode == "month":
            self.title.config(text=f"{MONTHS[self.sel.month - 1]} {self.sel.year}")
            self._month_grid(self.grid_frame, self.sel.year, self.sel.month, data, big=True)
        elif mode == "year":
            self.title.config(text=str(self.sel.year))
            for m in range(12):
                f = ttk.LabelFrame(self.grid_frame, text=MONTHS[m])
                f.grid(row=m // 4, column=m % 4, padx=4, pady=2, sticky="n")
                self._month_grid(f, self.sel.year, m + 1, data, big=False)
        else:
            self.title.config(text=f"{WEEKDAYS[self.sel.weekday()]} {fmt_date(self.sel)}")
        self._fill_day(data.get(self.sel, []) if mode != "day" else
                       in_range(store.schedules.all(), self.sel, self.sel).get(self.sel, []))

    def _month_grid(self, parent, year, month, data, big: bool):
        p = theme.pal()
        for c, name in enumerate(WEEKDAYS):
            tk.Label(parent, text=name, bg=p["bg"], fg=p["fg"],
                     font=("Segoe UI", 9 if big else 7, "bold")).grid(row=0, column=c)
        today = date.today()
        for r, week in enumerate(calendar.Calendar(0).monthdayscalendar(year, month), 1):
            for c, day in enumerate(week):
                if not day:
                    continue
                d = date(year, month, day)
                n = len(data.get(d, []))
                bg = p["sel"] if d == self.sel else p["today"] if d == today else p["busy"] if n else p["idle"]
                text = f"{day}\n{n} prog." if big and n else str(day)
                lbl = tk.Label(parent, text=text, bg=bg, fg=p["selfg"] if d == self.sel else p["fg"],
                               relief="ridge", cursor="hand2",
                               width=11 if big else 3, height=3 if big else 1,
                               font=("Segoe UI", 9 if big else 7))
                lbl.grid(row=r, column=c, padx=1, pady=1)
                lbl.bind("<Button-1>", lambda e, d=d: self.pick(d))

    def _fill_day(self, items):
        self.tree.master.pack_forget()
        self.stree.master.pack_forget()
        if self._searching():
            self.stree.master.pack(fill="both", expand=True)
            return self._fill_search()
        self.tree.master.pack(fill="both", expand=True)
        self.panel.config(text=f"Programaciones del {fmt_date(self.sel)}")
        self.tree.delete(*self.tree.get_children())
        hist = store.history.status_map()
        for s in items:
            self.tree.insert("", "end", iid=s["id"], values=(
                s["time"], _schedule_equipment_text(s), _schedule_label(s), REPEATS[s["repeat"]],
                status_for(s, self.sel, hist), s.get("notes", "")),
                tags=("schedule_7am" if s.get("profile") == "7am" else "schedule_5pm",))

    def _fill_search(self):
        needle = self.filter.get().strip()
        sel = _selected_id(self.stree)
        self.stree.delete(*self.stree.get_children())
        hist = store.history.status_map()
        try:
            day = parse_user_date(needle)
        except ValueError:
            day = None
        found = []
        for s in store.schedules.all():
            focus = self._focus_date(s)
            row = (fmt_date(focus), s["time"], _schedule_equipment_text(s), _schedule_label(s), REPEATS[s["repeat"]],
                   fmt_date(s["start_date"]), fmt_date(s.get("until")), "Sí" if s.get("enabled", True) else "No",
                   status_for(s, focus, hist), s.get("notes", ""))
            if _matches(needle, [*row, *_schedule_search_values(s)]) or (day and dates_for(s, day, day)):
                tag = "schedule_7am" if s.get("profile") == "7am" else "schedule_5pm"
                found.append((focus, s["time"], s["id"], row, tag))
        for _, _, sid, row, tag in sorted(found):
            self.stree.insert("", "end", iid=sid, values=row, tags=(tag,))
        self.panel.config(text=f"Búsqueda en todas las fechas: {len(found)} resultado(s). "
                               "La fecha es la próxima o, si ya pasó, la última.")
        if sel and self.stree.exists(sel):
            self.stree.selection_set(sel)


def export_table(parent, title: str, headers: list[str], rows: list[list[str]], name: str):
    path = filedialog.asksaveasfilename(
        parent=parent, initialdir=paths.REPORTS_DIR, defaultextension=".xlsx",
        initialfile=f"PowerPulse_{name}_{datetime.now():%Y%m%d_%H%M%S}.xlsx",
        filetypes=[("XLSX", "*.xlsx"), ("PDF", "*.pdf")])
    if not path:
        return
    writer = {".xlsx": reports.write_xlsx, ".pdf": reports.write_pdf}.get(Path(path).suffix.lower())
    if not writer:
        return messagebox.showerror("Exportar", "Elija formato .xlsx o .pdf.", parent=parent)
    try:
        writer(path, title, headers, rows)
    except OSError as exc:
        return messagebox.showerror("Exportar", f"No se pudo escribir el fichero:\n{exc}", parent=parent)
    store.log.info("INFORME generado: %s (%d filas)", path, len(rows))
    if messagebox.askyesno("Exportar", f"Exportado ({len(rows)} filas).\n¿Abrirlo ahora?", parent=parent):
        os.startfile(path)


class ArchiveTab(ttk.Frame):
    HEADERS = ["Registro", "Última fecha", "Hora", "Equipos", "Etiqueta", "Repetición", "Desde", "Hasta",
               "Estado", "Notas"]

    def __init__(self, parent, app):
        super().__init__(parent, padding=8)
        self.app = app
        self.rows: list[list[str]] = []
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="Exportar PDF/XLSX...", command=self.export).pack(side="left", padx=4)
        ttk.Button(bar, text="Actualizar", command=app.refresh_and_cleanup).pack(side="left")
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *_: self.refresh())
        _search_box(bar, self.filter)
        self.summary = ttk.Label(self, foreground="gray")
        self.summary.pack(anchor="w")
        self.tree = _make_tree(self, dict(zip(self.HEADERS, (130, 90, 60, 110, 170, 90, 90, 90, 100, 200))))

    def refresh(self):
        sel = _selected_id(self.tree)
        self.tree.delete(*self.tree.get_children())
        self.rows = []
        items = [(a, True) for a in store.archive.all()]
        archived_ids = {a.get("schedule_id") for a, _ in items}
        items += [(s, False) for s in store.schedules.all() if s["id"] not in archived_ids]
        items.sort(key=lambda pair: pair[0].get("created_at", ""), reverse=True)
        for a, archived in items:
            last = a.get("last_date") if archived else archive.last_date(a)
            if archived:
                status = a.get("final_status", "Archivada")
            elif not a.get("enabled", True):
                status = "Desactivada"
            elif archive.is_elapsed(a):
                status = "Hora superada"
            else:
                status = "Pendiente"
            row = [a.get("created_at", a.get("archived_at", ""))[:16].replace("T", " "),
                   fmt_date(last), a["time"],
                   _schedule_equipment_text(a), _schedule_label(a), REPEATS[a["repeat"]], fmt_date(a["start_date"]),
                   fmt_date(a.get("until")), status, a.get("notes", "")]
            if _matches(self.filter.get(), [*row, *_schedule_search_values(a)]):
                self.rows.append(row)
                self.tree.insert("", "end", iid=("archivo:" if archived else "activa:") + a["id"], values=row)
        self.summary.config(text=f"{len(self.rows)} de {len(items)} programaciones registradas.")
        if sel and self.tree.exists(sel):
            self.tree.selection_set(sel)

    def export(self):
        export_table(self, "Histórico de programaciones", self.HEADERS, self.rows, "historico")


class StatsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=8)
        self.d0 = date.today()
        self.d1 = date.today() + timedelta(days=30)
        self.cdata = None

        cf = ttk.LabelFrame(self, text="Calendario: equipos programados", padding=6)
        cf.pack(fill="both", expand=True)
        bar = ttk.Frame(cf)
        bar.pack(fill="x", pady=(0, 6))
        self.start = tk.StringVar(value=fmt_date(self.d0))
        self.end = tk.StringVar(value=fmt_date(self.d1))
        ttk.Label(bar, text="Desde:").pack(side="left")
        DatePicker(bar, self.start).pack(side="left", padx=4)
        ttk.Label(bar, text="Hasta:").pack(side="left")
        DatePicker(bar, self.end).pack(side="left", padx=4)
        ttk.Button(bar, text="Aplicar", command=self.apply_range).pack(side="left")
        ttk.Button(bar, text="Exportar PDF/XLSX...",
                   command=lambda: self._export(self.cdata, "estadisticas_calendario")).pack(side="left", padx=4)
        self.csummary = ttk.Label(bar, font=("Segoe UI", 9, "bold"))
        self.csummary.pack(side="left", padx=12)
        self.cfilter = tk.StringVar()
        self.cfilter.trace_add("write", lambda *_: self.refresh_calendar())
        _search_box(bar, self.cfilter)
        self.ctree = _make_tree(cf, {"IP": 130, "Asignación": 260, "Fecha": 100, "Hora": 70, "Repetición": 100})

    def apply_range(self):
        try:
            d0, d1 = parse_user_date(self.start.get()), parse_user_date(self.end.get())
            if d1 < d0:
                raise ValueError("La fecha final no puede ser anterior a la inicial")
            if (d1 - d0).days > 366:
                raise ValueError("El rango máximo es de 366 días")
        except ValueError as exc:
            return messagebox.showerror("Estadísticas", str(exc), parent=self)
        self.d0, self.d1 = d0, d1
        self.refresh_calendar()

    def refresh_calendar(self):
        assign = {a["ip"]: a.get("label", "") for a in store.load_assignments()}
        active = [s for s in store.schedules.all() + archive.as_schedules() if s.get("enabled", True)]
        rows = [(ip, assign.get(ip) or s.get("label", ""), fmt_date(d), s["time"],
                 REPEATS[s["repeat"]])
                for d, items in sorted(in_range(active, self.d0, self.d1).items()) for s in items
                for ip in included_ips(s)]
        summary = (f"{len(rows)} equipos programados | "
                   f"{len({r[0] for r in rows})} equipos distintos")
        self.csummary.config(text=summary)
        self.ctree.delete(*self.ctree.get_children())
        shown = [r for r in rows if _matches(self.cfilter.get(), r)]
        for r in shown:
            self.ctree.insert("", "end", values=r)
        self.cdata = (f"Estadísticas Calendario {fmt_date(self.d0)} - {fmt_date(self.d1)}: {summary}",
                      ["IP", "Asignación", "Fecha", "Hora", "Repetición"], [list(r) for r in shown])

    def _export(self, data, name: str):
        if not data:
            return messagebox.showinfo("Estadísticas", "No hay datos que exportar.", parent=self)
        export_table(self, *data, name)

    def refresh(self):
        self.refresh_calendar()


class BackupTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=8)
        self.app = app
        self.history = tk.BooleanVar(value=True)
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *_: self.refresh())
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="Crear backup...", command=self.create).pack(side="left")
        ttk.Button(bar, text="Restaurar seleccionado", command=self.restore_selected).pack(side="left", padx=4)
        ttk.Button(bar, text="Restaurar desde archivo...", command=self.restore_file).pack(side="left")
        ttk.Button(bar, text="Eliminar", command=self.delete).pack(side="left", padx=4)
        _search_box(bar, self.filter)
        bar2 = ttk.Frame(self)
        bar2.pack(fill="x", pady=(0, 6))
        ttk.Button(bar2, text="Abrir carpeta...", command=self.open_folder).pack(side="left")
        ttk.Button(bar2, text="Ir a la carpeta por defecto", command=self.go_default).pack(side="left", padx=4)
        ttk.Button(bar2, text="Cambiar carpeta por defecto...", command=app.choose_backup_folder).pack(side="left")
        self.folder = ttk.Label(self, foreground="gray")
        self.folder.pack(anchor="w")
        ttk.Checkbutton(self, text="Incluir historial de ejecuciones en el backup",
                        variable=self.history).pack(anchor="w")
        ttk.Label(self, text="El backup (.zip) contiene la configuración y las programaciones. "
                             "Al restaurar se reemplazan los datos actuales y antes se guarda una copia "
                             "automática (pre_restore_*).", foreground="gray", wraplength=900).pack(anchor="w", pady=4)
        self.tree = _make_tree(self, {"Fichero": 420, "Fecha": 150, "Tamaño": 90})

    def view_dir(self) -> Path:
        return self.app.backup_view or backup.backup_dir()

    def refresh(self):
        sel = _selected_id(self.tree)
        self.tree.delete(*self.tree.get_children())
        folder = self.view_dir()
        kind = "por defecto" if self.app.backup_view is None else "seleccionada"
        self.folder.config(text=f"Carpeta {kind}: {folder}")
        try:
            files = [f for f in folder.iterdir() if f.is_file()]
            files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        except OSError:
            files = []
        for f in files:
            st = f.stat()
            row = (f.name, datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M"),
                   f"{st.st_size / 1024:.1f} KB")
            if _matches(self.filter.get(), row):
                self.tree.insert("", "end", iid=str(f), values=row)
        if sel and self.tree.exists(sel):
            self.tree.selection_set(sel)

    def open_folder(self):
        chosen = filedialog.askdirectory(parent=self, initialdir=self.view_dir(), mustexist=True,
                                         title="Abrir carpeta de backups")
        if chosen:
            self.app.backup_view = Path(chosen)
            self.refresh()

    def go_default(self):
        self.app.backup_view = None
        self.refresh()

    def create(self):
        path = filedialog.asksaveasfilename(parent=self, initialdir=self.view_dir(),
                                            initialfile=backup.default_name(), defaultextension=".zip",
                                            filetypes=[("Backup PowerPulse", "*.zip")])
        if not path:
            return
        try:
            counts = backup.create(path, self.history.get())
        except OSError as exc:
            return messagebox.showerror("Backup", f"No se pudo crear el backup:\n{exc}", parent=self)
        self.refresh()
        messagebox.showinfo("Backup", f"Backup creado: {counts['schedules']} programaciones.\n{path}", parent=self)

    def restore_selected(self):
        path = _selected_id(self.tree)
        if not path:
            return messagebox.showinfo("Backup", "Seleccione un backup de la lista.", parent=self)
        self._restore(path)

    def restore_file(self):
        path = filedialog.askopenfilename(parent=self, initialdir=self.view_dir(),
                                          filetypes=[("Backup PowerPulse", "*.zip")])
        if path:
            self._restore(path)

    def _restore(self, path: str):
        app = self.app
        try:
            manifest, _ = backup.read_backup(path)
        except ValueError as exc:
            return messagebox.showerror("Backup", str(exc), parent=self)
        if not messagebox.askyesno(
                "Restaurar", f"Se reemplazarán la configuración y todas las programaciones actuales por las del "
                             f"backup del {manifest.get('created_at', '?').replace('T', ' ')}.\n"
                             "Antes se guardará una copia del estado actual.\n\n¿Continuar?",
                parent=self, default="no"):
            return
        try:
            result = backup.restore(path)
        except (ValueError, OSError) as exc:
            return messagebox.showerror("Backup", f"No se pudo restaurar:\n{exc}", parent=self)
        app.reload_settings()
        messagebox.showinfo("Backup", f"Restauración completada: {result['schedules']} programaciones.",
                            parent=app)

    def delete(self):
        path = _selected_id(self.tree)
        if not path:
            return messagebox.showinfo("Backup", "Seleccione un backup de la lista.", parent=self)
        if messagebox.askyesno("Eliminar", f"¿Eliminar el backup '{Path(path).name}'?", parent=self):
            Path(path).unlink(missing_ok=True)
            store.log.info("BACKUP eliminado: %s", path)
            self.refresh()


class ReportsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=12)
        self.scope = tk.StringVar(value="Programaciones")
        self.period = tk.StringVar(value="Diario")
        self.ref = tk.StringVar(value=fmt_date(date.today()))
        self.end = tk.StringVar(value=fmt_date(date.today()))
        self.fmt = tk.StringVar(value="XLSX")
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *_: self._show())
        self.cache = None
        form = ttk.Frame(self)
        form.pack(fill="x")
        rows = (("Ámbito:", ttk.Combobox(form, textvariable=self.scope, state="readonly",
                                         values=["Programaciones"])),
                ("Periodo:", ttk.Combobox(form, textvariable=self.period, state="readonly",
                                          values=["Diario", "Mensual", "Anual", "Rango de fechas"])),
                ("Fecha de referencia / desde:", DatePicker(form, self.ref)),
                ("Hasta (solo rango):", DatePicker(form, self.end)),
                ("Formato:", ttk.Combobox(form, textvariable=self.fmt, state="readonly",
                                          values=["XLSX", "PDF"])))
        for i, (text, w) in enumerate(rows):
            ttk.Label(form, text=text).grid(row=i, column=0, sticky="w", pady=4)
            w.grid(row=i, column=1, sticky="w", padx=8)
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=8)
        ttk.Button(bar, text="Vista previa", command=self.preview).pack(side="left")
        ttk.Button(bar, text="Generar informe", command=self.generate).pack(side="left", padx=4)
        _search_box(bar, self.filter)
        ttk.Label(self, text=f"Se exportan las filas visibles. Carpeta por defecto: {paths.REPORTS_DIR}",
                  foreground="gray").pack(anchor="w")
        self.holder = ttk.Frame(self)
        self.holder.pack(fill="both", expand=True, pady=(6, 0))

    def _build(self):
        scope = "schedules"
        period = {"Diario": "day", "Mensual": "month", "Anual": "year",
                  "Rango de fechas": "range"}[self.period.get()]
        try:
            ref = parse_user_date(self.ref.get())
            end = parse_user_date(self.end.get()) if period == "range" else None
            if end and end < ref:
                raise ValueError("La fecha final no puede ser anterior a la inicial")
        except ValueError as exc:
            messagebox.showerror("Informe", str(exc), parent=self)
            return None
        return scope, period, reports.build_report(scope, period, ref, end)

    def _visible_rows(self):
        return [r for r in self.cache[2][2] if _matches(self.filter.get(), r)]

    def preview(self):
        built = self._build()
        if built:
            self.cache = built
            for w in self.holder.winfo_children():
                w.destroy()
            self.tree = _make_tree(self.holder, {h: 110 for h in built[2][1]})
            self._show()

    def _show(self):
        if not self.cache:
            return
        self.tree.delete(*self.tree.get_children())
        for r in self._visible_rows():
            self.tree.insert("", "end", values=r)

    def generate(self):
        self.preview()
        if not self.cache:
            return
        scope, period, (title, headers, _) = self.cache
        rows = self._visible_rows()
        ext = self.fmt.get().lower()
        name = f"PowerPulse_{scope}_{period}_{datetime.now():%Y%m%d_%H%M%S}.{ext}"
        path = filedialog.asksaveasfilename(parent=self, initialdir=paths.REPORTS_DIR, initialfile=name,
                                            defaultextension=f".{ext}", filetypes=[(ext.upper(), f"*.{ext}")])
        if not path:
            return
        try:
            (reports.write_xlsx if ext == "xlsx" else reports.write_pdf)(path, title, headers, rows)
        except OSError as exc:
            return messagebox.showerror("Informe", f"No se pudo escribir el fichero:\n{exc}", parent=self)
        store.log.info("INFORME generado: %s (%d filas)", path, len(rows))
        if messagebox.askyesno("Informe", f"Informe generado ({len(rows)} filas).\n¿Abrirlo ahora?", parent=self):
            os.startfile(path)

    def refresh(self):
        pass


class LogTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=8)
        self.log_dir = tk.StringVar(value="5PM")
        self.log_directories = {
            "5PM": paths.CALENDAR_LOG_DIR,
            "7AM": paths.CALENDAR_7AM_LOG_DIR,
        }
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="Actualizar", command=app.refresh_and_cleanup).pack(side="left")
        ttk.Button(bar, text="Abrir carpeta de logs", command=self.open_folder).pack(side="left", padx=4)
        ttk.Label(bar, text="Programación:").pack(side="left", padx=(12, 4))
        ttk.Combobox(bar, textvariable=self.log_dir, values=list(self.log_directories),
                     state="readonly", width=8).pack(side="left")
        self.log_path = ttk.Label(self)
        self.log_path.pack(anchor="w")
        self.log_dir.trace_add("write", lambda *_: self.refresh())
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *_: self.show_file())
        _search_box(bar, self.filter)
        self.files = _make_tree(self, {"Archivo": 250})
        self.files.master.pack_configure(fill="x", expand=False)
        self.files.configure(height=6)
        self.files.bind("<<TreeviewSelect>>", lambda _: self.show_file())
        p = theme.pal()
        self.text = tk.Text(self, wrap="none", state="disabled", font=("Consolas", 9), bg=p["field"],
                            fg=p["fg"], insertbackground=p["fg"], highlightthickness=0, borderwidth=0)
        sb = ttk.Scrollbar(self, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True)

    def open_folder(self):
        log_dir = self.log_directories[self.log_dir.get()]
        try:
            os.startfile(log_dir)
        except OSError as exc:
            store.log.error("No se pudo abrir la carpeta de logs del calendario: %s", exc)
            messagebox.showerror("Logs", f"No se pudo abrir la carpeta:\n{exc}", parent=self)

    def _show_text(self, text: str):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", text)
        self.text.config(state="disabled")

    def refresh(self):
        log_dir = self.log_directories[self.log_dir.get()]
        self.log_path.config(text=str(log_dir))
        selected = _selected_id(self.files)
        try:
            files = sorted((p for p in log_dir.iterdir() if p.is_file()),
                           key=lambda p: p.name.casefold(), reverse=True)
        except FileNotFoundError:
            files = []
            error = f"La carpeta de logs no existe: {log_dir}"
        except OSError as exc:
            files = []
            error = f"No se pudieron leer los logs: {exc}"
            store.log.error(error)
        else:
            error = ""
        self.files.delete(*self.files.get_children())
        for path in files:
            self.files.insert("", "end", iid=str(path), values=(path.name,))
        if selected and self.files.exists(selected):
            self.files.selection_set(selected)
        elif files:
            self.files.selection_set(str(files[0]))
        if error:
            self._show_text(error)
        elif not files:
            self._show_text("No hay archivos de logs.")
        else:
            self.show_file()

    def show_file(self):
        selected = _selected_id(self.files)
        if not selected:
            return
        try:
            text = Path(selected).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            store.log.error("No se pudo leer el log %s: %s", selected, exc)
            self._show_text(f"No se pudo leer el archivo:\n{exc}")
            return
        lines = [line for line in text.splitlines() if _matches(self.filter.get(), [line])]
        self._show_text("\n".join(lines))


ABOUT_TEXT = f"""PowerPulse v{__version__}

PowerPulse es una aplicación para Windows 11 que gestiona programaciones y genera archivos diarios de equipos de la red local (LAN).

ORIGEN DE LOS EQUIPOS
Las IPs de los equipos y sus asignaciones (usuarios) se leen, en modo solo lectura, del fichero assignments.json de MapPulse. Todas las programaciones se guardan en los ficheros propios de PowerPulse.

PROGRAMACIONES
Programaciones 5PM y Programaciones 7AM mantienen listas independientes y generan TXT en regs y regs7, respectivamente. Cada programación puede dirigirse a un equipo individual o a todos los equipos de MapPulse con exclusiones. La opción de todos incluye automáticamente los nuevos equipos cuando PowerPulse está abierto y detecta cambios; con la aplicación cerrada se actualiza al volver a abrirla. Los informes de programaciones activas reflejan los equipos actuales, no un registro histórico de cambios en MapPulse. Las programaciones pueden ser únicas, diarias, semanales, mensuales o un rango de días.
Se puede añadir una etiqueta personalizada opcional a cada programación; no modifica la asignación del equipo en MapPulse ni el contenido de los TXT.

CALENDARIO
Vista diaria, mensual y anual de toda la programación. Al seleccionar un día se muestran sus programaciones y se pueden crear, editar o borrar desde ahí.

HISTÓRICO
Muestra todas las programaciones registradas, incluidas las pendientes y las eliminadas manualmente. Al iniciar o actualizar, las series cuya última fecha y hora han pasado se archivan y siguen incluidas en los backups. Esto no confirma que se hayan ejecutado.

ESTADÍSTICAS
Equipos indicados por el calendario (IP, asignación y fecha) en el rango elegido.

BACKUP
Copia de la configuración y las programaciones en un .zip, y su posterior restauración. Antes de restaurar se guarda una copia automática del estado actual.

INFORMES Y LOGS
Informes en XLSX y PDF de las programaciones, en periodo diario, mensual o anual. Logs permite consultar las carpetas {paths.CALENDAR_LOG_DIR} (5PM) y {paths.CALENDAR_7AM_LOG_DIR} (7AM). El log indica que el proceso externo registró el día, no que todos los apagados se hayan realizado correctamente.

ARCHIVOS PARA EL CALENDARIO EXTERNO
Cada pestaña genera archivos diarios YYYY-MM-DD.txt en su carpeta: {schedule_txt.OUTPUT_DIR} para 5PM y {schedule_txt.OUTPUT_DIR_7AM} para 7AM. Cada línea contiene un equipo seleccionado con el prefijo UNC (\\\\IP). Las nuevas programaciones generan un archivo cada día desde la fecha inicial hasta la fecha final opcional, a las 17:00 o 07:00 según la pestaña; si no se indica fecha final, se generan a 365 días vista. Al editar también se pueden mantener o cambiar repeticiones existentes. Se incluyen solo programaciones activas; al iniciar o actualizar se eliminan los TXT generados para fechas pasadas y se conservan en el TXT de hoy solo los equipos con horarios pendientes, sin exigir un log. PowerPulse solo crea estos archivos: no ejecuta apagados ni el .bat externo.

BUSCADOR
Las pestañas con listas disponen de un buscador que filtra por cualquier texto visible.

TEMA
El tema claro u oscuro se elige en Archivo > Tema y se recuerda al cerrar.

"""


class AboutTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=8)
        self._content = ""
        p = theme.pal()
        self.text = tk.Text(self, wrap="word", font=("Segoe UI", 10), bg=p["field"], fg=p["fg"],
                            highlightthickness=0, borderwidth=0, padx=12, pady=8, state="disabled")
        self.text.pack(fill="both", expand=True)
        self.refresh()

    def refresh(self):
        content = ABOUT_TEXT + f"\nCreado por sagazmaker@gmail.com - {date.today():%d/%m/%Y}\n"
        if content == self._content:
            return
        self._content = content
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", content)
        self.text.config(state="disabled")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"PowerPulse v{__version__}")
        self.geometry("1150x720")
        try:
            self.iconbitmap(paths.ICON_FILE)
        except tk.TclError:
            pass
        store.setup_logging()
        store.log.info("PowerPulse iniciado")
        try:
            paths.ensure_calendar_directories()
        except OSError as exc:
            store.log.exception("No se pudieron crear las carpetas del calendario externo")
            messagebox.showerror(
                "Carpetas del calendario",
                f"No se pudieron crear las carpetas necesarias en {paths.CALENDAR_DIR}:\n{exc}",
                parent=self)
            self.destroy()
            raise RuntimeError("No se pudieron crear las carpetas del calendario externo.") from exc
        missing_scripts = paths.missing_calendar_scripts()
        if missing_scripts:
            missing = "\n".join(str(paths.CALENDAR_DIR / name) for name in missing_scripts)
            store.log.warning("Faltan scripts del calendario externo: %s", ", ".join(missing_scripts))
            messagebox.showinfo(
                "Scripts del calendario",
                "No se encontraron estos scripts en la carpeta del calendario:\n"
                f"{missing}\n\nPowerPulse no los copia ni los ejecuta.",
                parent=self)
        self.settings = store.load_settings()
        theme.apply(self, self.settings["theme"])
        ok, detail = background.uninstall()
        if not ok:
            store.log.error("No se pudieron eliminar las tareas de apagado anteriores: %s", detail)
            messagebox.showerror(
                "Tareas anteriores",
                f"No se pudieron eliminar las tareas de apagado anteriores:\n{detail}",
                parent=self)
            self.destroy()
            raise RuntimeError("No se pudieron eliminar las tareas de apagado anteriores.")

        self.menubar = ttk.Frame(self)
        self.menubar.pack(side="top", fill="x")
        self.theme_var = tk.StringVar(value=self.settings["theme"])
        self.top_var = tk.BooleanVar(value=self.settings["always_on_top"])
        self.backup_view: Path | None = None
        self._txt_count = 0
        self._txt_generation_date = date.today()
        self._txt_assignments_signature = None
        self.attributes("-topmost", self.top_var.get())
        self.build_menu()

        self.status = tk.StringVar()
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w").pack(side="bottom", fill="x")
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self.build_tabs()
        self.nb.bind("<<NotebookTabChanged>>", self._tab_changed)
        self.refresh_and_cleanup()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(15000, self.auto_refresh)
        self.update()
        theme.style_titlebar(self)

    def build_menu(self):
        for w in self.menubar.winfo_children():
            w.destroy()
        p = theme.pal()
        mb = ttk.Menubutton(self.menubar, text="Archivo")
        opts = dict(tearoff=False, bg=p["field"], fg=p["fg"], activebackground=p["sel"],
                    activeforeground=p["selfg"], selectcolor=p["fg"], borderwidth=0)
        menu = tk.Menu(mb, **opts)
        menu.add_command(label="Abrir carpeta de datos", command=lambda: os.startfile(paths.DATA_DIR))
        menu.add_command(label="Carpeta de backups por defecto...", command=self.choose_backup_folder)
        menu.add_command(label="Restablecer carpeta de backups (Copia)", command=self.reset_backup_folder)
        menu.add_checkbutton(label="Mantener ventana en primer plano", variable=self.top_var,
                             command=self.toggle_top)
        theme_menu = tk.Menu(menu, **opts)
        for label, value in (("Claro", theme.LIGHT), ("Oscuro", theme.DARK)):
            theme_menu.add_radiobutton(label=label, value=value, variable=self.theme_var,
                                       command=self.set_theme)
        menu.add_cascade(label="Tema", menu=theme_menu)
        menu.add_separator()
        menu.add_command(label="Salir", command=self.on_close)
        mb.configure(menu=menu)
        mb.pack(side="left", padx=4, pady=2)

    def _tab_changed(self, _=None):
        if self.nb.tabs():
            tab = self.tabs.get(self.nb.tab(self.nb.select(), "text"))
            if tab:
                tab.refresh()

    def toggle_top(self):
        self.settings["always_on_top"] = self.top_var.get()
        store.save_settings(self.settings)
        self.attributes("-topmost", self.top_var.get())

    def choose_backup_folder(self):
        chosen = filedialog.askdirectory(parent=self, initialdir=backup.backup_dir(), mustexist=True,
                                         title="Carpeta de backups por defecto")
        if chosen:
            self._set_backup_default(Path(chosen))

    def reset_backup_folder(self):
        self._set_backup_default(None)

    def _set_backup_default(self, folder):
        backup.set_backup_dir(folder)
        self.settings = store.load_settings()
        self.backup_view = None
        self.tabs["Backup"].refresh()

    def reload_settings(self):
        self.settings = store.load_settings()
        self.top_var.set(self.settings["always_on_top"])
        self.attributes("-topmost", self.top_var.get())
        self.theme_var.set(self.settings["theme"])
        theme.apply(self, self.settings["theme"])
        self.build_menu()
        self.build_tabs()
        self.generate_schedule_txts(self, notify=False)
        self.refresh_all()

    def set_theme(self):
        self.settings["theme"] = self.theme_var.get()
        store.save_settings(self.settings)
        theme.apply(self, self.settings["theme"])
        self.build_menu()
        self.build_tabs()
        self.refresh_all()

    def build_tabs(self):
        current = self.nb.index("current") if self.nb.tabs() else 0
        for t in self.nb.tabs():
            self.nb.nametowidget(t).destroy()
        self.tabs = {}
        for name, cls in (("Programaciones 5PM", ScheduleTab),
                          ("Programaciones 7AM", lambda parent, app: ScheduleTab(parent, app, "7am")),
                          ("Calendario", CalendarTab),
                          ("Histórico", ArchiveTab), ("Estadísticas", StatsTab),
                          ("Informes", ReportsTab),
                          ("Backup", BackupTab), ("Logs", LogTab),
                          ("About", AboutTab)):
            tab = cls(self.nb, self)
            self.nb.add(tab, text=name)
            self.tabs[name] = tab
        self.nb.select(current)

    def update_status(self):
        self.status.set(f" TXT generados: {self._txt_count} | Carpetas: "
                        f"{schedule_txt.OUTPUT_DIR} / {schedule_txt.OUTPUT_DIR_7AM} | "
                        f"Equipos MapPulse: {len(store.load_assignments())}")

    def generate_schedule_txts(self, parent, notify: bool = False, *,
                               now: datetime | None = None, cleanup_elapsed: bool = False,
                               profile: str | None = None):
        signature = self._assignments_signature()
        profiles = (profile,) if profile else ("5pm", "7am")
        counts = {}
        for current_profile in profiles:
            try:
                counts[current_profile] = schedule_txt.generate(
                    now=now, cleanup_elapsed=cleanup_elapsed, profile=current_profile)
            except (OSError, ValueError, KeyError) as exc:
                self._txt_assignments_signature = signature
                store.log.exception("No se pudieron generar los TXT diarios del perfil %s",
                                    current_profile)
                messagebox.showerror("Generar TXT", f"No se pudieron generar los archivos:\n{exc}",
                                     parent=parent)
                return False
        self._txt_count = sum(counts.values())
        self._txt_generation_date = date.today()
        self._txt_assignments_signature = signature
        store.log.info("Generación de TXT finalizada por perfil: %s", counts)
        self.update_status()
        if notify:
            destinations = {
                "5pm": schedule_txt.OUTPUT_DIR,
                "7am": schedule_txt.OUTPUT_DIR_7AM,
            }
            detail = "\n".join(f"{count} archivo(s) en {destinations[key]}"
                               for key, count in counts.items())
            messagebox.showinfo("Generar TXT", f"Se generaron:\n{detail}", parent=parent)
        return True

    def refresh_all(self):
        self.update_status()
        for tab in self.tabs.values():
            tab.refresh()

    def refresh_and_cleanup(self):
        now = datetime.now()
        if not self.generate_schedule_txts(self, notify=False, now=now, cleanup_elapsed=True):
            self.refresh_all()
            return
        try:
            archive.archive_finished(now)
        except (OSError, ValueError, KeyError) as exc:
            store.log.exception("No se pudieron archivar las programaciones")
            messagebox.showerror("Actualizar", f"No se pudieron archivar las programaciones:\n{exc}", parent=self)
        self.refresh_all()

    @staticmethod
    def _assignments_signature():
        if not any(s.get("enabled", True) and s.get("target_mode") == "all"
                   for s in store.schedules.all()):
            return None
        try:
            return hashlib.sha256(paths.ASSIGNMENTS_FILE.read_bytes()).hexdigest()
        except OSError as exc:
            return f"error:{exc}"

    def auto_refresh(self):
        self.refresh_all()
        if (date.today() != self._txt_generation_date or
                self._assignments_signature() != self._txt_assignments_signature):
            self.generate_schedule_txts(self, notify=False)
        self.after(15000, self.auto_refresh)

    def on_close(self):
        store.log.info("PowerPulse cerrado")
        self.destroy()


def main():
    App().mainloop()
