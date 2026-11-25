"""User settings, persisted with QSettings and exposed to QML as `cfg`."""
from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtQml import QQmlPropertyMap

from .constants import DEFAULTS


def _coerce(default, v):
    if isinstance(default, bool):
        return v if isinstance(v, bool) else str(v).lower() in ("true", "1")
    if isinstance(default, int):
        return int(round(float(v)))
    if isinstance(default, float):
        return float(v)
    return str(v)


class Prefs:
    """User settings. `map` is exposed to QML as `cfg` (read + write, auto-persisted)."""

    def __init__(self, settings: QSettings):
        self._s = settings
        self.map = QQmlPropertyMap()
        for k, d in DEFAULTS.items():
            try:
                val = _coerce(d, settings.value("prefs/" + k, d))
            except (TypeError, ValueError):
                val = d
            self.map.insert(k, val)
        self.map.valueChanged.connect(self._save)

    def _save(self, key, value):
        if key in DEFAULTS:
            self._s.setValue("prefs/" + key, value)

    def get(self, key):
        try:
            return _coerce(DEFAULTS[key], self.map.value(key))
        except (TypeError, ValueError):
            return DEFAULTS[key]


def theme_extras(p: Prefs) -> dict:
    """Derived theme values. QML Bindings keep these in sync while the app runs."""
    phys = p.get("physics")
    return {
        "physics": phys,
        "sp": p.get("stiffness") if phys else 6.0,
        "dp": (0.5 - 0.42 * p.get("bounce")) if phys else 0.9,
        "hoverScale": p.get("hoverScale"),
        "magnet": p.get("magnet"),
    }
