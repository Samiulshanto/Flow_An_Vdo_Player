"""App-wide constants: identity, file types, theme colours and default settings."""
from __future__ import annotations

import sys

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

APP_NAME = "Flow~"
APP_VERSION = "1.1.0"
APP_ID = "Flow.MediaPlayer"          # Windows AppUserModelID (taskbar grouping + icon)
DESKTOP_ID = "flow-media-player"     # Linux .desktop id / Wayland app_id

# The ONE icon file the whole app uses. Replace this file to re-brand everything.
ICON_FILE = "icons/app_master.ico"


VIDEO_EXTS = [
    "mp4", "m4v", "mkv", "avi", "mov", "webm", "flv", "m2ts", "mts",
    "wmv", "mpg", "mpeg", "3gp", "ogv", "vob", "asf", "divx"
]
AUDIO_EXTS = [
    "mp3", "flac", "wav", "aac", "m4a", "ogg", "oga", "opus", "wma",
    "aiff", "ape", "mka"
]
MEDIA_EXTS = set(VIDEO_EXTS + AUDIO_EXTS)
STREAM_SCHEMES = ("http", "https", "rtsp", "rtmp")
MAX_RECENT = 6


def _glob(exts):
    return " ".join(f"*.{e}" for e in exts)


FILE_FILTERS = [
    f"All media ({_glob(VIDEO_EXTS + AUDIO_EXTS)})",
    f"Video ({_glob(VIDEO_EXTS)})",
    f"Audio ({_glob(AUDIO_EXTS)})",
    "All files (*)",
]

SUBTITLE_FILTERS = [
    "Subtitles (*.srt *.ass *.ssa *.vtt *.sub)",
    "All files (*)",
]

# Picture presets. Values are written into the `fx*` settings when a preset is picked.
FX_PRESETS = {
    "off":       {"fxBrightness": 0.0,   "fxContrast": 0.0,  "fxSaturation": 0.0,   "fxWarmth": 0.0,  "fxVignette": 0.0,  "fxLetterbox": False},
    "hdr":       {"fxBrightness": 0.04,  "fxContrast": 0.22, "fxSaturation": 0.20,  "fxWarmth": 0.0,  "fxVignette": 0.0,  "fxLetterbox": False},
    "cinematic": {"fxBrightness": -0.03, "fxContrast": 0.16, "fxSaturation": -0.10, "fxWarmth": 0.35, "fxVignette": 0.45, "fxLetterbox": False},
    "vibrant":   {"fxBrightness": 0.02,  "fxContrast": 0.10, "fxSaturation": 0.45,  "fxWarmth": 0.0,  "fxVignette": 0.0,  "fxLetterbox": False},
}

THEME = {
    "accent": "#ffffff",
    "panel": "#d92a2a2a",
    "panelDeep": "#1e1e1e",
    "hairline": "#1fffffff",
    "hairlineStrong": "#33ffffff",
    "text": "#f5f5f5",
    "textDim": "#a0a0a0",
    "textFaint": "#6e6e6e",
    "segOn": "#ffffff",
    "segBuf": "#666666",
    "segOff": "#333333",
    "hover": "#1fffffff",
    "press": "#33ffffff",
    "danger": "#ffffff",
    "mono": "monospace",
}

DEFAULTS = {
    # appearance
    "panelOpacity": 0.85,
    "showRemaining": True,
    # motion / physics
    "physics": True,
    "stiffness": 3.2,
    "bounce": 0.55,
    "hoverScale": 0.12,
    "magnet": 0.25,
    "waveBars": True,
    "vizStyle": "both",
    # playback
    "seekSmall": 5,
    "seekLarge": 30,
    "volStep": 5,
    "wheelVolume": True,
    "autoAdvance": True,
    # subtitles
    "autoSubs": True,
    "subSize": 1.0,
    "subBox": False,
    # picture (see FX_PRESETS)
    "fxPreset": "off",
    "fxBrightness": 0.0,
    "fxContrast": 0.0,
    "fxSaturation": 0.0,
    "fxWarmth": 0.0,
    "fxVignette": 0.0,
    "fxLetterbox": False,
    # interface
    "hideDelay": 3.0,
    "tooltips": True,
    "notifications": True,
    "openLibrary": True,
    "scanOnLaunch": True,
    "scanDepth": 12,
    "alwaysOnTop": False,
}
