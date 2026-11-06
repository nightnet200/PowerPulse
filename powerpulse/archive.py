"""Archivo histórico de programaciones finalizadas."""
from datetime import date, datetime

from . import paths, store
from .occurrences import dates_for
from .schedule_targets import scope_ips


def last_date(item: dict) -> date | None:
    """Última fecha en la que se ejecuta la programación; None si no termina nunca."""
    start = date.fromisoformat(item["start_date"])
    if item.get("repeat", "none") == "none":
        return start
    if not item.get("until"):
        return None
    until = date.fromisoformat(item["until"])
    occurrences = dates_for(item, start, until)
    return occurrences[-1] if occurrences else until


def is_finished(item: dict, today: date | None = None) -> bool:
    last = last_date(item)
    return last is not None and last < (today or date.today())


def is_elapsed(item: dict, now: datetime | None = None) -> bool:
    """Una serie termina cuando ha pasado la hora de su última ocurrencia."""
    last = last_date(item)
    if last is None:
        return False
    when = datetime.combine(last, datetime.strptime(item["time"], "%H:%M").time())
    return when < (now or datetime.now())


def _archive_item(item: dict, final_status: str, now: str, kind: str) -> None:
    if any(a.get("schedule_id") == item["id"] for a in store.archive.all()):
        return
    last = last_date(item)
    record = {k: v for k, v in item.items() if k != "id"}
    if item.get("target_mode") == "all":
        record["ips"] = scope_ips(item, store.load_assignments_strict())
        record["target_mode"] = "selected"
    record.update(schedule_id=item["id"], last_date=last.isoformat() if last else None,
                  final_status=final_status, archived_at=now, archive_kind=kind)
    store.archive.add(record)


def delete_to_history(item_id: str) -> None:
    """Remove a schedule from active work while retaining its last version."""
    with store._lock:
        item = store.schedules.get(item_id)
        if item is None:
            raise ValueError("La programación ya no existe.")
        _archive_item(item, "Eliminada", datetime.now().isoformat(timespec="seconds"), "deleted")
        store.schedules.delete(item_id)


def archive_finished(now: datetime | None = None) -> int:
    """Archiva las series cuya última fecha y hora ya han pasado."""
    with store._lock:
        now = now or datetime.now()
        items = store.schedules.all()
        finished = [s for s in items if is_elapsed(s, now)]
        if not finished:
            return 0
        for s in finished:
            _archive_item(s, "Hora superada (sin confirmar)", now.isoformat(timespec="seconds"), "completed")
        finished_ids = {s["id"] for s in finished}
        store._write(paths.SCHEDULES_FILE, [s for s in items if s["id"] not in finished_ids])
    store.log.info("ARCHIVADAS %d programaciones finalizadas", len(finished))
    return len(finished)


def as_schedules() -> list[dict]:
    """Programaciones archivadas con su id original, para informes y estadísticas de fechas pasadas."""
    return [{**a, "id": a.get("schedule_id", a["id"])} for a in store.archive.all()
            if a.get("archive_kind") != "deleted"]
