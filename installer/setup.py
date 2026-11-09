"""Instalador/desinstalador de PowerPulse (por usuario, sin privilegios de administrador)."""
import os
import shutil
import subprocess
import sys
import tkinter as tk
import winreg
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from powerpulse import background

APP = "PowerPulse"
VERSION = "1.3.0"
PUBLISHER = "PowerPulse"
UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP}"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
LOCAL = Path(os.environ["LOCALAPPDATA"])
START_MENU = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
DESKTOP = Path.home() / "Desktop"


def make_shortcut(link: Path, target: Path, icon: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{l}');"
          "$s.TargetPath='{t}';$s.WorkingDirectory='{w}';$s.IconLocation='{i}';"
          "$s.Description='{a}';$s.Save()").format(
        l=link, t=target, w=target.parent, i=icon, a=APP)
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, creationflags=NO_WINDOW)


def install(dest: Path, desktop: bool) -> Path:
    ok, msg = background.uninstall()
    if not ok:
        raise OSError(f"No se pudieron eliminar las tareas anteriores:\n{msg}")
    dest.mkdir(parents=True, exist_ok=True)
    exe = dest / f"{APP}.exe"
    shutil.copy2(BUNDLE / f"{APP}.exe", exe)
    shutil.copy2(BUNDLE / "icon.ico", dest / "icon.ico")
    uninstaller = dest / "Uninstall.exe"
    shutil.copy2(sys.executable, uninstaller)

    make_shortcut(START_MENU / f"{APP}.lnk", exe, dest / "icon.ico")
    if desktop:
        make_shortcut(DESKTOP / f"{APP}.lnk", exe, dest / "icon.ico")

    size_kb = sum(f.stat().st_size for f in dest.iterdir()) // 1024
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        for name, val in (("DisplayName", APP), ("DisplayVersion", VERSION), ("Publisher", PUBLISHER),
                          ("InstallLocation", str(dest)), ("DisplayIcon", str(dest / "icon.ico")),
                          ("UninstallString", f'"{uninstaller}" --uninstall')):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
        for name in ("NoModify", "NoRepair"):
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, size_kb)
    return exe


def uninstall() -> None:
    root = tk.Tk()
    root.withdraw()
    if not messagebox.askyesno(f"Desinstalar {APP}", f"¿Desinstalar {APP} {VERSION}?"):
        return
    purge = messagebox.askyesno(
        APP, "¿Eliminar también los datos (programaciones, globales, historial y logs)?\n"
             f"{LOCAL / APP}", default="no")
    dest = Path(sys.executable).parent
    for link in (START_MENU / f"{APP}.lnk", DESKTOP / f"{APP}.lnk"):
        link.unlink(missing_ok=True)
    ok, detail = background.uninstall()
    if not ok:
        messagebox.showerror(APP, f"No se pudieron eliminar las tareas anteriores:\n{detail}", parent=root)
        root.destroy()
        return
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass
    if purge:
        shutil.rmtree(LOCAL / APP, ignore_errors=True)
    # El desinstalador no puede borrarse a sí mismo: se difiere con cmd.
    subprocess.Popen(f'cmd /c ping -n 3 127.0.0.1 >nul & rmdir /s /q "{dest}"',
                     creationflags=NO_WINDOW | subprocess.DETACHED_PROCESS, close_fds=True)
    messagebox.showinfo(APP, "PowerPulse se ha desinstalado.")


class Wizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Instalación de {APP} {VERSION}")
        self.resizable(False, False)
        try:
            self.iconbitmap(BUNDLE / "icon.ico")
        except tk.TclError:
            pass
        f = ttk.Frame(self, padding=16)
        f.pack()
        ttk.Label(f, text=f"{APP} {VERSION}", font=("Segoe UI", 16, "bold")).grid(sticky="w")
        ttk.Label(f, text="Programación y generación de archivos de equipos de la LAN.").grid(sticky="w", pady=(0, 10))
        ttk.Label(f, text="Carpeta de instalación:").grid(sticky="w")
        self.path = tk.StringVar(value=str(LOCAL / "Programs" / APP))
        row = ttk.Frame(f)
        row.grid(sticky="we")
        ttk.Entry(row, textvariable=self.path, width=52).pack(side="left")
        ttk.Button(row, text="Examinar...", command=self.browse).pack(side="left", padx=4)
        self.desktop = tk.BooleanVar(value=True)
        self.launch = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="Crear acceso directo en el escritorio", variable=self.desktop).grid(sticky="w", pady=(10, 0))
        ttk.Checkbutton(f, text="Ejecutar PowerPulse al terminar (genera los TXT)", variable=self.launch).grid(sticky="w")
        bar = ttk.Frame(f)
        bar.grid(sticky="e", pady=(14, 0))
        ttk.Button(bar, text="Instalar", command=self.run).pack(side="left", padx=4)
        ttk.Button(bar, text="Cancelar", command=self.destroy).pack(side="left")

    def browse(self):
        d = filedialog.askdirectory(initialdir=self.path.get(), parent=self)
        if d:
            self.path.set(str(Path(d) / APP) if Path(d).name != APP else d)

    def run(self):
        try:
            exe = install(Path(self.path.get()), self.desktop.get())
        except (OSError, subprocess.CalledProcessError) as exc:
            messagebox.showerror(APP, f"No se pudo instalar:\n{exc}", parent=self)
            return
        messagebox.showinfo(APP, "Instalación completada.", parent=self)
        if self.launch.get():
            subprocess.Popen([str(exe)], cwd=exe.parent, close_fds=True)
        self.destroy()


if __name__ == "__main__":
    if "--uninstall" in sys.argv:
        uninstall()
    else:
        Wizard().mainloop()
