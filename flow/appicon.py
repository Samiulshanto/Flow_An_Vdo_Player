"""
Single source of truth for the application icon: icons/app_master.ico

  * window title bar / taskbar / Alt-Tab   -> QGuiApplication.setWindowIcon + per-window setIcon
  * logo drawn inside the UI               -> PNG copied from the .ico into data/icon, passed to QML as LogoUrl
  * Windows taskbar grouping               -> AppUserModelID

Portable: nothing is installed or written outside the app folder (no launcher / menu entries).
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QGuiApplication, QIcon, QImage, QPixmap

from .constants import APP_ID, APP_NAME, DESKTOP_ID, ICON_FILE, IS_LINUX, IS_WIN
from .paths import PROJECT_ROOT, data_dir, resource_path

PNG_SIZES = (16, 24, 32, 48, 64, 128, 256)
LOGO_SIZE = 256


# ----------------------------------------------------------------------------- loading

def icon_file() -> str | None:
    """Path of icons/app_master.ico, searching resource_path and project roots."""
    try:
        p = resource_path(ICON_FILE)
        if os.path.isfile(p):
            return str(p)
    except Exception:
        pass

    candidates = [
        PROJECT_ROOT / ICON_FILE,
        PROJECT_ROOT / "icons" / "app_master.ico",
        Path(__file__).resolve().parent.parent / "icons" / "app_master.ico",
        Path(__file__).resolve().parent / "icons" / "app_master.ico",
        Path.cwd() / ICON_FILE,
        Path.cwd() / "icons" / "app_master.ico",
    ]
    for cand in candidates:
        try:
            if cand.is_file():
                return str(cand.resolve())
        except Exception:
            continue
    return None


def _ico_png_frames(path: str) -> dict[int, bytes]:
    """
    {size: PNG bytes} for every PNG-compressed frame inside an .ico.
    Pure Python, so it does not depend on Qt's .ico image plugin being present.
    """
    frames: dict[int, bytes] = {}
    try:
        data = Path(path).read_bytes()
        _reserved, kind, count = struct.unpack_from("<HHH", data, 0)
        if kind != 1:
            return {}
        for i in range(count):
            w, h, _cc, _r, _planes, _bpp, size, off = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
            w, h = w or 256, h or 256          # 0 means 256 in the ICO format
            blob = data[off:off + size]
            if w == h and blob[:8] == b"\x89PNG\r\n\x1a\n":
                frames[w] = blob
    except (OSError, struct.error):
        return {}
    return frames


def _source_sig() -> str:
    """Short content hash of the .ico ('none' if missing). Changes when the icon changes."""
    src = icon_file()
    if not src:
        return "none"
    try:
        return hashlib.sha1(Path(src).read_bytes()).hexdigest()[:10]
    except OSError:
        return "none"


def _ico_fallback_image(size: int) -> QImage:
    """Extract and scale an image directly from app_master.ico without drawing anything by code."""
    path = icon_file()
    if path and os.path.isfile(path):
        frames = _ico_png_frames(path)
        if frames:
            blob = frames.get(size) or frames[max(frames.keys())]
            img = QImage()
            if img.loadFromData(blob, "PNG"):
                img.setDevicePixelRatio(1.0)
                if img.width() != size or img.height() != size:
                    img = img.scaled(
                        size, size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                return img

        img = QImage(path)
        if not img.isNull():
            img.setDevicePixelRatio(1.0)
            if img.width() != size or img.height() != size:
                img = img.scaled(
                    size, size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            return img

    empty = QImage(size, size, QImage.Format.Format_ARGB32)
    empty.fill(Qt.GlobalColor.transparent)
    return empty


def load_app_icon() -> QIcon:
    """QIcon with every frame of the .ico (16..256 px)."""
    path = icon_file()
    icon = QIcon()

    if path and os.path.isfile(path):
        icon = QIcon(path)
        frames = _ico_png_frames(path)

        for _sz, blob in sorted(frames.items()):
            pm = QPixmap()
            if pm.loadFromData(blob, "PNG"):
                icon.addPixmap(pm)

        if icon.isNull() or icon.pixmap(QSize(32, 32)).isNull():
            for sz in PNG_SIZES:
                fb = _ico_fallback_image(sz)
                if not fb.isNull():
                    icon.addPixmap(QPixmap.fromImage(fb))

        if not icon.isNull() and not icon.pixmap(QSize(32, 32)).isNull():
            print(f"[{APP_NAME}] icon: {path}", file=sys.stderr)
            return icon
        print(f"[{APP_NAME}] warning: could not read {path}", file=sys.stderr)
    else:
        print(f"[{APP_NAME}] warning: {ICON_FILE} not found", file=sys.stderr)

    # Even on read failure, populate strictly from the ICO fallback reader
    for sz in PNG_SIZES:
        fb = _ico_fallback_image(sz)
        if not fb.isNull():
            icon.addPixmap(QPixmap.fromImage(fb))
    return icon


def _render(icon: QIcon, size: int) -> QImage:
    """Render the icon at exactly size x size (device-pixel-ratio independent)."""
    if not icon.isNull():
        pm = icon.pixmap(QSize(size, size))
        if not pm.isNull():
            img = pm.toImage()
            img.setDevicePixelRatio(1.0)
            if img.width() != size or img.height() != size:
                img = img.scaled(
                    size, size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            return img
    return _ico_fallback_image(size)


# ----------------------------------------------------------------------------- PNG exports

def ensure_pngs(icon: QIcon) -> dict[int, str]:
    """
    Write the icon as PNG files in the user data dir and return {size: path}.
    Used for the in-app logo (QML) and the Linux launcher. Frames stored in the .ico are copied
    byte-for-byte (no resampling); missing sizes are rendered from the .ico.
    """
    out_dir = Path(data_dir()) / "icon"
    out_dir.mkdir(parents=True, exist_ok=True)
    src = icon_file()
    sig = _source_sig()
    stamp = out_dir / "source.txt"
    try:
        stale = stamp.read_text(encoding="utf-8") != sig
    except OSError:
        stale = True

    frames = _ico_png_frames(src) if src else {}
    paths: dict[int, str] = {}
    for sz in PNG_SIZES:
        p = out_dir / f"app-{sz}.png"
        if stale or not p.exists():
            if sz in frames:
                p.write_bytes(frames[sz])
            else:
                _render(icon, sz).save(str(p), "PNG")
        paths[sz] = str(p)
    if stale:
        try:
            stamp.write_text(sig, encoding="utf-8")
        except OSError:
            pass
    return paths


def logo_url(pngs: dict[int, str]) -> str:
    """file:// URL of the big PNG, for QML `Image { source: LogoUrl }`."""
    return QUrl.fromLocalFile(pngs[LOGO_SIZE]).toEncoded().data().decode("ascii")


# ----------------------------------------------------------------------------- per-OS hooks

def set_windows_app_id() -> None:
    """Windows: own taskbar identity, so the taskbar shows OUR icon instead of python.exe's."""
    if not IS_WIN:
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


# ----------------------------------------------------------------------------- apply

def apply_to_app(app: QGuiApplication) -> tuple[QIcon, str]:
    """
    Call once, right after QGuiApplication is created and before any window exists.
    Returns (icon, logo_url).
    """
    if IS_LINUX:
        # Crucial for Wayland: sets xdg_toplevel app_id to match DESKTOP_ID.desktop
        try:
            app.setDesktopFileName(DESKTOP_ID)
        except Exception:
            pass

    icon = load_app_icon()
    pngs = ensure_pngs(icon)
    app.setWindowIcon(icon)
    return icon, logo_url(pngs)


def apply_to_windows(icon: QIcon, roots) -> None:
    """Explicitly stamp the icon on the windows the QML engine created."""
    for obj in roots:
        if hasattr(obj, "setIcon"):
            obj.setIcon(icon)