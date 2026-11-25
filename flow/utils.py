"""Small pure helpers shared by the player and the library."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QLocale
from PySide6.QtMultimedia import QMediaMetaData

from .constants import AUDIO_EXTS, MEDIA_EXTS


def media_kind(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return "audio" if ext in AUDIO_EXTS else "video"


def natural_name(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def fmt_size(n: int) -> str:
    v = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024 or unit == "TB":
            return f"{int(v)} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024
    return ""


def natural_key(p: Path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]


def language_of(md: QMediaMetaData):
    try:
        v = md.value(QMediaMetaData.Key.Language)
    except Exception:
        return "", ""
    if v is None:
        return "", ""
    if isinstance(v, str):
        return v, v
    try:
        lang = QLocale.Language(int(getattr(v, "value", v)))
        if lang in (QLocale.Language.AnyLanguage, QLocale.Language.C):
            return "", ""
        name = QLocale.languageToString(lang)
        code = ""
        try:
            code = QLocale.languageToCode(lang, QLocale.LanguageCodeType.ISO639Part3)
        except Exception:
            pass
        if not code:
            code = QLocale(lang).bcp47Name()
        return code, name
    except Exception:
        return "", ""


# ----------------------------------------------------------------------------- library classification
_EXTRA_WORDS = re.compile(
    r"(?<![a-z0-9])(trailers?|teasers?|samples?|featurettes?|behind[ ._-]?the[ ._-]?scenes|"
    r"deleted[ ._-]?scenes?|bloopers?|gag[ ._-]?reel|making[ ._-]?of|extras?|bonus|interviews?|"
    r"promo|specials?|recap|ncop|nced)(?![a-z0-9])", re.I)
_EXTRA_DIRS = {"extras", "extra", "featurettes", "behind the scenes", "deleted scenes", "trailers",
               "samples", "sample", "bonus", "bonus features", "specials", "interviews", "bloopers"}
_SE = re.compile(r"(?<![a-z0-9])s(\d{1,2})[ ._-]?e(\d{1,3})(?![a-z0-9])", re.I)
_NXN = re.compile(r"(?<![a-z0-9])(\d{1,2})x(\d{2,3})(?![a-z0-9])", re.I)
_SEASON_EP = re.compile(r"season[ ._-]?(\d{1,2})[ ._-]*(?:episode|ep|e)[ ._-]?(\d{1,3})", re.I)
_EP = re.compile(r"(?<![a-z0-9])(?:ep|episode)[ ._-]?(\d{1,3})(?![a-z0-9])", re.I)
_ANIME = re.compile(r"^\[[^\]]+\][ ._]*(.+?)[ ._]*-[ ._]*(\d{2,4})(?:v\d)?(?![0-9a-z])", re.I)
_SEASON_DIR = re.compile(r"^(?:season|series|s)[ ._-]?(\d{1,2})$", re.I)


def _clean_title(t: str) -> str:
    t = re.sub(r"[._]+", " ", t)
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -~")
    return t


def classify(name: str, dirpath: str):
    """-> (category, show, season). category: movies | series | extras | audio."""
    stem, _, ext = name.rpartition(".")
    if not stem:
        stem, ext = name, ""
    if ext.lower() in AUDIO_EXTS:
        return "audio", "", 0
    parts = [p for p in re.split(r"[\\/]+", dirpath) if p]
    here = parts[-1] if parts else ""
    up = parts[-2] if len(parts) > 1 else ""
    if here.lower() in _EXTRA_DIRS or _EXTRA_WORDS.search(stem):
        return "extras", "", 0

    season, show = 0, ""
    m = _SE.search(stem) or _SEASON_EP.search(stem)
    if m:
        season, show = int(m.group(1)), stem[:m.start()]
    else:
        m = _NXN.search(stem)
        if m and not (1900 <= int(m.group(1)) * 100 + int(m.group(2)) <= 2100):
            season, show = int(m.group(1)), stem[:m.start()]
        else:
            m = _ANIME.match(stem)
            if m:
                show = m.group(1)
            else:
                m = _EP.search(stem)
                if m:
                    show = stem[:m.start()]
                else:
                    sd = _SEASON_DIR.match(here)
                    if not sd:
                        return "movies", "", 0
                    season, show = int(sd.group(1)), ""
    show = _clean_title(show)
    sd = _SEASON_DIR.match(here)
    if sd and not season:
        season = int(sd.group(1))
    if not show:
        show = _clean_title(up if sd else here)
    return "series", show or "Unknown show", season


def library_entry(name: str, size: int, dirpath: str):
    """[name, size, category, show, season] or None if the file is not a playable media type."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in MEDIA_EXTS:
        return None
    cat, show, season = classify(name, dirpath)
    return [name, size, cat, show, season]
