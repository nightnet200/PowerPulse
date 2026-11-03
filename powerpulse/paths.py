import os
import sys
from pathlib import Path

RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
ICON_FILE = RESOURCE_DIR / "assets" / "icon.ico"

LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))

ASSIGNMENTS_FILE = LOCALAPPDATA / "MapPulse" / "MapPulse" / "assignments.json"

DATA_DIR = LOCALAPPDATA / "PowerPulse"
SCHEDULES_FILE = DATA_DIR / "schedules.json"
GLOBAL_FILE = DATA_DIR / "global.json"
HISTORY_FILE = DATA_DIR / "history.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "powerpulse.log"
REPORTS_DIR = DATA_DIR / "reports"

for _d in (DATA_DIR, LOG_DIR, REPORTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
