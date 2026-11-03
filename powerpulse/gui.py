import calendar
import os
import threading
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, ttk

from . import __version__, archive, background, backup, paths, reports, store, theme
from . import dialogs as messagebox
from .executor import Scheduler, global_targets
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
        if selectmode == "multiple":
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
    """Campos de fecha/hora/repetición compartidos por programaciones y globales."""

    def __init__(self, parent, item: dict | None, default_date: date):
        super().__init__(parent)
        item = item or {}
        self.date = tk.StringVar(value=fmt_date(item.get("start_date") or default_date))
        self.time = tk.StringVar(value=item.get("time", "08:00"))
        self.repeat = tk.StringVar(value=REPEATS[item.get("repeat", "none")])
        self.until = tk.StringVar(value=fmt_date(item.get("until")))
        self.enabled = tk.BooleanVar(value=item.get("enabled", True))
        days = item.get("weekdays", [])
        self.wd = [tk.BooleanVar(value=i in days) for i in range(7)]

        ttk.Label(self, text="Fecha / desde:").grid(row=0, column=0, sticky="w", pady=2)
        DatePicker(self, self.date, 14).grid(row=0, column=1, sticky="w")
        self.until_lbl = ttk.Label(self)
        self.until_lbl.grid(row=0, column=2, sticky="w", padx=(12, 0))
        DatePicker(self, self.until, 14, allow_empty=True).grid(row=0, column=3, sticky="w")
        ttk.Label(self, text="Hora (HH:MM):").grid(row=1, column=0, sticky="w", pady=2)
        TimePicker(self, self.time).grid(row=1, column=1, sticky="w")
        ttk.Label(self, text="Repetición:").grid(row=1, column=2, sticky="w", padx=(12, 0))
        ttk.Combobox(self, textvariable=self.repeat, values=list(REPEATS.values()),
                     state="readonly", width=14).grid(row=1, column=3, sticky="w")
        self.repeat.trace_add("write", lambda *_: self._update_until_label())
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
    def __init__(self, parent, item: dict | None, default_date: date):
        super().__init__(parent, "Editar programación" if item else "Nueva programación")
        self.editing = item is not None
        ttk.Label(self.body, text="Equipo(s):").pack(anchor="w")
        self.picker = EquipmentPicker(self.body, "browse" if self.editing else "extended")
        self.picker.pack(fill="both", expand=True)
        if item:
            self.picker.select([item["ip"]])
        else:
            ttk.Label(self.body, text="Ctrl/Mayús para seleccionar varios equipos.",
                      foreground="gray").pack(anchor="w")
        self.timing = TimingForm(self.body, item, default_date)
        self.timing.pack(fill="x", pady=8)
        ttk.Label(self.body, text="Notas:").pack(anchor="w")
        self.notes = tk.StringVar(value=(item or {}).get("notes", ""))
        ttk.Entry(self.body, textvariable=self.notes).pack(fill="x")
        self.finish_layout()

    def collect(self):
        targets = self.picker.selected_assignments()
        if not targets:
            raise ValueError("Seleccione al menos un equipo")
        timing = self.timing.values()
        if archive.is_finished(timing):
            raise ValueError("La programación ya habría finalizado (fechas pasadas). Indique una fecha futura.")
        return {"targets": targets, "timing": timing,
                "notes": self.notes.get().strip()}


class GlobalDialog(_Dialog):
    def __init__(self, parent, item: dict | None, default_date: date):
        super().__init__(parent, "Editar global" if item else "Nueva programación global")
        ttk.Label(self.body, text="Nombre:").pack(anchor="w")
        self.name = tk.StringVar(value=(item or {}).get("name", ""))
        ttk.Entry(self.body, textvariable=self.name).pack(fill="x")
        self.timing = TimingForm(self.body, item, default_date)
        self.timing.pack(fill="x", pady=8)
        ttk.Label(self.body, text="Equipos EXCLUIDOS del apagado (clic para marcar/desmarcar):").pack(anchor="w")
        self.picker = EquipmentPicker(self.body, "multiple")
        self.picker.pack(fill="both", expand=True)
        self.picker.select((item or {}).get("excluded_ips", []))
        self.finish_layout()

    def collect(self):
        if not self.name.get().strip():
            raise ValueError("Indique un nombre")
        return {"name": self.name.get().strip(), "timing": self.timing.values(),
                "excluded_ips": sorted(self.picker.selected)}


