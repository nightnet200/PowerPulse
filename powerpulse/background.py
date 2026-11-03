"""Tarea programada de Windows que ejecuta el planificador aunque PowerPulse esté cerrado."""
import subprocess
import sys
from pathlib import Path

TASK_NAME = "PowerPulse-Scheduler"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _quote(text: str) -> str:
    return text.replace("'", "''")


def _command(exe: str | Path | None) -> tuple[str, str]:
    if exe:
        return str(exe), "--tick"
    if getattr(sys, "frozen", False):
        return sys.executable, "--tick"
    pyw = Path(sys.executable).with_name("pythonw.exe")
    run = Path(__file__).resolve().parent.parent / "run.py"
    return str(pyw if pyw.exists() else sys.executable), f'"{run}" --tick'


def _powershell(script: str) -> tuple[bool, str]:
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-Command", script], capture_output=True, timeout=60, creationflags=_NO_WINDOW)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    out = (r.stdout + r.stderr).decode("oem", errors="replace").strip()
    return r.returncode == 0, out


def is_installed() -> bool:
    return _powershell(f"Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction Stop | Out-Null")[0]


def install(exe: str | Path | None = None) -> tuple[bool, str]:
    """Crea la tarea del usuario actual: se ejecuta cada minuto mientras tenga la sesión iniciada."""
    program, args = _command(exe)
    script = (
        f"$a = New-ScheduledTaskAction -Execute '{_quote(program)}' -Argument '{_quote(args)}'; "
        "$t = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 1) "
        "-RepetitionDuration (New-TimeSpan -Days 3650); "
        "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30); "
        f"Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $a -Trigger $t -Settings $s "
        "-Description 'Ejecuta los apagados programados de PowerPulse' -Force | Out-Null")
    return _powershell(script)


def uninstall() -> tuple[bool, str]:
    return _powershell(f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false -ErrorAction Stop")
