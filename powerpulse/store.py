import json
import logging
import os
import threading
import uuid
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from . import paths

_lock = threading.RLock()
log = logging.getLogger("powerpulse")


def setup_logging() -> None:
    if log.handlers:
        return
    log.setLevel(logging.INFO)
    handler = TimedRotatingFileHandler(
        paths.LOG_FILE, when="midnight", backupCount=90, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    log.addHandler(handler)


def _read(path: Path, default):
    with _lock:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.error("No se pudo leer %s: %s", path, exc)
            return default


def _write(path: Path, data) -> None:
    with _lock:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)


class JsonStore:
    """CRUD sobre un fichero JSON con una lista de diccionarios."""

    def __init__(self, path: Path, name: str):
        self.path = path
        self.name = name

    def all(self) -> list[dict]:
        return _read(self.path, [])

    def get(self, item_id: str) -> dict | None:
        return next((i for i in self.all() if i["id"] == item_id), None)

    def add(self, item: dict) -> dict:
        with _lock:
            items = self.all()
            now = datetime.now().isoformat(timespec="seconds")
            item = {**item, "id": str(uuid.uuid4()), "created_at": now, "updated_at": now}
            items.append(item)
            _write(self.path, items)
        log.info("[%s] CREADO %s", self.name, _brief(item))
        return item

    def update(self, item_id: str, changes: dict) -> None:
        with _lock:
            items = self.all()
            for i in items:
                if i["id"] == item_id:
                    i.update(changes)
                    i["updated_at"] = datetime.now().isoformat(timespec="seconds")
                    _write(self.path, items)
                    log.info("[%s] ACTUALIZADO %s", self.name, _brief(i))
                    return

    def delete(self, item_id: str) -> None:
        with _lock:
            items = self.all()
            gone = [i for i in items if i["id"] == item_id]
            _write(self.path, [i for i in items if i["id"] != item_id])
        for i in gone:
            log.info("[%s] BORRADO %s", self.name, _brief(i))


def _brief(item: dict) -> str:
    keys = ("id", "name", "ip", "start_date", "time", "repeat")
    return " ".join(f"{k}={item[k]}" for k in keys if k in item)


class HistoryStore(JsonStore):
    def status_map(self) -> dict[str, dict]:
        return {h["key"]: h for h in self.all()}


schedules = JsonStore(paths.SCHEDULES_FILE, "PROGRAMACION")
globals_ = JsonStore(paths.GLOBAL_FILE, "GLOBAL")
history = HistoryStore(paths.HISTORY_FILE, "HISTORIAL")

DEFAULT_SETTINGS = {"dry_run": True, "delay_seconds": 60, "grace_minutes": 15, "theme": "light"}


def load_settings() -> dict:
    data = _read(paths.SETTINGS_FILE, {})
    return {**DEFAULT_SETTINGS, **data}


def save_settings(settings: dict) -> None:
    _write(paths.SETTINGS_FILE, settings)
    log.info("Configuración guardada: %s", settings)


def load_assignments() -> list[dict]:
    """Equipos y usuarios de MapPulse (solo lectura)."""
    data = _read(paths.ASSIGNMENTS_FILE, [])
    items = [a for a in data if a.get("ip")]
    return sorted(items, key=lambda a: tuple(int(p) if p.isdigit() else 0 for p in a["ip"].split(".")))


def equipment_text(a: dict) -> str:
    extra = a.get("alias") or a.get("hostname")
    return f"{a['ip']}  |  {a.get('label', '')}" + (f"  ({extra})" if extra else "")