def _crud_buttons(parent, app, new, edit, delete):
    bar = ttk.Frame(parent)
    bar.pack(fill="x", pady=(0, 6))
    ttk.Button(bar, text="Nuevo", command=new).pack(side="left")
    ttk.Button(bar, text="Editar", command=edit).pack(side="left", padx=4)
    ttk.Button(bar, text="Borrar", command=delete).pack(side="left")
    ttk.Button(bar, text="Actualizar", command=app.refresh_all).pack(side="left", padx=4)
    return bar


def schedule_new(app, parent, default_date: date):
    dlg = ScheduleDialog(parent, None, default_date)
    parent.wait_window(dlg)
    if dlg.result:
        for a in dlg.result["targets"]:
            store.schedules.add({"ip": a["ip"], "label": a.get("label", ""),
                                 "notes": dlg.result["notes"], **dlg.result["timing"]})
        app.refresh_all()


def schedule_edit(app, parent, item_id: str | None):
    item = item_id and store.schedules.get(item_id)
    if not item:
        messagebox.showinfo("PowerPulse", "Seleccione una programación.", parent=parent)
        return
    dlg = ScheduleDialog(parent, item, date.today())
    parent.wait_window(dlg)
    if dlg.result:
        a = dlg.result["targets"][0]
        store.schedules.update(item_id, {"ip": a["ip"], "label": a.get("label", ""),
                                         "notes": dlg.result["notes"], **dlg.result["timing"]})
        app.refresh_all()


def schedule_delete(app, parent, item_id: str | None):
    item = item_id and store.schedules.get(item_id)
    if not item:
        messagebox.showinfo("PowerPulse", "Seleccione una programación.", parent=parent)
        return
    extra = "\nSe eliminará toda la serie repetida." if item["repeat"] != "none" else ""
    if messagebox.askyesno("Borrar", f"¿Borrar la programación de {item['ip']}?{extra}", parent=parent):
        store.schedules.delete(item_id)
        app.refresh_all()


class ScheduleTab(ttk.Frame):
    COLS = {"Fecha": 90, "Hora": 60, "IP": 120, "Etiqueta": 180, "Repetición": 90,
            "Días": 140, "Hasta": 90, "Activa": 60, "Estado": 110, "Notas": 200}

    def __init__(self, parent, app):
        super().__init__(parent, padding=8)
        self.app = app
        bar = _crud_buttons(self, app, lambda: schedule_new(app, self, date.today()),
                            lambda: schedule_edit(app, self, _selected_id(self.tree)),
                            lambda: schedule_delete(app, self, _selected_id(self.tree)))
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *_: self.refresh())
        _search_box(bar, self.filter)
        self.tree = _make_tree(self, self.COLS)
        self.tree.bind("<Double-1>", lambda e: schedule_edit(app, self, _selected_id(self.tree)))

    def refresh(self):
        sel = _selected_id(self.tree)
        self.tree.delete(*self.tree.get_children())
        hist = store.history.status_map()
        needle = self.filter.get()
        for s in sorted(store.schedules.all(), key=lambda s: (s["start_date"], s["time"])):
            hits = [k.split("|")[1] for k in hist if k.startswith(s["id"])]
            status = hist[f"{s['id']}|{max(hits)}"]["status"] if hits else (
                "Pendiente" if s.get("enabled", True) else "Desactivada")
            row = (fmt_date(s["start_date"]), s["time"], s["ip"], s.get("label", ""),
                   REPEATS[s["repeat"]], weekdays_text(s), fmt_date(s.get("until")),
                   "Sí" if s.get("enabled", True) else "No", status, s.get("notes", ""))
            if not _matches(needle, row):
                continue
            self.tree.insert("", "end", iid=s["id"], values=row)
        if sel and self.tree.exists(sel):
            self.tree.selection_set(sel)


