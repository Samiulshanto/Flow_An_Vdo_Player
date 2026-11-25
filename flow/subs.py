"""Subtitle engine. No Qt in here, so it can be tested on its own.

Why this exists: Qt's built-in subtitle support only knows what the platform backend can decode,
and it chokes on some files (image-based PGS tracks, compressed MKV tracks, ASS styling...).
Flow~ reads subtitles itself, in this order of preference:

  1. sidecar files next to the video   (.srt .ass .ssa .vtt .sub), several languages are fine
  2. text tracks inside the file       (MKV: built-in reader, MP4/MOV: built-in reader)
  3. anything else the `ffmpeg` binary can convert, if ffmpeg happens to be installed

Image-based tracks (PGS, VobSub, DVB) are detected and listed as unsupported instead of crashing.
"""
from __future__ import annotations

import bisect
import html
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import zlib
from dataclasses import dataclass, field
from pathlib import Path

SIDECAR_EXTS = (".srt", ".ass", ".ssa", ".vtt", ".sub")
TEXT_CODECS = {
    "S_TEXT/UTF8": "srt", "S_TEXT/ASCII": "srt", "S_TEXT/SSA": "ass", "S_TEXT/ASS": "ass",
    "S_TEXT/WEBVTT": "vtt", "S_SSA": "ass", "S_ASS": "ass",
}
IMAGE_CODEC_NAMES = {
    "S_HDMV/PGS": "PGS", "S_VOBSUB": "VobSub", "S_DVBSUB": "DVB", "S_HDMV/TEXTST": "TextST",
    "hdmv_pgs_subtitle": "PGS", "dvd_subtitle": "VobSub", "dvb_subtitle": "DVB",
    "xsub": "XSUB", "dvb_teletext": "Teletext",
}
MAX_CUES = 200_000

LANG_NAMES = {
    "eng": "English", "en": "English", "hin": "Hindi", "hi": "Hindi", "tam": "Tamil", "ta": "Tamil",
    "tel": "Telugu", "te": "Telugu", "kan": "Kannada", "kn": "Kannada", "mal": "Malayalam",
    "ml": "Malayalam", "ben": "Bengali", "bn": "Bengali", "mar": "Marathi", "mr": "Marathi",
    "spa": "Spanish", "es": "Spanish", "fre": "French", "fra": "French", "fr": "French",
    "ger": "German", "deu": "German", "de": "German", "ita": "Italian", "it": "Italian",
    "por": "Portuguese", "pt": "Portuguese", "rus": "Russian", "ru": "Russian",
    "jpn": "Japanese", "ja": "Japanese", "kor": "Korean", "ko": "Korean",
    "chi": "Chinese", "zho": "Chinese", "zh": "Chinese", "ara": "Arabic", "ar": "Arabic",
    "tur": "Turkish", "tr": "Turkish", "dut": "Dutch", "nld": "Dutch", "nl": "Dutch",
    "pol": "Polish", "pl": "Polish", "swe": "Swedish", "sv": "Swedish", "tha": "Thai", "th": "Thai",
    "vie": "Vietnamese", "vi": "Vietnamese", "ind": "Indonesian", "id": "Indonesian",
    "heb": "Hebrew", "he": "Hebrew", "gre": "Greek", "ell": "Greek", "el": "Greek",
    "und": "", "mul": "Multiple", "zxx": "",
}


def lang_name(code: str) -> str:
    code = (code or "").strip().lower()
    if not code:
        return ""
    return LANG_NAMES.get(code, LANG_NAMES.get(code.split("-")[0], code.upper()))


