"""Generación de los TXT diarios consumidos por el proceso externo del usuario."""
import json
import os
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from . import paths, store
from .occurrences import dates_for
from .schedule_targets import included_ips

OUTPUT_DIR = Path(r"C:\ShutPCs\Calendario\regs")
MANIFEST_FILE = paths.DATA_DIR / "generated_schedule_txt.json"
ROLLING_DAYS = 365
_DATE_FILE = re.compile(r"\d{4}-\d{2}-\d{2}\.txt\Z")


def _read_manifest() -> set[str]:
    if not MANIFEST_FILE.exists():
        return set()
    try:
        data = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"No se pudo leer el manifiesto de TXT generados: {exc}") from exc
    if not isinstance(data, list) or not all(
            isinstance(name, str) and _DATE_FILE.fullmatch(name) for name in data):
        raise ValueError("El manifiesto de TXT generados tiene un formato no válido.")
    return set(data)


def _write_atomic(path: Path, content: str) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        temp.write_text(content, encoding="ascii", newline="")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _ip_sort_key(ip: str) -> tuple[tuple[int, int | str], ...]:
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                 for part in ip.split("."))


def generate(today: date | None = None, *, now: datetime | None = None,
             cleanup_elapsed: bool = False) -> int:
    """Genera TXT futuros; las recurrencias abiertas se mantienen en una ventana móvil."""
    now = now or datetime.now()
    today = today or now.date()
    latest = today + timedelta(days=ROLLING_DAYS)
    targets: dict[date, set[str]] = defaultdict(set)

    schedules = store.schedules.all()
    assignments = (store.load_assignments_strict()
                   if any(item.get("enabled", True) and item.get("target_mode") == "all"
                          for item in schedules) else None)
    for item in schedules:
        if not item.get("enabled", True):
            continue
        start = max(today, date.fromisoformat(item["start_date"]))
        until = date.fromisoformat(item["until"]) if item.get("until") else None
        end = until or latest
        if start > end:
            continue
        ips = included_ips(item, assignments)
        for occurrence in dates_for(item, start, end):
            if datetime.combine(
                    occurrence, datetime.strptime(item["time"], "%H:%M").time()) < now:
                continue
            targets[occurrence].update(ips)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    previous = _read_manifest()
    current = {f"{day.isoformat()}.txt" for day, ips in targets.items() if ips}

    for name in current - previous:
        path = OUTPUT_DIR / name
        if path.exists():
            raise FileExistsError(f"El archivo existe y no fue generado por PowerPulse: {path}")

    retained = {name for name in previous - current
                if date.fromisoformat(name[:-4]) < today and not cleanup_elapsed}

    _write_atomic(MANIFEST_FILE, json.dumps(sorted(previous | current), indent=2))
    for day, ips in targets.items():
        if not ips:
            continue
        name = f"{day.isoformat()}.txt"
        path = OUTPUT_DIR / name
        lines = [f"\\\\{ip}" for ip in sorted(ips, key=_ip_sort_key)]
        _write_atomic(path, "\r\n".join(lines) + "\r\n")

    for stale_name in previous - current - retained:
        stale = OUTPUT_DIR / stale_name
        if stale.exists():
            stale.unlink()

    _write_atomic(MANIFEST_FILE, json.dumps(sorted(current | retained), indent=2))
    store.log.info("TXT de programación generados: %d archivo(s) en %s", len(current), OUTPUT_DIR)
    return len(current)
