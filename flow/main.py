"""Application start-up: wires Qt, the icon, the Python objects and the QML UI together."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QSettings, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlPropertyMap
from PySide6.QtQuickControls2 import QQuickStyle

from . import appicon
from .constants import APP_NAME, APP_VERSION, DEFAULTS, DESKTOP_ID, FX_PRESETS, THEME
from .glyphs import ICONS
from .library import LibraryModel
from .paths import data_dir, resource_path
from .platform_setup import (apply_default_font, load_bundled_fonts, quiet_native_stderr,
                             setup_logging)
from .player import PlayerController
from .prefs import Prefs, theme_extras
from .visualizer import Visualizer

QML_FILE = "flow/qml/main.qml"


def main() -> int:
    setup_logging()
    os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")
    quiet_native_stderr()
    QCoreApplication.setOrganizationName(APP_NAME)
    QCoreApplication.setApplicationName(APP_NAME)

    appicon.set_windows_app_id()          # must happen before the first window

    app = QGuiApplication(sys.argv)
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(DESKTOP_ID)
    icon, logo_url = appicon.apply_to_app(app)

    family = load_bundled_fonts()         # JetBrains Mono from ./fonts
    apply_default_font(app, family)
    THEME["mono"] = family
    print(f"[{APP_NAME}] platform={app.platformName()} font={family} data={data_dir()}", file=sys.stderr)

    QQuickStyle.setStyle("Basic")

    # Portable settings: a plain .ini file in the app's data folder (no registry, no ~/.config).
    qs = QSettings(str(Path(data_dir()) / "settings.ini"), QSettings.Format.IniFormat)
    prefs = Prefs(qs)
    paths = [a for a in sys.argv[1:] if not a.startswith("--")]

    controller = PlayerController(qs, native_frame=True, prefs=prefs)
    library = LibraryModel(controller)
    wavefeed = Visualizer(controller)
    app.aboutToQuit.connect(controller.shutdown)
    app.aboutToQuit.connect(library.stop)
    app.aboutToQuit.connect(wavefeed.shutdown)

    theme = QQmlPropertyMap()
    for k, v in {**THEME, **theme_extras(prefs)}.items():
        theme.insert(k, v)

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("player", controller)
    ctx.setContextProperty("library", library)
    ctx.setContextProperty("wavefeed", wavefeed)
    ctx.setContextProperty("FxPresets", dict(FX_PRESETS))
    ctx.setContextProperty("UI", theme)
    ctx.setContextProperty("cfg", prefs.map)
    ctx.setContextProperty("cfgDefaults", dict(DEFAULTS))
    ctx.setContextProperty("IconPaths", ICONS)
    ctx.setContextProperty("LogoUrl", logo_url)
    ctx.setContextProperty("AppVersion", APP_VERSION)
    engine.load(QUrl.fromLocalFile(resource_path(QML_FILE)))
    if not engine.rootObjects():
        print(f"[{APP_NAME}] error: the interface failed to load (see messages above)", file=sys.stderr)
        return 1

    appicon.apply_to_windows(icon, engine.rootObjects())

    if prefs.get("scanOnLaunch"):
        QTimer.singleShot(300, library.rescan)
    if paths:
        QTimer.singleShot(0, lambda: controller.openUrls(paths))

    return app.exec()
