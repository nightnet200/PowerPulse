"""Archivo histórico de programaciones finalizadas."""
from datetime import date, datetime

from . import paths, store
from .occurrences import dates_for, status_for


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


def archive_finished() -> int:
    """Mueve al histórico las programaciones sin ejecuciones futuras. Devuelve cuántas movió."""
    with store._lock:
        today = date.today()
        items = store.schedules.all()
        finished = [s for s in items if is_finished(s, today)]
        if not finished:
            return 0
        hist = store.history.status_map()
        now = datetime.now().isoformat(timespec="seconds")
        for s in finished:
            last = last_date(s)
            record = {k: v for k, v in s.items() if k != "id"}
            record.update(schedule_id=s["id"], last_date=last.isoformat(),
                          final_status=status_for(s, last, hist), archived_at=now)
            store.archive.add(record)
        store._write(paths.SCHEDULES_FILE, [s for s in items if not is_finished(s, today)])
    store.log.info("ARCHIVADAS %d programaciones finalizadas", len(finished))
    return len(finished)


def as_schedules() -> list[dict]:
    """Programaciones archivadas con su id original, para informes y estadísticas de fechas pasadas."""
    return [{**a, "id": a.get("schedule_id", a["id"])} for a in store.archive.all()]
