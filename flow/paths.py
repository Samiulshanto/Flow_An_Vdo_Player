"""Where things live on disk. Portable: data stays next to the app (or next to Flow.exe)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# .../Flow/flow/paths.py  ->  .../Flow
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FROZEN = bool(getattr(sys, "frozen", False))

# Folder that holds the app: the .exe itself when frozen, the project folder otherwise.
APP_ROOT = Path(sys.executable).resolve().parent if FROZEN else PROJECT_ROOT

_data_cache: str | None = None


def resource_path(name: str) -> str:
    """Absolute path of a bundled resource (icons/..., fonts/..., flow/qml/...)."""
    base = getattr(sys, "_MEIPASS", None) or str(PROJECT_ROOT)
    return os.path.join(base, *name.split("/"))


def _writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def data_dir() -> str:
    """Writable folder for settings, cache and logs: <app folder>/data, or a per-user folder
    if the app folder is read-only."""
    global _data_cache
    if _data_cache:
        return _data_cache
    d = APP_ROOT / "data"
    if not _writable(d):
        if sys.platform == "win32":
            base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        else:
            base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        d = base / "flow-media-player"
        d.mkdir(parents=True, exist_ok=True)
    _data_cache = str(d)
    return _data_cache