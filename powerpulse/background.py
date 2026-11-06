"""Limpieza de tareas de apagado creadas por versiones anteriores de PowerPulse."""
import subprocess

TASK_NAME = "PowerPulse-Scheduler"
_TASK_DESCRIPTION_PREFIX = "PowerPulse Global:"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def uninstall() -> tuple[bool, str]:
    """Elimina las tareas antiguas que podían enviar apagados remotos."""
    script = (
        "$ErrorActionPreference = 'Stop'; "
        f"$task = Get-ScheduledTask -TaskPath '\\' -TaskName '{TASK_NAME}' "
        "-ErrorAction SilentlyContinue; "
        "if ($task) { Unregister-ScheduledTask -TaskPath '\\' "
        f"-TaskName '{TASK_NAME}' -Confirm:$false -ErrorAction Stop }}; "
        "$tasks = @(Get-ScheduledTask -TaskPath '\\Global\\' "
        "-ErrorAction SilentlyContinue | Where-Object { "
        f"$_.TaskName -eq '{TASK_NAME}' -or $_.Description -like '{_TASK_DESCRIPTION_PREFIX}*' }}); "
        "foreach ($task in $tasks) { Unregister-ScheduledTask -TaskPath $task.TaskPath "
        "-TaskName $task.TaskName -Confirm:$false -ErrorAction Stop }")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", script],
            capture_output=True, timeout=60, creationflags=_NO_WINDOW)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    output = (result.stdout + result.stderr).decode("oem", errors="replace").strip()
    return result.returncode == 0, output