class GlobalTab(ttk.Frame):
    COLS = {"Nombre": 200, "Inicio": 90, "Hora": 60, "Repetición": 90, "Días": 140,
            "Hasta": 90, "Activa": 60, "Equipos": 70, "Excluidos": 300}

    def __init__(self, parent, app):
        super().__init__(parent, padding=8)
        self.app = app
        bar = _crud_buttons(self, app, self.new, self.edit, self.delete)
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *_: self.refresh())
        _search_box(bar, self.filter)
        self.tree = _make_tree(self, self.COLS)
        self.tree.bind("<Double-1>", lambda e: self.edit())

    def new(self):
        dlg = GlobalDialog(self, None, date.today())
        self.wait_window(dlg)
        if dlg.result:
            r = dlg.result
            store.globals_.add({"name": r["name"], "excluded_ips": r["excluded_ips"], **r["timing"]})
            self.app.refresh_all()

    def edit(self):
        gid = _selected_id(self.tree)
        item = gid and store.globals_.get(gid)
        if not item:
            return messagebox.showinfo("PowerPulse", "Seleccione una programación global.", parent=self)
        dlg = GlobalDialog(self, item, date.today())
        self.wait_window(dlg)
        if dlg.result:
            r = dlg.result
            store.globals_.update(gid, {"name": r["name"], "excluded_ips": r["excluded_ips"], **r["timing"]})
            self.app.refresh_all()

    def delete(self):
        gid = _selected_id(self.tree)
        item = gid and store.globals_.get(gid)
        if not item:
            return messagebox.showinfo("PowerPulse", "Seleccione una programación global.", parent=self)
        if messagebox.askyesno("Borrar", f"¿Borrar la programación global '{item['name']}'?", parent=self):
            store.globals_.delete(gid)
            self.app.refresh_all()

    def refresh(self):
        sel = _selected_id(self.tree)
        self.tree.delete(*self.tree.get_children())
        for g in store.globals_.all():
            row = (
                g["name"], fmt_date(g["start_date"]), g["time"], REPEATS[g["repeat"]],
                weekdays_text(g), fmt_date(g.get("until")), "Sí" if g.get("enabled", True) else "No",
                len(global_targets(g)), ", ".join(g.get("excluded_ips", [])))
            if _matches(self.filter.get(), row):
                self.tree.insert("", "end", iid=g["id"], values=row)
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
        self.tree = _make_tree(self.panel, {"Hora": 60, "IP": 120, "Etiqueta": 200,
                                            "Repetición": 90, "Estado": 110, "Notas": 250})
        self.tree.bind("<Double-1>", lambda e: schedule_edit(app, self, _selected_id(self.tree)))
        self.stree = _make_tree(self.panel, {"Fecha": 90, "Hora": 60, "IP": 110, "Etiqueta": 170,
                                             "Repetición": 90, "Desde": 90, "Hasta": 90, "Activa": 55,
                                             "Estado": 100, "Notas": 200})
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
                s["time"], s["ip"], s.get("label", ""), REPEATS[s["repeat"]],
                status_for(s, self.sel, hist), s.get("notes", "")))

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
            row = (fmt_date(focus), s["time"], s["ip"], s.get("label", ""), REPEATS[s["repeat"]],
                   fmt_date(s["start_date"]), fmt_date(s.get("until")), "Sí" if s.get("enabled", True) else "No",
                   status_for(s, focus, hist), s.get("notes", ""))
            if _matches(needle, row) or (day and dates_for(s, day, day)):
                found.append((focus, s["time"], s["id"], row))
        for _, _, sid, row in sorted(found):
            self.stree.insert("", "end", iid=sid, values=row)
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
    HEADERS = ["Archivada", "Última fecha", "Hora", "IP", "Etiqueta", "Repetición", "Desde", "Hasta",
               "Estado final", "Notas"]

    def __init__(self, parent, app):
        super().__init__(parent, padding=8)
        self.app = app
        self.rows: list[list[str]] = []
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="Eliminar", command=self.delete).pack(side="left")
        ttk.Button(bar, text="Exportar PDF/XLSX...", command=self.export).pack(side="left", padx=4)
        ttk.Button(bar, text="Actualizar", command=app.refresh_all).pack(side="left")
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
        items = sorted(store.archive.all(), key=lambda a: a.get("archived_at", ""), reverse=True)
        for a in items:
            row = [a.get("archived_at", "")[:16].replace("T", " "), fmt_date(a.get("last_date")), a["time"],
                   a["ip"], a.get("label", ""), REPEATS[a["repeat"]], fmt_date(a["start_date"]),
                   fmt_date(a.get("until")), a.get("final_status", ""), a.get("notes", "")]
            if _matches(self.filter.get(), row):
                self.rows.append(row)
                self.tree.insert("", "end", iid=a["id"], values=row)
        self.summary.config(text=f"{len(self.rows)} de {len(items)} programaciones finalizadas. "
                                 "Se archivan solas al terminar y dejan de verse en Programaciones y Calendario.")
        if sel and self.tree.exists(sel):
            self.tree.selection_set(sel)

    def delete(self):
        item_id = _selected_id(self.tree)
        if not item_id:
            return messagebox.showinfo("Histórico", "Seleccione una programación del histórico.", parent=self)
        if messagebox.askyesno("Eliminar", "¿Eliminar definitivamente esta programación del histórico?", parent=self):
            store.archive.delete(item_id)
            self.app.refresh_all()

    def export(self):
        export_table(self, "Histórico de programaciones finalizadas", self.HEADERS, self.rows, "historico")


class StatsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=8)
        self.d0 = date.today()
        self.d1 = date.today() + timedelta(days=30)
        self.gmap: dict[str, str] = {}
        self.gdata = self.cdata = None

        gf = ttk.LabelFrame(self, text="Global: equipos que se apagan y excluidos", padding=6)
        gf.pack(fill="both", expand=True)
        bar = ttk.Frame(gf)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(bar, text="Programación global:").pack(side="left")
        self.gsel = tk.StringVar()
        self.gcombo = ttk.Combobox(bar, textvariable=self.gsel, state="readonly", width=36)
        self.gcombo.pack(side="left", padx=4)
        self.gcombo.bind("<<ComboboxSelected>>", lambda e: self.refresh_global())
        self.gsummary = ttk.Label(bar, font=("Segoe UI", 9, "bold"))
        self.gsummary.pack(side="left", padx=12)
        ttk.Button(bar, text="Exportar PDF/XLSX...",
                   command=lambda: self._export(self.gdata, "estadisticas_global")).pack(side="left")
        self.gfilter = tk.StringVar()
        self.gfilter.trace_add("write", lambda *_: self.refresh_global())
        _search_box(bar, self.gfilter)
        self.gtree = _make_tree(gf, {"IP": 130, "Asignación": 260, "Estado": 120})
        self.gtree.tag_configure("off", foreground="#2e9e5b")
        self.gtree.tag_configure("excl", foreground="#e5534b")

        cf = ttk.LabelFrame(self, text="Calendario: equipos que se apagan", padding=6)
        cf.pack(fill="both", expand=True, pady=(8, 0))
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

    def refresh_global(self):
        globs = store.globals_.all()
        labels, ids = [], []
        for g in globs:
            label = f"{g['name']} ({g['time']}, {REPEATS[g['repeat']]})"
            while label in labels:
                label += "'"
            labels.append(label)
            ids.append(g["id"])
        self.gmap = dict(zip(labels, ids))
        self.gcombo["values"] = labels
        if self.gsel.get() not in self.gmap:
            self.gsel.set(labels[0] if labels else "")
        self.gtree.delete(*self.gtree.get_children())
        g = next((g for g in globs if g["id"] == self.gmap.get(self.gsel.get())), None)
        if not g:
            self.gdata = None
            self.gsummary.config(text="No hay programaciones globales")
            return
        excluded = set(g.get("excluded_ips", []))
        assignments = store.load_assignments()
        off = sum(a["ip"] not in excluded for a in assignments)
        summary = (f"Total: {len(assignments)} | Se apagan: {off} | "
                   f"Excluidos: {len(assignments) - off}")
        self.gsummary.config(text=summary)
        rows = [(a["ip"], a.get("label", ""), "Excluido" if a["ip"] in excluded else "Se apaga")
                for a in assignments]
        rows = [r for r in rows if _matches(self.gfilter.get(), r)]
        for r in rows:
            self.gtree.insert("", "end", values=r, tags=("excl" if r[2] == "Excluido" else "off",))
        self.gdata = (f"Estadísticas Global: {self.gsel.get()} - {summary}",
                      ["IP", "Asignación", "Estado"], [list(r) for r in rows])

    def refresh_calendar(self):
        assign = {a["ip"]: a.get("label", "") for a in store.load_assignments()}
        active = [s for s in store.schedules.all() + archive.as_schedules() if s.get("enabled", True)]
        rows = [(s["ip"], assign.get(s["ip"]) or s.get("label", ""), fmt_date(d), s["time"],
                 REPEATS[s["repeat"]])
                for d, items in sorted(in_range(active, self.d0, self.d1).items()) for s in items]
        summary = (f"{len(rows)} apagados programados | "
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
        self.refresh_global()
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
        ttk.Label(self, text="El backup (.zip) contiene la configuración, las programaciones y las globales. "
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
        messagebox.showinfo("Backup", f"Backup creado: {counts['schedules']} programaciones y "
                                      f"{counts['global']} globales.\n{path}", parent=self)

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
        messagebox.showinfo("Backup", f"Restauración completada: {result['schedules']} programaciones y "
                                      f"{result['global']} globales.", parent=app)

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
                                         values=["Programaciones", "Global"])),
                ("Periodo:", ttk.Combobox(form, textvariable=self.period, state="readonly",
                                          values=["Diario", "Mensual", "Anual", "Rango de fechas",
                                                  "Definiciones (solo Global)"])),
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
        scope = "global" if self.scope.get() == "Global" else "schedules"
        period = {"Diario": "day", "Mensual": "month", "Anual": "year",
                  "Rango de fechas": "range"}.get(self.period.get(), "all")
        if period == "all" and scope != "global":
            messagebox.showerror("Informe", "Las definiciones solo aplican al ámbito Global.", parent=self)
            return None
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
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="Actualizar", command=self.refresh).pack(side="left")
        ttk.Button(bar, text="Abrir carpeta de logs", command=lambda: os.startfile(paths.LOG_DIR)).pack(side="left", padx=4)
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *_: self.refresh())
        _search_box(bar, self.filter)
        p = theme.pal()
        self.text = tk.Text(self, wrap="none", state="disabled", font=("Consolas", 9), bg=p["field"],
                            fg=p["fg"], insertbackground=p["fg"], highlightthickness=0, borderwidth=0)
        sb = ttk.Scrollbar(self, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True)

    def refresh(self):
        lines: list[str] = []
        try:
            for f in reversed(store.log_files()):
                lines = f.read_text(encoding="utf-8", errors="replace").splitlines() + lines
                if len(lines) >= 5000:
                    break
        except OSError:
            pass
        lines = [l for l in lines if _matches(self.filter.get(), [l])][-1000:]
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", "\n".join(lines))
        self.text.see("end")
        self.text.config(state="disabled")


