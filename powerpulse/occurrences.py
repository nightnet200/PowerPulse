import calendar
from datetime import date, datetime, timedelta

REPEATS = {"none": "Una vez", "daily": "Diaria", "weekly": "Semanal", "monthly": "Mensual",
           "range": "Rango de días"}
WEEKDAYS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def parse_user_date(text: str) -> date:
    text = text.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Fecha no válida: '{text}' (use dd/mm/aaaa)")


def parse_time(text: str) -> str:
    try:
        return datetime.strptime(text.strip(), "%H:%M").strftime("%H:%M")
    except ValueError:
        raise ValueError(f"Hora no válida: '{text}' (use HH:MM)")


def fmt_date(iso: str | date | None) -> str:
    if not iso:
        return ""
    d = date.fromisoformat(iso) if isinstance(iso, str) else iso
    return d.strftime("%d/%m/%Y")


def weekdays_text(item: dict) -> str:
    if item.get("repeat") != "weekly":
        return ""
    days = item.get("weekdays") or [date.fromisoformat(item["start_date"]).weekday()]
    return ", ".join(WEEKDAYS[d] for d in sorted(days))


def dates_for(item: dict, d0: date, d1: date) -> list[date]:
    """Fechas en [d0, d1] en las que se dispara la programación."""
    start = date.fromisoformat(item["start_date"])
    until = date.fromisoformat(item["until"]) if item.get("until") else None
    end = min(d1, until) if until else d1
    first = max(d0, start)
    repeat = item.get("repeat", "none")
    if first > end:
        return []
    if repeat == "none":
        return [start] if d0 <= start <= d1 else []
    days = (first + timedelta(days=n) for n in range((end - first).days + 1))
    if repeat in ("daily", "range"):
        return list(days)
    if repeat == "weekly":
        wd = set(item.get("weekdays") or [start.weekday()])
        return [d for d in days if d.weekday() in wd]
    if repeat == "monthly":
        return [d for d in days if d.day == start.day]
    return []


def in_range(items: list[dict], d0: date, d1: date) -> dict[date, list[dict]]:
    out: dict[date, list[dict]] = {}
    for item in items:
        for d in dates_for(item, d0, d1):
            out.setdefault(d, []).append(item)
    for lst in out.values():
        lst.sort(key=lambda i: i["time"])
    return out


def period_range(period: str, ref: date) -> tuple[date, date]:
    if period == "day":
        return ref, ref
    if period == "month":
        return ref.replace(day=1), ref.replace(day=calendar.monthrange(ref.year, ref.month)[1])
    return date(ref.year, 1, 1), date(ref.year, 12, 31)


def status_for(item: dict, d: date, hist: dict[str, dict]) -> str:
    h = hist.get(f"{item['id']}|{d.isoformat()}")
    if h:
        return h["status"]
    if not item.get("enabled", True):
        return "Desactivada"
    when = datetime.combine(d, datetime.strptime(item["time"], "%H:%M").time())
    return "No ejecutado" if when < datetime.now() else "Pendiente"
