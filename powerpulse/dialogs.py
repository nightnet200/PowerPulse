"""Cuadros de diálogo con el tema de la aplicación (los nativos de Windows no admiten tema oscuro)."""
import tkinter as tk
from tkinter import ttk

from . import theme


class _Box(tk.Toplevel):
    def __init__(self, parent, title, message, buttons, default, prompt_value=None, validate=None):
        root = parent.winfo_toplevel() if parent else tk._default_root
        super().__init__(root)
        self.title(title)
        self.configure(bg=theme.pal()["bg"])
        self.resizable(False, False)
        self.transient(root)
        self.result = None
        self.validate = validate
        body = ttk.Frame(self, padding=16)
        body.pack()
        ttk.Label(body, text=message, wraplength=420, justify="left").pack(anchor="w")
        self.var = None
        self.error = ttk.Label(body, foreground="#ff6b6b")
        if prompt_value is not None:
            self.var = tk.StringVar(value=str(prompt_value))
            entry = ttk.Entry(body, textvariable=self.var)
            entry.pack(fill="x", pady=(8, 0))
            entry.focus_set()
            entry.select_range(0, "end")
            self.error.pack(anchor="w")
        bar = ttk.Frame(body)
        bar.pack(anchor="e", pady=(14, 0))
        for label, value in buttons:
            btn = ttk.Button(bar, text=label, command=lambda v=value: self._close(v))
            btn.pack(side="left", padx=4)
            if value == default:
                self.bind("<Return>", lambda e, v=value: self._close(v))
                if self.var is None:
                    btn.focus_set()
        self.bind("<Escape>", lambda e: self._close(None))
        self.protocol("WM_DELETE_WINDOW", lambda: self._close(None))
        self.update_idletasks()
        x = root.winfo_rootx() + (root.winfo_width() - self.winfo_reqwidth()) // 2
        y = root.winfo_rooty() + (root.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.wait_visibility()
        theme.style_titlebar(self)
        self.grab_set()
        self.wait_window(self)

    def _close(self, value):
        if value is True and self.validate and self.var is not None:
            err = self.validate(self.var.get())
            if err:
                self.error.config(text=err)
                return
        if self.var is not None:
            value = self.var.get() if value is True else None
        self.result = value
        self.destroy()


def showinfo(title, message, parent=None):
    _Box(parent, title, message, [("Aceptar", True)], True)


def showerror(title, message, parent=None):
    _Box(parent, title, message, [("Aceptar", True)], True)


def askyesno(title, message, parent=None, default="yes"):
    box = _Box(parent, title, message, [("Sí", True), ("No", False)], default == "yes")
    return bool(box.result)


def askinteger(title, prompt, initialvalue=0, minvalue=None, maxvalue=None, parent=None):
    def validate(text):
        try:
            n = int(text)
        except ValueError:
            return "Introduzca un número entero."
        if (minvalue is not None and n < minvalue) or (maxvalue is not None and n > maxvalue):
            return f"El valor debe estar entre {minvalue} y {maxvalue}."
        return None

    box = _Box(parent, title, prompt, [("Aceptar", True), ("Cancelar", False)], True,
               prompt_value=initialvalue, validate=validate)
    return int(box.result) if box.result is not None else None