ABOUT_TEXT = f"""PowerPulse v{__version__}

PowerPulse es una aplicación para Windows 11 que programa y gestiona el apagado de equipos de la red local (LAN).

ORIGEN DE LOS EQUIPOS
Las IPs de los equipos y sus asignaciones (usuarios) se leen, en modo solo lectura, del fichero assignments.json de MapPulse. Todas las programaciones se guardan en los ficheros propios de PowerPulse.

PROGRAMACIONES
Panel CRUD para crear, ver, editar, borrar y actualizar programaciones por equipo. Cada una puede ser única, diaria, semanal (con días a elegir), mensual o un rango de días (desde/hasta), con fecha final opcional. Al crear se pueden elegir varios equipos a la vez.

CALENDARIO
Vista diaria, mensual y anual de toda la programación. Al seleccionar un día se muestran sus programaciones y se pueden crear, editar o borrar desde ahí.

GLOBAL
Apagados para todos los equipos con posibilidad de excluir los que se indiquen. Tiene su propio fichero JSON y su propio CRUD, y es independiente del calendario.

HISTÓRICO
Las programaciones del calendario que han finalizado por completo (fecha pasada y sin repeticiones pendientes) se archivan automáticamente en el histórico y dejan de aparecer en Programaciones y Calendario. Siguen contando en informes y estadísticas de fechas pasadas, y se incluyen en los backups.

ESTADÍSTICAS
Equipos que se apagan y excluidos en cada programación global, y equipos que se apagan según el calendario (IP, asignación y fecha) en el rango elegido.

BACKUP
Copia de la configuración, las programaciones y las globales en un .zip, y su posterior restauración. Antes de restaurar se guarda una copia automática del estado actual.

INFORMES Y LOGS
Informes en XLSX y PDF de las programaciones y de las globales, en periodo diario, mensual o anual. La aplicación genera logs automáticamente (altas, cambios, apagados e informes).

EJECUCIÓN
Mientras la aplicación esté abierta, un planificador ejecuta los apagados a su hora con 'shutdown /s /m'. Con la opción Archivo > 'Apagar también con PowerPulse cerrado' se crea una tarea de Windows que lo hace cada minuto aunque la aplicación esté cerrada (requiere sesión de usuario iniciada). El modo simulación (menú Archivo) registra la ejecución sin apagar ningún equipo. Para apagar equipos remotos se requieren permisos de administrador sobre ellos.

BUSCADOR
Las pestañas con listas disponen de un buscador que filtra por cualquier texto visible.

TEMA
El tema claro u oscuro se elige en Archivo > Tema y se recuerda al cerrar.

DATOS: {paths.DATA_DIR}
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
        self.settings = store.load_settings()
        theme.apply(self, self.settings["theme"])

        self.menubar = ttk.Frame(self)
        self.menubar.pack(side="top", fill="x")
        self.dry = tk.BooleanVar(value=self.settings["dry_run"])
        self.theme_var = tk.StringVar(value=self.settings["theme"])
        self.top_var = tk.BooleanVar(value=self.settings["always_on_top"])
        self.backup_view: Path | None = None
        self.bg_var = tk.BooleanVar(value=False)
        self._bg_state: bool | None = None
        threading.Thread(target=self._check_background, daemon=True).start()
        self.attributes("-topmost", self.top_var.get())
        self.build_menu()

        self.status = tk.StringVar()
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w").pack(side="bottom", fill="x")
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self.build_tabs()
        self.nb.bind("<<NotebookTabChanged>>", self._tab_changed)
        self.refresh_all()
        self.scheduler = Scheduler()
        self.scheduler.start()
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
        menu.add_checkbutton(label="Modo simulación (no apaga equipos)", variable=self.dry,
                             command=self.toggle_dry)
        menu.add_command(label="Retardo de apagado...", command=self.set_delay)
        menu.add_command(label="Abrir carpeta de datos", command=lambda: os.startfile(paths.DATA_DIR))
        menu.add_command(label="Carpeta de backups por defecto...", command=self.choose_backup_folder)
        menu.add_command(label="Restablecer carpeta de backups (Copia)", command=self.reset_backup_folder)
        menu.add_checkbutton(label="Mantener ventana en primer plano", variable=self.top_var,
                             command=self.toggle_top)
        menu.add_checkbutton(label="Apagar también con PowerPulse cerrado (tarea de Windows)",
                             variable=self.bg_var, command=self.toggle_background)
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

    def _check_background(self):
        self._bg_state = background.is_installed()

    def toggle_background(self):
        want = self.bg_var.get()
        ok, msg = background.install() if want else background.uninstall()
        if ok:
            store.log.info("Tarea en segundo plano %s", "activada" if want else "desactivada")
        else:
            self.bg_var.set(not want)
            messagebox.showerror("Segundo plano", f"No se pudo {'activar' if want else 'desactivar'} "
                                                  f"la tarea de Windows:\n{msg}", parent=self)
        self.update_status()

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
        self.dry.set(self.settings["dry_run"])
        self.top_var.set(self.settings["always_on_top"])
        self.attributes("-topmost", self.top_var.get())
        self.theme_var.set(self.settings["theme"])
        theme.apply(self, self.settings["theme"])
        self.build_menu()
        self.build_tabs()
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
        for name, cls in (("Programaciones", ScheduleTab), ("Calendario", CalendarTab),
                          ("Global", GlobalTab), ("Histórico", ArchiveTab), ("Estadísticas", StatsTab),
                          ("Informes", ReportsTab),
                          ("Backup", BackupTab), ("Logs", LogTab),
                          ("About", AboutTab)):
            tab = cls(self.nb, self)
            self.nb.add(tab, text=name)
            self.tabs[name] = tab
        self.nb.select(current)

    def toggle_dry(self):
        self.settings["dry_run"] = self.dry.get()
        store.save_settings(self.settings)
        self.update_status()

    def set_delay(self):
        v = messagebox.askinteger("Retardo", "Segundos de aviso antes de apagar (0-600):",
                                  initialvalue=self.settings["delay_seconds"],
                                  minvalue=0, maxvalue=600, parent=self)
        if v is not None:
            self.settings["delay_seconds"] = v
            store.save_settings(self.settings)
            self.update_status()

    def update_status(self):
        if self._bg_state is not None:
            self.bg_var.set(self._bg_state)
            self._bg_state = None
        mode = "SIMULACIÓN (no se apaga ningún equipo)" if self.settings["dry_run"] else "REAL (los equipos se apagarán)"
        bg = "ACTIVO" if self.bg_var.get() else "inactivo"
        self.status.set(f" Modo: {mode} | Segundo plano: {bg} | Retardo: {self.settings['delay_seconds']} s | "
                        f"Equipos MapPulse: {len(store.load_assignments())}")

    def refresh_all(self):
        archive.archive_finished()
        self.update_status()
        for tab in self.tabs.values():
            tab.refresh()

    def auto_refresh(self):
        self.refresh_all()
        self.after(15000, self.auto_refresh)

    def on_close(self):
        self.scheduler.stop()
        store.log.info("PowerPulse cerrado")
        self.destroy()


def main():
    App().mainloop()
