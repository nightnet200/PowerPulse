"""Backup y restauración de la configuración y las programaciones."""
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from . import __version__, paths, store

DEFAULT_DIR = paths.DATA_DIR / "Copia"
LEGACY_DIR = paths.DATA_DIR / "backups"

LIST_FILES = {"schedules.json": paths.SCHEDULES_FILE, "global.json": paths.GLOBAL_FILE,
              "history.json": paths.HISTORY_FILE, "historico.json": paths.ARCHIVE_FILE}
SETTINGS_NAME = "settings.json"


def _migrate_legacy() -> None:
    """Mueve a Copia los backups creados cuando la carpeta por defecto se llamaba 'backups'."""
    if not LEGACY_DIR.is_dir():
        return
    DEFAULT_DIR.mkdir(parents=True, exist_ok=True)
    for f in LEGACY_DIR.glob("*.zip"):
        target = DEFAULT_DIR / f.name
        if not target.exists():
            shutil.move(str(f), target)
    try:
        LEGACY_DIR.rmdir()
    except OSError:
        pass


def backup_dir() -> Path:
    _migrate_legacy()
    chosen = store.load_settings().get("backup_dir")
    folder = Path(chosen) if chosen else DEFAULT_DIR
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        folder = DEFAULT_DIR
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def set_backup_dir(folder: str | Path | None) -> None:
    """None restablece la carpeta por defecto (Copia)."""
    settings = store.load_settings()
    settings["backup_dir"] = str(folder) if folder else ""
    store.save_settings(settings)


def default_name(prefix: str = "PowerPulse_backup") -> str:
    return f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}.zip"


def create(dest: str | Path, include_history: bool = True) -> dict:
    with store._lock:
        payload = {SETTINGS_NAME: store.load_settings(),
                   "schedules.json": store.schedules.all(),
                   "global.json": store.globals_.all()}
        if include_history:
            payload["history.json"] = store.history.all()
            payload["historico.json"] = store.archive.all()
    manifest = {"app": "PowerPulse", "version": __version__,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "files": list(payload)}
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        for name, data in payload.items():
            z.writestr(name, json.dumps(data, ensure_ascii=False, indent=2))
    counts = {"schedules": len(payload["schedules.json"]), "global": len(payload["global.json"])}
    store.log.info("BACKUP creado: %s %s", dest, counts)
    return counts


def read_backup(src: str | Path) -> tuple[dict, dict]:
    """Devuelve (manifest, datos) tras validar el contenido del zip."""
    try:
        with zipfile.ZipFile(src) as z:
            manifest = json.loads(z.read("manifest.json"))
            if manifest.get("app") != "PowerPulse":
                raise ValueError("El fichero no es un backup de PowerPulse.")
            data = {}
            for name in manifest.get("files", []):
                if name != SETTINGS_NAME and name not in LIST_FILES:
                    continue
                data[name] = json.loads(z.read(name))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Backup no válido: {exc}") from exc
    for name, value in data.items():
        expected = dict if name == SETTINGS_NAME else list
        if not isinstance(value, expected):
            raise ValueError(f"Contenido no válido en {name}.")
    if "schedules.json" not in data or "global.json" not in data:
        raise ValueError("El backup no contiene las programaciones.")
    return manifest, data


def restore(src: str | Path) -> dict:
    """Reemplaza los datos actuales; antes guarda una copia de seguridad del estado vigente."""
    _, data = read_backup(src)
    safety = backup_dir() / default_name("pre_restore")
    create(safety)
    with store._lock:
        for name, value in data.items():
            if name == SETTINGS_NAME:
                store._write(paths.SETTINGS_FILE, {**store.DEFAULT_SETTINGS, **value})
            else:
                store._write(LIST_FILES[name], value)
    store.log.info("BACKUP restaurado desde %s (copia previa: %s)", src, safety)
    return {"schedules": len(data["schedules.json"]), "global": len(data["global.json"]),
            "safety": str(safety)}