# ----------------------------------------------------------------------------- text helpers
def decode_bytes(raw: bytes) -> str:
    """Bytes -> text for subtitle files of unknown encoding."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", "replace")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", "replace")
    if len(raw) >= 4 and raw[1:2] == b"\x00" and raw[3:4] == b"\x00":     # BOM-less UTF-16 LE
        try:
            return raw.decode("utf-16-le")
        except UnicodeDecodeError:
            pass
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    for enc in ("cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


_TAG = re.compile(r"<[^>]{1,80}>")
_ASS_TAG = re.compile(r"\{[^}]*\}")


def clean_text(s: str, ass: bool = False) -> str:
    """Strip styling so the overlay always shows readable plain text."""
    if ass:
        s = _ASS_TAG.sub("", s)
        s = s.replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
    else:
        s = _ASS_TAG.sub("", s)             # {\an8} also appears in SRT files
    s = _TAG.sub("", s)
    s = html.unescape(s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln).strip()


# ----------------------------------------------------------------------------- text parsers
_SRT_TIME = re.compile(
    r"(\d{1,3}):(\d{1,2}):(\d{1,2})[,.:](\d{1,3})\s*-->\s*(\d{1,3}):(\d{1,2}):(\d{1,2})[,.:](\d{1,3})")
_VTT_TIME = re.compile(
    r"(?:(\d{1,3}):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})\s*-->\s*(?:(\d{1,3}):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})")


def _ms(h, m, s, frac) -> int:
    frac = (frac + "000")[:3]
    return ((int(h or 0) * 60 + int(m)) * 60 + int(s)) * 1000 + int(frac)


def parse_srt(text: str) -> list[tuple[int, int, str]]:
    """SRT, tolerant of missing numbers, odd blank lines, '.' vs ',' and WebVTT-style cues."""
    cues = []
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    lines = text.split("\n")
    i, n = 0, len(lines)
    while i < n:
        m = _SRT_TIME.search(lines[i])
        vm = None if m else _VTT_TIME.search(lines[i])
        if not (m or vm):
            i += 1
            continue
        if m:
            a = _ms(m.group(1), m.group(2), m.group(3), m.group(4))
            b = _ms(m.group(5), m.group(6), m.group(7), m.group(8))
        else:
            a = _ms(vm.group(1), vm.group(2), vm.group(3), vm.group(4))
            b = _ms(vm.group(5), vm.group(6), vm.group(7), vm.group(8))
        i += 1
        body = []
        while i < n and lines[i].strip() != "":
            if _SRT_TIME.search(lines[i]) or _VTT_TIME.search(lines[i]):
                break
            body.append(lines[i])
            i += 1
        # a bare cue number belonging to the NEXT block can sneak in when blank lines are missing
        if body and re.fullmatch(r"\d+", body[-1].strip()) and i < n and (
                _SRT_TIME.search(lines[i]) or _VTT_TIME.search(lines[i])):
            body.pop()
        txt = clean_text("\n".join(body))
        if txt and b >= a:
            cues.append((a, b, txt))
    return cues


def parse_vtt(text: str) -> list[tuple[int, int, str]]:
    text = re.sub(r"(?m)^(WEBVTT.*|NOTE\b.*|STYLE\b.*|REGION\b.*)$", "", text.lstrip("\ufeff"))
    return parse_srt(text)


def _ass_time(s: str) -> int:
    m = re.match(r"\s*(\d+):(\d{1,2}):(\d{1,2})[.:](\d{1,3})", s)
    if not m:
        raise ValueError(s)
    frac = m.group(4)
    ms = int(frac) * 10 if len(frac) <= 2 else int((frac + "00")[:3])
    return ((int(m.group(1)) * 60 + int(m.group(2))) * 60 + int(m.group(3))) * 1000 + ms


def parse_ass(text: str) -> list[tuple[int, int, str]]:
    """ASS / SSA 'Dialogue:' lines. Drawing commands (\\p1) and empty lines are dropped."""
    cues = []
    fmt = ["layer", "start", "end", "style", "name", "marginl", "marginr", "marginv", "effect", "text"]
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        low = line.lower()
        if low.startswith("format:") and "text" in low and "start" in low:
            fmt = [p.strip().lower() for p in line.split(":", 1)[1].split(",")]
            continue
        if not low.startswith("dialogue:"):
            continue
        body = line.split(":", 1)[1].lstrip()
        parts = body.split(",", len(fmt) - 1)
        if len(parts) < len(fmt):
            continue
        row = dict(zip(fmt, parts))
        try:
            a, b = _ass_time(row["start"]), _ass_time(row["end"])
        except (KeyError, ValueError):
            continue
        t = row.get("text", "")
        if re.search(r"\\p[1-9]", t):
            continue
        txt = clean_text(t, ass=True)
        if txt and b >= a:
            cues.append((a, b, txt))
    return cues


def parse_microdvd(text: str, fps: float = 23.976) -> list[tuple[int, int, str]]:
    cues = []
    for ln in text.splitlines():
        m = re.match(r"\{(\d+)\}\{(\d+)\}(.*)", ln.strip())
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if not cues and a == 1 and b == 1:     # first line often carries the fps
            try:
                fps = float(m.group(3))
            except ValueError:
                pass
            continue
        txt = clean_text(m.group(3).replace("|", "\n"))
        if txt:
            cues.append((int(a * 1000 / fps), int(b * 1000 / fps), txt))
    return cues


def parse_text(text: str, kind: str) -> list[tuple[int, int, str]]:
    if kind == "ass":
        return parse_ass(text)
    if kind == "vtt":
        return parse_vtt(text)
    if kind == "sub":
        return parse_microdvd(text)
    return parse_srt(text)


def parse_file(path: str) -> list[tuple[int, int, str]]:
    ext = os.path.splitext(path)[1].lower()
    with open(path, "rb") as f:
        raw = f.read(32 * 1024 * 1024)
    text = decode_bytes(raw)
    head = text[:2000].lower()
    if ext in (".ass", ".ssa") or "[script info]" in head:
        kind = "ass"
    elif ext == ".vtt" or head.lstrip().startswith("webvtt"):
        kind = "vtt"
    elif ext == ".sub" and re.search(r"\{\d+\}\{\d+\}", text[:2000]):
        kind = "sub"
    else:
        kind = "srt"
    cues = parse_text(text, kind)
    if not cues and kind != "srt":
        cues = parse_srt(text)
    return cues


# ----------------------------------------------------------------------------- track object
@dataclass
class SubTrack:
    """One selectable subtitle track. `cues` fills in while a background scan is still running."""
    label: str
    lang: str = ""
    source: str = "embedded"          # embedded | file
    codec: str = ""
    kind: str = "text"                # text | image
    default: bool = False
    forced: bool = False
    path: str = ""
    key: int = -1                     # container track id / stream index
    cues: list = field(default_factory=list)
    done: bool = True
    error: str = ""
    _starts: list = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def usable(self) -> bool:
        return self.kind == "text" and not self.error

    def add(self, a: int, b: int, text: str):
        with self._lock:
            if len(self.cues) >= MAX_CUES:
                return
            if not self._starts or a >= self._starts[-1]:
                self._starts.append(a)
                self.cues.append((a, b, text))
            else:
                i = bisect.bisect_right(self._starts, a)
                self._starts.insert(i, a)
                self.cues.insert(i, (a, b, text))

    def set_cues(self, cues):
        cues = sorted(cues, key=lambda c: c[0])
        with self._lock:
            self.cues = list(cues)[:MAX_CUES]
            self._starts = [c[0] for c in self.cues]

    def text_at(self, ms: int) -> str:
        """Text visible at `ms` (several cues may overlap)."""
        with self._lock:
            if not self.cues:
                return ""
            i = bisect.bisect_right(self._starts, ms) - 1
            out, seen = [], set()
            for j in range(i, max(-1, i - 40), -1):
                a, b, t = self.cues[j]
                if a <= ms < b and t not in seen:
                    seen.add(t)
                    out.append(t)
            out.reverse()
            return "\n".join(out)

    def info(self, index: int) -> dict:
        label = self.label
        if self.kind == "image":
            label += "  (image subtitles are not supported)"
        elif self.error:
            label += "  (unreadable)"
        return {"index": index, "tag": self.lang, "label": label, "usable": self.usable,
                "source": self.source, "default": self.default, "forced": self.forced}


# ----------------------------------------------------------------------------- Matroska reader
ID_EBML = 0x1A45DFA3
ID_SEGMENT = 0x18538067
ID_INFO = 0x1549A966
ID_TIMESCALE = 0x2AD7B1
ID_TRACKS = 0x1654AE6B
ID_TRACKENTRY = 0xAE
ID_TRACKNUM = 0xD7
ID_TRACKTYPE = 0x83
ID_CODECID = 0x86
ID_CODECPRIV = 0x63A2
ID_LANG = 0x22B59C
ID_LANGBCP = 0x22B59D
ID_NAME = 0x536E
ID_FLAGDEF = 0x88
ID_FLAGFORCED = 0x55AA
ID_CONTENTENC = 0x6D80
ID_CLUSTER = 0x1F43B675
ID_CLUSTERTC = 0xE7
ID_SIMPLEBLOCK = 0xA3
ID_BLOCKGROUP = 0xA0
ID_BLOCK = 0xA1
ID_BLOCKDUR = 0x9B
ID_CUES = 0x1C53BB6B
ID_TOP_LEVEL = {0x114D9B74, ID_INFO, ID_TRACKS, ID_CLUSTER, ID_CUES, 0x1043A770, 0x1254C367}


def _read_id(f):
    b = f.read(1)
    if not b:
        return None, 0
    first = b[0]
    if first == 0:
        return None, 1
    ln = 1
    mask = 0x80
    while not (first & mask):
        mask >>= 1
        ln += 1
    rest = f.read(ln - 1)
    if len(rest) != ln - 1:
        return None, ln
    return int.from_bytes(b + rest, "big"), ln


def _read_size(f):
    """-> (size or -1 for unknown, bytes consumed)"""
    b = f.read(1)
    if not b:
        return None, 0
    first = b[0]
    if first == 0:
        return None, 1
    ln = 1
    mask = 0x80
    while not (first & mask):
        mask >>= 1
        ln += 1
    rest = f.read(ln - 1)
    if len(rest) != ln - 1:
        return None, ln
    val = first & (mask - 1)
    for x in rest:
        val = (val << 8) | x
    if val == (1 << (7 * ln)) - 1:
        return -1, ln
    return val, ln


def _children(buf: bytes):
    """Iterate (id, payload) over a small in-memory EBML payload."""
    import io
    f = io.BytesIO(buf)
    while True:
        eid, _ = _read_id(f)
        if eid is None:
            return
        size, _ = _read_size(f)
        if size is None or size < 0:
            return
        yield eid, f.read(size)


def _uint(b: bytes) -> int:
    return int.from_bytes(b, "big") if b else 0


def _parse_track_entry(buf: bytes) -> dict:
    t = {"num": 0, "type": 0, "codec": "", "lang": "", "name": "", "default": True,
         "forced": False, "private": b"", "comp": None}
    for eid, data in _children(buf):
        if eid == ID_TRACKNUM:
            t["num"] = _uint(data)
        elif eid == ID_TRACKTYPE:
            t["type"] = _uint(data)
        elif eid == ID_CODECID:
            t["codec"] = data.decode("ascii", "replace").strip("\x00")
        elif eid == ID_CODECPRIV:
            t["private"] = data
        elif eid == ID_LANG and not t["lang"]:
            t["lang"] = data.decode("ascii", "replace").strip("\x00")
        elif eid == ID_LANGBCP:
            t["lang"] = data.decode("ascii", "replace").strip("\x00")
        elif eid == ID_NAME:
            t["name"] = data.decode("utf-8", "replace").strip("\x00")
        elif eid == ID_FLAGDEF:
            t["default"] = bool(_uint(data))
        elif eid == ID_FLAGFORCED:
            t["forced"] = bool(_uint(data))
        elif eid == ID_CONTENTENC:
            for e2, d2 in _children(data):
                if e2 != 0x6240:                         # ContentEncoding
                    continue
                for e3, d3 in _children(d2):
                    if e3 == 0x5034:                     # ContentCompression
                        algo, settings = 0, b""
                        for e4, d4 in _children(d3):
                            if e4 == 0x4254:
                                algo = _uint(d4)
                            elif e4 == 0x4255:
                                settings = d4
                        t["comp"] = (algo, settings)
    return t


def _decompress(frame: bytes, comp) -> bytes:
    if not comp:
        return frame
    algo, settings = comp
    if algo == 0:                                        # zlib
        try:
            return zlib.decompress(frame)
        except zlib.error:
            try:
                return zlib.decompressobj().decompress(frame)
            except zlib.error:
                return b""
    if algo == 3:                                        # header stripping
        return settings + frame
    return frame


def _ass_header_columns(private: bytes) -> list[str] | None:
    text = decode_bytes(private)
    for ln in text.splitlines():
        if ln.lower().startswith("format:") and "text" in ln.lower() and "start" not in ln.lower():
            return [p.strip().lower() for p in ln.split(":", 1)[1].split(",")]
    return None


def _mkv_ass_block(data: str, columns: list[str] | None) -> str:
    """Matroska stores ASS as 'ReadOrder,Layer,Style,Name,MarginL,MarginR,MarginV,Effect,Text'."""
    parts = data.split(",", 8)
    if len(parts) < 9:
        parts = data.split(",", len(parts) - 1) if parts else [data]
        return clean_text(parts[-1], ass=True) if parts else ""
    if re.search(r"\\p[1-9]", parts[8]):
        return ""
    return clean_text(parts[8], ass=True)


def read_mkv(path: str, want_cues: bool = True, stop: threading.Event | None = None):
    """Yield ('tracks', [track dicts]) once, then ('cue', track_number, start_ms, end_ms, text).

    Reads only the element headers of audio/video blocks and seeks over their payload, so large
    files scan at disk speed. Handles zlib/header-stripping compression and unknown-size clusters.
    """
    with open(path, "rb", buffering=0) as f:
        size_total = os.fstat(f.fileno()).st_size
        eid, _ = _read_id(f)
        if eid != ID_EBML:
            raise ValueError("not a Matroska file")
        sz, _ = _read_size(f)
        if sz is None or sz < 0:
            raise ValueError("bad EBML header")
        f.seek(sz, 1)
        eid, _ = _read_id(f)
        if eid != ID_SEGMENT:
            raise ValueError("no segment")
        _read_size(f)                       # segment size (may be unknown); we just read on to EOF

        timescale = 1_000_000
        tracks: dict[int, dict] = {}
        sub_nums: set[int] = set()
        cluster_tc = 0
        tracks_sent = False

        while True:
            if stop is not None and stop.is_set():
                return
            pos = f.tell()
            eid, il = _read_id(f)
            if eid is None:
                if il == 0 or pos >= size_total:
                    break
                continue
            size, sl = _read_size(f)
            if size is None:
                break
            payload_at = pos + il + sl

            if eid == ID_INFO and size >= 0:
                for e2, d2 in _children(f.read(size)):
                    if e2 == ID_TIMESCALE:
                        timescale = max(1, _uint(d2))
            elif eid == ID_TRACKS and size >= 0:
                for e2, d2 in _children(f.read(size)):
                    if e2 == ID_TRACKENTRY:
                        t = _parse_track_entry(d2)
                        tracks[t["num"]] = t
                sub_nums = {n for n, t in tracks.items()
                            if t["type"] == 17 and t["codec"] in TEXT_CODECS}
                tracks_sent = True
                yield ("tracks", [tracks[k] for k in sorted(tracks)])
                if not (sub_nums and want_cues):
                    return
            elif eid == ID_CLUSTER:
                continue                                    # descend: read children in sequence
            elif eid == ID_CLUSTERTC:
                cluster_tc = _uint(f.read(size))
            elif eid == ID_SIMPLEBLOCK:
                if size < 4:
                    f.seek(payload_at + max(size, 0))
                    continue
                head = f.read(min(size, 16))
                tn, tl = _vint_value(head)
                if tn in sub_nums:
                    f.seek(payload_at)
                    blk = f.read(size)
                    yield from _emit_block(blk, tn, tracks[tn], cluster_tc, timescale, None)
                f.seek(payload_at + size)
            elif eid == ID_BLOCKGROUP and size >= 0:
                head = f.read(min(size, 24))
                # the Block is normally the first child: 0xA1 <size> <track vint> ...
                is_sub = False
                if head[:1] == b"\xa1":
                    bs_len = 1
                    first = head[1] if len(head) > 1 else 0
                    m = 0x80
                    while m and not (first & m):
                        m >>= 1
                        bs_len += 1
                    tn, _ = _vint_value(head[1 + bs_len:])
                    is_sub = tn in sub_nums
                else:
                    is_sub = True                                # unusual layout: inspect fully
                if is_sub:
                    f.seek(payload_at)
                    grp = f.read(size)
                    blk, dur = None, None
                    for e2, d2 in _children(grp):
                        if e2 == ID_BLOCK:
                            blk = d2
                        elif e2 == ID_BLOCKDUR:
                            dur = _uint(d2)
                    if blk:
                        tn, _ = _vint_value(blk)
                        if tn in sub_nums:
                            yield from _emit_block(blk, tn, tracks[tn], cluster_tc, timescale, dur)
                f.seek(payload_at + size)
            elif size < 0:
                continue                                       # unknown-size master we don't need
            else:
                f.seek(payload_at + size)
        if not tracks_sent:
            yield ("tracks", [])


def _vint_value(b: bytes):
    if not b:
        return -1, 0
    first = b[0]
    if first == 0:
        return -1, 1
    ln, mask = 1, 0x80
    while not (first & mask):
        mask >>= 1
        ln += 1
    if len(b) < ln:
        return -1, ln
    val = first & (mask - 1)
    for x in b[1:ln]:
        val = (val << 8) | x
    return val, ln


def _emit_block(blk: bytes, tn: int, track: dict, cluster_tc: int, timescale: int, dur):
    _, tl = _vint_value(blk)
    if tl <= 0 or len(blk) < tl + 3:
        return
    rel = struct.unpack(">h", blk[tl:tl + 2])[0]
    flags = blk[tl + 2]
    frame = blk[tl + 3:]
    if flags & 0x06:                                           # laced subtitle blocks: not used in practice
        return
    frame = _decompress(frame, track.get("comp"))
    if not frame:
        return
    ms_per_tick = timescale / 1_000_000.0
    start = int(round((cluster_tc + rel) * ms_per_tick))
    codec = track["codec"]
    text = decode_bytes(frame)
    if TEXT_CODECS.get(codec) == "ass":
        txt = _mkv_ass_block(text, None)
    elif TEXT_CODECS.get(codec) == "vtt":
        txt = clean_text(text.split("\n\n")[-1] if "-->" not in text else text.split("\n", 1)[-1])
    else:
        txt = clean_text(text)
    if not txt:
        return
    if dur is None:
        dur_ms = 3000
    else:
        dur_ms = max(1, int(round(dur * ms_per_tick)))
    yield ("cue", tn, start, start + dur_ms, txt)


# ----------------------------------------------------------------------------- MP4 / MOV reader
def _mp4_boxes(f, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        hdr = f.read(8)
        if len(hdr) < 8:
            return
        size, typ = struct.unpack(">I4s", hdr)
        head = 8
        if size == 1:
            size = struct.unpack(">Q", f.read(8))[0]
            head = 16
        elif size == 0:
            size = end - pos
        if size < head:
            return
        yield typ.decode("latin-1"), pos + head, min(pos + size, end)
        pos += size


def read_mp4(path: str):
    """-> list of dicts {lang, name, cues, codec} for tx3g / mov_text / wvtt tracks."""
    out = []
    with open(path, "rb") as f:
        total = os.fstat(f.fileno()).st_size
        moov = None
        for typ, a, b in _mp4_boxes(f, 0, total):
            if typ == "moov":
                moov = (a, b)
                break
        if not moov:
            return out
        for typ, a, b in _mp4_boxes(f, *moov):
            if typ != "trak":
                continue
            info = _mp4_track(f, a, b)
            if info:
                out.append(info)
    return out


def _find(f, a, b, path_names):
    cur = [(a, b)]
    for name in path_names:
        nxt = []
        for s, e in cur:
            for typ, aa, bb in _mp4_boxes(f, s, e):
                if typ == name:
                    nxt.append((aa, bb))
        cur = nxt
        if not cur:
            return None
    return cur[0]


def _mp4_track(f, a, b):
    mdia = _find(f, a, b, ["mdia"])
    if not mdia:
        return None
    timescale, lang = 1000, ""
    for typ, aa, bb in _mp4_boxes(f, *mdia):
        if typ == "mdhd":
            f.seek(aa)
            d = f.read(bb - aa)
            ver = d[0]
            toff = 20 if ver == 1 else 12
            loff = 32 if ver == 1 else 20
            timescale = struct.unpack(">I", d[toff:toff + 4])[0] or 1000
            code = struct.unpack(">H", d[loff:loff + 2])[0]
            lang = "".join(chr(((code >> sh) & 0x1F) + 0x60) for sh in (10, 5, 0))
            if not lang.isalpha() or lang == "und":
                lang = ""
        elif typ == "hdlr":
            f.seek(aa)
            d = f.read(min(bb - aa, 64))
            htype = d[8:12]
            if htype not in (b"sbtl", b"text", b"subt", b"clcp"):
                return None
    stbl = _find(f, *mdia, ["minf", "stbl"])
    if not stbl:
        return None
    boxes = {}
    codec = ""
    for typ, aa, bb in _mp4_boxes(f, *stbl):
        f.seek(aa)
        if typ == "stsd":
            d = f.read(min(bb - aa, 64))
            codec = d[12:16].decode("latin-1")
        elif typ in ("stts", "stsz", "stsc", "stco", "co64", "ctts"):
            boxes[typ] = f.read(bb - aa)
    if codec not in ("tx3g", "text", "wvtt") or "stsz" not in boxes:
        return {"lang": lang, "name": "", "cues": [], "codec": codec, "image": True} if codec else None

    stsz = boxes["stsz"]
    fixed, count = struct.unpack(">II", stsz[4:12])
    sizes = [fixed] * count if fixed else list(struct.unpack(f">{count}I", stsz[12:12 + 4 * count]))
    stts = boxes.get("stts", b"\0" * 8)
    n = struct.unpack(">I", stts[4:8])[0]
    durs = []
    for i in range(n):
        c, d = struct.unpack(">II", stts[8 + 8 * i:16 + 8 * i])
        durs += [d] * c
    if "co64" in boxes:
        n = struct.unpack(">I", boxes["co64"][4:8])[0]
        offs = list(struct.unpack(f">{n}Q", boxes["co64"][8:8 + 8 * n]))
    else:
        c = boxes.get("stco", b"\0" * 8)
        n = struct.unpack(">I", c[4:8])[0]
        offs = list(struct.unpack(f">{n}I", c[8:8 + 4 * n]))
    stsc = boxes.get("stsc", b"\0" * 8)
    n = struct.unpack(">I", stsc[4:8])[0]
    runs = [struct.unpack(">III", stsc[8 + 12 * i:20 + 12 * i]) for i in range(n)]

    # sample index -> file offset
    sample_off = []
    si = 0
    for ci, base in enumerate(offs):
        per = 1
        for first, spc, _ in runs:
            if ci + 1 >= first:
                per = spc
        pos = base
        for _ in range(per):
            if si >= len(sizes):
                break
            sample_off.append(pos)
            pos += sizes[si]
            si += 1

    cues = []
    t = 0
    for i, size in enumerate(sizes):
        d = durs[i] if i < len(durs) else 0
        start = t
        t += d
        if size <= 2 or i >= len(sample_off):
            continue
        f.seek(sample_off[i])
        raw = f.read(size)
        if codec == "wvtt":
            txt = _wvtt_text(raw)
        else:
            ln = struct.unpack(">H", raw[:2])[0]
            txt = clean_text(decode_bytes(raw[2:2 + ln]))
        if txt:
            cues.append((int(start * 1000 / timescale), int((start + d) * 1000 / timescale), txt))
    return {"lang": lang, "name": "", "cues": cues, "codec": codec, "image": False}


def _wvtt_text(raw: bytes) -> str:
    pos, parts = 0, []
    while pos + 8 <= len(raw):
        size, typ = struct.unpack(">I4s", raw[pos:pos + 8])
        if size < 8:
            break
        if typ == b"payl":
            parts.append(decode_bytes(raw[pos + 8:pos + size]))
        pos += size
    return clean_text("\n".join(parts))


# ----------------------------------------------------------------------------- ffmpeg fallback
def _flags():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def find_tool(name: str) -> str | None:
    p = shutil.which(name)
    if p:
        return p
    here = Path(__file__).resolve().parent.parent
    for cand in (here / "bin" / name, here / "bin" / (name + ".exe")):
        if cand.is_file():
            return str(cand)
    return None


def ffprobe_subs(path: str, timeout: int = 20) -> list[dict]:
    exe = find_tool("ffprobe")
    if not exe:
        return []
    try:
        p = subprocess.run([exe, "-v", "error", "-select_streams", "s", "-show_entries",
                            "stream=index,codec_name:stream_tags=language,title:stream_disposition=default,forced",
                            "-of", "json", path], capture_output=True, timeout=timeout,
                           creationflags=_flags())
        data = json.loads(p.stdout.decode("utf-8", "replace") or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    res = []
    for pos, s in enumerate(data.get("streams", [])):
        tags = s.get("tags") or {}
        disp = s.get("disposition") or {}
        res.append({"pos": pos, "index": s.get("index", pos), "codec": s.get("codec_name", ""),
                    "lang": tags.get("language", ""), "title": tags.get("title", ""),
                    "default": bool(disp.get("default")), "forced": bool(disp.get("forced"))})
    return res


def ffmpeg_extract(path: str, pos: int, timeout: int = 600) -> list[tuple[int, int, str]]:
    exe = find_tool("ffmpeg")
    if not exe:
        return []
    try:
        p = subprocess.run([exe, "-v", "error", "-nostdin", "-i", path, "-map", f"0:s:{pos}",
                            "-f", "srt", "-"], capture_output=True, timeout=timeout,
                           creationflags=_flags())
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_srt(decode_bytes(p.stdout))


# ----------------------------------------------------------------------------- discovery + loader
def find_sidecars(video_path: str) -> list[str]:
    """Subtitle files that belong to this video: same name, or name + language suffix, or in a
    Subs/ Subtitles/ folder next to it."""
    p = Path(video_path)
    stem = p.stem.lower()
    found = []
    dirs = [p.parent]
    for sub in ("Subs", "subs", "Subtitles", "subtitles", "Sub", "sub"):
        d = p.parent / sub
        if d.is_dir():
            dirs.append(d)
            nested = d / p.stem
            if nested.is_dir():
                dirs.append(nested)
    for d in dirs:
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for name in names:
            low = name.lower()
            if not low.endswith(SIDECAR_EXTS):
                continue
            base = os.path.splitext(low)[0]
            in_subdir = d != p.parent
            if base == stem or base.startswith(stem + ".") or base.startswith(stem + "_") \
                    or base.startswith(stem + "-") or base.startswith(stem + " ") or in_subdir:
                full = str(d / name)
                if full not in found:
                    found.append(full)
    return found


def _sidecar_label(path: str, video_path: str) -> tuple[str, str]:
    base = os.path.splitext(os.path.basename(path))[0]
    stem = Path(video_path).stem
    suffix = base[len(stem):].strip(" ._-") if base.lower().startswith(stem.lower()) else base
    code = ""
    for tok in re.split(r"[ ._\-\[\]()]+", suffix.lower()):
        if tok in LANG_NAMES and LANG_NAMES[tok]:
            code = tok
            break
    name = lang_name(code)
    label = f"{name or 'File'} \u00b7 {os.path.basename(path)}"
    return code, label


class SubtitleSet:
    """All subtitle tracks for one video. Built on a worker thread; poll `version` for changes."""

    def __init__(self, video_path: str):
        self.path = video_path
        self.tracks: list[SubTrack] = []
        self.version = 0
        self.finished = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # -- lifecycle
    def start(self):
        self._thread = threading.Thread(target=self._run, name="flow-subs", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _bump(self):
        with self._lock:
            self.version += 1

    def add_file(self, path: str) -> SubTrack | None:
        """Load a subtitle file picked by the user (any time)."""
        try:
            cues = parse_file(path)
        except OSError:
            return None
        code, label = _sidecar_label(path, self.path)
        tr = SubTrack(label=label if self.path else os.path.basename(path), lang=code,
                      source="file", path=path)
        if not cues:
            tr.error = "no cues"
        tr.set_cues(cues)
        with self._lock:
            self.tracks.append(tr)
        self._bump()
        return tr

    # -- worker
    def _run(self):
        try:
            self._load_sidecars()
            self._load_embedded()
        except Exception as e:                     # never let a bad file take the app down
            print(f"[Flow~] subtitles: {type(e).__name__}: {e}", file=sys.stderr)
        finally:
            self.finished = True
            self._bump()

    def _load_sidecars(self):
        for sp in find_sidecars(self.path):
            if self._stop.is_set():
                return
            try:
                self.add_file(sp)
            except Exception as e:
                print(f"[Flow~] subtitles: {sp}: {e}", file=sys.stderr)

    def _load_embedded(self):
        ext = os.path.splitext(self.path)[1].lower()
        if ext in (".mkv", ".mka", ".webm"):
            if self._load_mkv():
                return
        elif ext in (".mp4", ".m4v", ".mov", ".3gp"):
            if self._load_mp4():
                return
        self._load_ffmpeg()

    def _load_mkv(self) -> bool:
        by_num: dict[int, SubTrack] = {}
        try:
            for item in read_mkv(self.path, stop=self._stop):
                if item[0] == "tracks":
                    for t in item[1]:
                        if t["type"] != 17:
                            continue
                        codec = t["codec"]
                        lang = t["lang"] if t["lang"] not in ("und", "") else ""
                        name = t["name"]
                        base = " \u00b7 ".join(dict.fromkeys(
                            x for x in (lang_name(lang), name) if x)) or f"Subtitle {len(self.tracks) + 1}"
                        if t["forced"]:
                            base += " (forced)"
                        tr = SubTrack(label=base, lang=lang, codec=codec, key=t["num"],
                                      default=t["default"], forced=t["forced"])
                        if codec in TEXT_CODECS:
                            tr.done = False
                            by_num[t["num"]] = tr
                        else:
                            tr.kind = "image"
                            tr.label = f"{base} [{IMAGE_CODEC_NAMES.get(codec, codec.split('/')[-1])}]"
                        with self._lock:
                            self.tracks.append(tr)
                    self._bump()
                elif item[0] == "cue":
                    tr = by_num.get(item[1])
                    if tr:
                        tr.add(item[2], item[3], item[4])
                if self._stop.is_set():
                    break
            for tr in by_num.values():
                tr.done = True
            self._bump()
            return True
        except (OSError, ValueError, struct.error, IndexError) as e:
            print(f"[Flow~] subtitles: mkv reader failed ({e}), trying ffmpeg", file=sys.stderr)
            for tr in by_num.values():
                tr.done = True
            return bool(by_num)

    def _load_mp4(self) -> bool:
        try:
            tracks = read_mp4(self.path)
        except (OSError, ValueError, struct.error, IndexError) as e:
            print(f"[Flow~] subtitles: mp4 reader failed ({e}), trying ffmpeg", file=sys.stderr)
            return False
        for t in tracks:
            lang = t["lang"]
            base = lang_name(lang) or f"Subtitle {len(self.tracks) + 1}"
            tr = SubTrack(label=base, lang=lang, codec=t["codec"])
            if t.get("image"):
                tr.kind = "image"
                tr.label = f"{base} [{t['codec']}]"
            else:
                tr.set_cues(t["cues"])
            with self._lock:
                self.tracks.append(tr)
        self._bump()
        return bool(tracks)

    def _load_ffmpeg(self):
        for s in ffprobe_subs(self.path):
            if self._stop.is_set():
                return
            codec = s["codec"]
            base = " \u00b7 ".join(dict.fromkeys(
                x for x in (lang_name(s["lang"]), s["title"]) if x)) or f"Subtitle {s['pos'] + 1}"
            tr = SubTrack(label=base, lang=s["lang"], codec=codec, key=s["pos"],
                          default=s["default"], forced=s["forced"])
            if codec in IMAGE_CODEC_NAMES:
                tr.kind = "image"
                tr.label = f"{base} [{IMAGE_CODEC_NAMES[codec]}]"
            else:
                tr.done = False
            with self._lock:
                self.tracks.append(tr)
            self._bump()
            if tr.kind == "text":
                tr.set_cues(ffmpeg_extract(self.path, s["pos"]))
                tr.done = True
                if not tr.cues:
                    tr.error = "empty"
                self._bump()

    # -- queries
    def snapshot(self) -> list[SubTrack]:
        with self._lock:
            return list(self.tracks)

    def best_default(self, prefer_lang: str = "") -> int:
        """Index of the track to switch on automatically, or -1."""
        tracks = self.snapshot()
        usable = [(i, t) for i, t in enumerate(tracks) if t.usable]
        if not usable:
            return -1
        for i, t in usable:
            if t.source == "file" and (not prefer_lang or t.lang.startswith(prefer_lang[:2])):
                return i
        for i, t in usable:
            if t.default and not t.forced:
                return i
        return -1
