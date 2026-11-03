import msvcrt
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from . import paths, store
from .occurrences import dates_for

log = store.log


@contextmanager
def _single_instance():
    """Bloqueo entre procesos: evita que la app y la tarea en segundo plano apaguen a la vez."""
    f = open(paths.DATA_DIR / "scheduler.lock", "a+")
    try:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        yield False
        return
    try:
        yield True
    finally:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        f.close()


def tick_once() -> None:
    """Una pasada del planificador, usada por la tarea de Windows con la app cerrada."""
    store.setup_logging()
    Scheduler().tick()


def shutdown_host(ip: str, delay: int, dry_run: bool) -> tuple[bool, str]:
    if dry_run:
        return True, "simulado"
    cmd = ["shutdown", "/s", "/f", "/t", str(delay), "/m", f"\\\\{ip}",
           "/c", "Apagado programado por PowerPulse"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    out = (r.stdout + r.stderr).decode("oem", errors="replace").strip()
    return r.returncode == 0, out or f"código {r.returncode}"


def _record(key: str, source: str, name: str, status: str, detail: str) -> None:
    store.history.add({"key": key, "source": source, "name": name,
                       "status": status, "detail": detail,
                       "executed_at": datetime.now().isoformat(timespec="seconds")})


def run_targets(ips: list[str], settings: dict) -> dict[str, tuple[bool, str]]:
    dry = settings["dry_run"]
    delay = settings["delay_seconds"]

    def one(ip):
        ok, msg = shutdown_host(ip, delay, dry)
        log.log(20 if ok else 40, "APAGADO %s -> %s (%s)", ip, "OK" if ok else "ERROR", msg)
        return ip, (ok, msg)

    with ThreadPoolExecutor(max_workers=10) as pool:
        return dict(pool.map(one, ips))


def global_targets(item: dict) -> list[str]:
    excluded = set(item.get("excluded_ips", []))
    return [a["ip"] for a in store.load_assignments() if a["ip"] not in excluded]


class Scheduler(threading.Thread):
    def __init__(self, interval: int = 20):
        super().__init__(daemon=True, name="PowerPulseScheduler")
        self.interval = interval
        self._stop_evt = threading.Event()

    def stop(self) -> None:
        self._stop_evt.set()

    def run(self) -> None:
        log.info("Planificador iniciado")
        while not self._stop_evt.wait(self.interval):
            try:
                self.tick()
            except Exception:
                log.exception("Error en el planificador")
        log.info("Planificador detenido")

    def tick(self) -> None:
        with _single_instance() as acquired:
            if acquired:
                self._tick_locked()

    def _tick_locked(self) -> None:
        from . import archive
        archive.archive_finished()
        settings = store.load_settings()
        now = datetime.now()
        today = now.date()
        grace = timedelta(minutes=settings["grace_minutes"])
        done = set(store.history.status_map())
        for source, st in (("Programación", store.schedules), ("Global", store.globals_)):
            for item in st.all():
                if not item.get("enabled", True):
                    continue
                key = f"{item['id']}|{today.isoformat()}"
                if key in done or not dates_for(item, today, today):
                    continue
                at = datetime.combine(today, datetime.strptime(item["time"], "%H:%M").time())
                if not (at <= now < at + grace):
                    continue
                self._execute(source, item, key, settings)

    def _execute(self, source: str, item: dict, key: str, settings: dict) -> None:
        name = item.get("name") or item.get("ip", "")
        ips = global_targets(item) if source == "Global" else [item["ip"]]
        log.info("EJECUCION %s '%s' sobre %d equipo(s)%s", source, name, len(ips),
                 " [SIMULACION]" if settings["dry_run"] else "")
        results = run_targets(ips, settings)
        fails = {ip: m for ip, (ok, m) in results.items() if not ok}
        if not fails:
            status = "Simulado" if settings["dry_run"] else "Ejecutado"
        else:
            status = "Error" if len(fails) == len(results) else "Parcial"
        detail = "; ".join(f"{ip}: {m}" for ip, m in fails.items())[:2000]
        _record(key, source, name, status, detail or f"{len(results)} equipo(s)")
