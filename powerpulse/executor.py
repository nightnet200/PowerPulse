"""Compatibility entry points for removing obsolete scheduled shutdown tasks."""
from . import background, store


def tick_once() -> None:
    store.setup_logging()
    ok, detail = background.uninstall()
    if not ok:
        store.log.error("No se pudieron eliminar las tareas de apagado antiguas: %s", detail)
        raise RuntimeError(detail or "No se pudieron eliminar las tareas antiguas.")
    store.log.info("Tareas antiguas de apagado eliminadas; no se ejecutó ninguna orden.")


def tick_global_once(_item_id: str) -> None:
    tick_once()
