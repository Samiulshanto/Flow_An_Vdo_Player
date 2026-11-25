"""OS-level start-up tweaks: log file, stderr noise filter, bundled fonts."""
from __future__ import annotations

import io
import os
import sys
import threading
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication

from .paths import data_dir, resource_path

FONT_FAMILY = "JetBrains Mono"
FONT_FILES = (
    "JetBrainsMono-Regular.ttf",
    "JetBrainsMono-Medium.ttf",
    "JetBrainsMono-SemiBold.ttf",
    "JetBrainsMono-Bold.ttf",
)


def setup_logging() -> None:
    """When there is no console (Windows double-click / pythonw), write output to data/flow.log."""
    if sys.stderr is not None and sys.stdout is not None:
        try:
            if os.isatty(2):
                return
        except OSError:
            pass
    try:
        log = Path(data_dir()) / "flow.log"
        if log.exists() and log.stat().st_size > 1_000_000:
            log.unlink()
        f = open(log, "a", encoding="utf-8", errors="replace", buffering=1)
        sys.stdout = sys.stderr = f
        try:
            os.dup2(f.fileno(), 2)   # native Qt messages too
        except OSError:
            pass
    except OSError:
        pass


_NOISY = ("_mf @", "MFT name", "Input #0", "Stream #", "Metadata:", "Chapter #", "Chapters:",
          "Duration:", "creation_time", "encoder  ", "qt.multimedia")


def quiet_native_stderr() -> None:
    """Hide chatty FFmpeg / multimedia lines from native stderr. Python's own errors bypass the filter."""
    try:
        orig = os.dup(2)
        r, w = os.pipe()
        os.dup2(w, 2)
        os.close(w)
    except OSError:
        return
    # Python-level stderr (tracebacks) goes straight to the real stderr, unfiltered and unbuffered.
    try:
        sys.stderr = io.TextIOWrapper(io.FileIO(os.dup(orig), "w"), line_buffering=True,
                                      encoding="utf-8", errors="replace")
    except OSError:
        pass

    def pump():
        buf = b""
        with os.fdopen(r, "rb", buffering=0) as src:
            while True:
                chunk = src.read(4096)
                if not chunk:
                    break
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for ln in lines:
                    txt = ln.decode("utf-8", "replace")
                    st = txt.strip()
                    if any(k in txt for k in _NOISY) or st.startswith(("TITLE", "WEBSiTE", "Metadata")):
                        continue
                    try:
                        os.write(orig, ln + b"\n")
                    except OSError:
                        pass

    threading.Thread(target=pump, daemon=True).start()


def load_bundled_fonts() -> str:
    """Register JetBrains Mono from ./fonts so the UI looks identical on every machine."""
    loaded = 0
    for name in FONT_FILES:
        path = resource_path("fonts/" + name)
        if os.path.isfile(path) and QFontDatabase.addApplicationFont(path) >= 0:
            loaded += 1
    if loaded == 0:
        print("[Flow~] warning: bundled fonts not found, using system monospace", file=sys.stderr)
        return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
    return FONT_FAMILY


def apply_default_font(app: QGuiApplication, family: str) -> None:
    font = QFont(family)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPixelSize(13)
    app.setFont(font)
