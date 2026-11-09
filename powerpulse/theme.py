import ctypes
from tkinter import ttk

LIGHT, DARK = "light", "dark"

_PALETTES = {
    LIGHT: {"bg": "#f0f0f0", "fg": "#000000", "field": "#ffffff", "button": "#e1e1e1", "hover": "#e9e9e9",
            "border": "#adadad", "muted": "#6d6d6d", "sel": "#7fb6ff", "selfg": "#000000",
            "busy": "#cfe8ff", "today": "#fff2b3", "idle": "#f4f4f4",
            "schedule_5pm": "#008000", "schedule_7am": "#c00000"},
    DARK: {"bg": "#202020", "fg": "#f0f0f0", "field": "#2b2b2b", "button": "#3a3a3a", "hover": "#4a4a4a",
           "border": "#555555", "muted": "#888888", "sel": "#0067c0", "selfg": "#ffffff",
           "busy": "#1f4e78", "today": "#7a6a1a", "idle": "#2b2b2b",
           "schedule_5pm": "#7cfc98", "schedule_7am": "#ff6b6b"},
}
_current = LIGHT
_native_theme: str | None = None


def pal() -> dict:
    return _PALETTES[_current]


def is_dark() -> bool:
    return _current == DARK


def style_titlebar(win) -> None:
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        val = ctypes.c_int(1 if is_dark() else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (build nuevo / antiguo)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), 4)
    except (AttributeError, OSError):
        pass


def apply(root, name: str) -> None:
    global _current, _native_theme
    style = ttk.Style(root)
    if _native_theme is None:
        _native_theme = style.theme_use()
    _current = name if name in _PALETTES else LIGHT
    p = pal()
    if is_dark():
        _style_dark(style, p)
    else:
        style.theme_use(_native_theme)
    root.configure(bg=p["bg"])
    for opt, key in (("background", "field"), ("foreground", "fg"),
                     ("selectBackground", "sel"), ("selectForeground", "selfg")):
        root.option_add(f"*TCombobox*Listbox.{opt}", p[key])
    style_titlebar(root)


def _style_dark(st: ttk.Style, p: dict) -> None:
    st.theme_use("clam")
    st.configure(".", background=p["bg"], foreground=p["fg"], fieldbackground=p["field"],
                 bordercolor=p["border"], lightcolor=p["bg"], darkcolor=p["bg"], troughcolor=p["field"],
                 selectbackground=p["sel"], selectforeground=p["selfg"], insertcolor=p["fg"])
    st.map(".", foreground=[("disabled", p["muted"])])
    st.configure("TButton", background=p["button"], padding=5)
    st.map("TButton", background=[("pressed", p["sel"]), ("active", p["hover"])])
    st.configure("TMenubutton", background=p["button"], arrowcolor=p["fg"], padding=4)
    st.map("TMenubutton", background=[("active", p["hover"])])
    st.configure("TEntry", fieldbackground=p["field"], foreground=p["fg"])
    st.configure("TCombobox", fieldbackground=p["field"], background=p["button"], arrowcolor=p["fg"])
    st.map("TCombobox", fieldbackground=[("readonly", p["field"])], foreground=[("readonly", p["fg"])],
           selectbackground=[("readonly", p["field"])], selectforeground=[("readonly", p["fg"])])
    st.configure("TNotebook", background=p["bg"], bordercolor=p["border"])
    st.configure("TNotebook.Tab", background=p["button"], foreground=p["fg"], padding=(12, 4))
    st.map("TNotebook.Tab", background=[("selected", p["sel"])], foreground=[("selected", p["selfg"])])
    st.configure("Treeview", background=p["field"], fieldbackground=p["field"], foreground=p["fg"])
    st.map("Treeview", background=[("selected", p["sel"])], foreground=[("selected", p["selfg"])])
    st.configure("Treeview.Heading", background=p["button"], foreground=p["fg"], relief="flat")
    st.map("Treeview.Heading", background=[("active", p["hover"])])
    for w in ("TCheckbutton", "TRadiobutton"):
        st.configure(w, background=p["bg"], indicatorcolor=p["field"])
        st.map(w, indicatorcolor=[("selected", p["sel"])])
    st.configure("TLabelframe", background=p["bg"], bordercolor=p["border"])
    st.configure("TLabelframe.Label", background=p["bg"], foreground=p["fg"])
    st.configure("TScrollbar", background=p["button"], troughcolor=p["bg"], arrowcolor=p["fg"],
                 bordercolor=p["bg"])
    st.map("TScrollbar", background=[("active", p["hover"])])
