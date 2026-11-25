"""PlayerController: queue, playback, resume points, volume/speed. Exposed to QML as `player`."""
from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Property, QObject, QSettings, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudio, QAudioOutput, QMediaDevices, QMediaMetaData, QMediaPlayer

from .constants import FILE_FILTERS, MAX_RECENT, MEDIA_EXTS, STREAM_SCHEMES, SUBTITLE_FILTERS
from .subs import SIDECAR_EXTS, SubtitleSet
from .utils import language_of, media_kind, natural_key

if TYPE_CHECKING:
    from .prefs import Prefs


def url_str(url: QUrl) -> str:
    """Fully percent-encoded URL text, so names containing '#', '%' or '?' survive a round trip."""
    return url.toEncoded().data().decode("ascii")


class PlayerController(QObject):
    positionChanged = Signal()
    durationChanged = Signal()
    playingChanged = Signal()
    volumeChanged = Signal()
    mutedChanged = Signal()
    speedChanged = Signal()
    mediaChanged = Signal()
    queueChanged = Signal()
    tracksChanged = Signal()
    recentChanged = Signal()
    bufferChanged = Signal()
    modeChanged = Signal()
    folderChanged = Signal()
    errorMessage = Signal(str)
    trackStarted = Signal(str)
    jumped = Signal()                 # the play position was moved (seek / new file)
    subtitleChanged = Signal()
    subDelayChanged = Signal()

    def __init__(self, settings: QSettings, native_frame: bool = False, prefs: "Prefs | None" = None):
        super().__init__()
        self._s = settings
        self._native_frame = native_frame
        self._prefs = prefs

        self._queue: list[dict] = []
        self._index = -1
        self._pos = 0
        self._dur = 0
        self._playing = False
        self._has_video = False
        self._base_title = ""
        self._meta_title = ""
        self._tracks: list[dict] = []
        self._active_track = -1
        self._subs: list[dict] = []
        self._active_sub = -1
        self._subset: SubtitleSet | None = None
        self._sub_ver = -1
        self._sub_text = ""
        self._sub_delay = 0
        self._sub_auto_done = False
        self._buffer = 0.0
        self._buffering = False
        self._last_folder = str(settings.value("lastFolder", "") or "")

        self._volume = self._num("volume", 0.8, 0.0, 1.0)
        self._speed = self._num("speed", 1.0, 0.25, 4.0)
        self._muted = False
        self._shuffle = str(settings.value("shuffle", "false")).lower() in ("true", "1")
        self._repeat = int(self._num("repeat", 0, 0, 2))
        self._recent: list[str] = [str(r) for r in self._json("recentJson", [])][:MAX_RECENT]
        self._pending_seek = 0
        self._last_save = 0.0
        try:
            raw = self._json("resume", {})
            self._resume: dict = {k: [int(v[0]), int(v[1])] for k, v in raw.items() if k in self._recent}
        except Exception:
            self._resume = {}

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        # Follow the system's default speaker/earphone, also when it changes while the app runs.
        self._devices = QMediaDevices(self)
        self._devices.audioOutputsChanged.connect(lambda: QTimer.singleShot(300, self._follow_default_output))
        self._follow_default_output()
        self._player.setAudioOutput(self._audio)
        self._apply_volume()
        self._player.setPlaybackRate(self._speed)

        self._player.playbackStateChanged.connect(self._on_state)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.durationChanged.connect(self._on_duration)
        self._player.hasVideoChanged.connect(self._on_has_video)
        self._player.tracksChanged.connect(self._refresh_tracks)
        self._player.metaDataChanged.connect(self._on_meta)
        self._player.bufferProgressChanged.connect(self._on_buffer)
        self._player.errorOccurred.connect(self._on_error)

        self._ticker = QTimer(self)
        self._ticker.setInterval(150)
        self._ticker.timeout.connect(self._tick)

        # Subtitles are handled by Flow~ itself (flow/subs.py), never by Qt's own subtitle API.
        self._sub_timer = QTimer(self)
        self._sub_timer.setInterval(80)
        self._sub_timer.timeout.connect(self._sub_tick)

    @property
    def media_player(self) -> QMediaPlayer:
        return self._player

    def _json(self, key, default):
        """Read a JSON value from settings (INI turns strings with commas into lists, so rejoin)."""
        raw = self._s.value(key, None)
        if isinstance(raw, (list, tuple)):
            raw = ",".join(str(x) for x in raw)
        try:
            val = json.loads(str(raw)) if raw else default
        except ValueError:
            return default
        return val if isinstance(val, type(default)) else default

    def _follow_default_output(self):
        try:
            dev = QMediaDevices.defaultAudioOutput()
            if not dev.isNull() and dev != self._audio.device():
                self._audio.setDevice(dev)
        except Exception:
            pass

    def _num(self, key, default, lo, hi):
        try:
            v = float(self._s.value(key, default))
        except (TypeError, ValueError):
            v = float(default)
        return max(lo, min(hi, v))

    @staticmethod
    def _to_url(x) -> QUrl:
        if isinstance(x, QUrl):
            return x
        s = str(x)
        if os.path.exists(s):
            return QUrl.fromLocalFile(os.path.abspath(s))
        return QUrl(s)

    @staticmethod
    def _entry(url: QUrl):
        if url.isLocalFile():
            p = Path(url.toLocalFile())
            return {"url": url_str(url), "title": p.stem, "folder": p.parent.name or str(p.parent)}
        return {"url": url_str(url), "title": url.fileName() or url.host(), "folder": url.host()}

    def _collect(self, urls) -> list[dict]:
        out = []
        for u in urls or []:
            url = self._to_url(u)
            if url.isLocalFile():
                p = Path(url.toLocalFile())
                if p.is_dir():
                    try:
                        files = sorted((f for f in p.iterdir()
                                        if f.is_file() and f.suffix.lower().lstrip(".") in MEDIA_EXTS),
                                       key=natural_key)
                    except OSError:
                        files = []
                    out += [self._entry(QUrl.fromLocalFile(str(f))) for f in files]
                elif p.is_file():
                    out.append(self._entry(url))
            elif url.scheme() in STREAM_SCHEMES:
                out.append(self._entry(url))
        return out

    def _apply_volume(self):
        try:
            lin = QAudio.convertVolume(self._volume, QAudio.VolumeScale.LogarithmicVolumeScale,
                                       QAudio.VolumeScale.LinearVolumeScale)
        except Exception:
            lin = self._volume ** 2
        self._audio.setVolume(lin)
        self._audio.setMuted(self._muted)

    def _refresh_title(self):
        self._meta_title = ""
        if not self._has_video:
            md = self._player.metaData()
            t = md.stringValue(QMediaMetaData.Key.Title)
            a = (md.stringValue(QMediaMetaData.Key.ContributingArtist)
                 or md.stringValue(QMediaMetaData.Key.AlbumArtist))
            if t:
                self._meta_title = f"{a} \u2014 {t}" if a else t
        self.mediaChanged.emit()

    def _tick(self):
        p = self._player.position()
        if p != self._pos:
            self._pos = p
            self.positionChanged.emit()
        now = time.monotonic()
        if self._playing and now - self._last_save > 5.0:
            self._last_save = now
            self._save_resume()

    def _on_state(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        if playing:
            self._ticker.start()
        else:
            self._ticker.stop()
            self._tick()
            if state == QMediaPlayer.PlaybackState.PausedState:
                self._save_resume(notify=True)
        if playing != self._playing:
            self._playing = playing
            self.playingChanged.emit()

    def _on_status(self, status):
        S = QMediaPlayer.MediaStatus
        buffering = status in (S.LoadingMedia, S.StalledMedia, S.BufferingMedia)
        if buffering != self._buffering:
            self._buffering = buffering
            self.bufferChanged.emit()
        if status in (S.LoadedMedia, S.BufferedMedia):
            self._player.setPlaybackRate(self._speed)
            if self._pending_seek > 0:
                ms, self._pending_seek = self._pending_seek, 0
                self._player.setPosition(ms)
                self._pos = ms
                self.positionChanged.emit()
            self._sync_video()
            self._refresh_tracks()
        elif status == S.EndOfMedia:
            self._on_end()
        elif status == S.InvalidMedia:
            self.errorMessage.emit("Can\u2019t play this file")
            if self._index + 1 < len(self._queue):
                QTimer.singleShot(400, self.next)

    def _on_duration(self, d):
        self._dur = int(d)
        self.durationChanged.emit()

    def _on_has_video(self, v):
        self._sync_video(bool(v))

    def _sync_video(self, v=None):
        """Keep hasVideo in step with the real player. Qt does not re-emit hasVideoChanged when one
        video replaces another, so _load() resetting the flag would otherwise leave it False forever."""
        if v is None:
            v = bool(self._player.hasVideo())
        if v != self._has_video:
            self._has_video = v
            self._refresh_title()

    def _on_meta(self):
        self._refresh_title()

    def _on_buffer(self, v):
        self._buffer = float(v)
        self.bufferChanged.emit()

    def _on_error(self, _err, msg):
        self.errorMessage.emit(msg or "Playback error")

    def _on_end(self):
        self._drop_resume()
        if self._repeat == 2:
            self._player.setPosition(0)
            self._player.play()
            return
        if self._prefs is not None and not self._prefs.get("autoAdvance"):
            return
        nxt = self._next_index()
        if nxt is not None:
            self._load(nxt)

    def _next_index(self):
        n = len(self._queue)
        if n == 0:
            return None
        if self._shuffle and n > 1:
            choices = [i for i in range(n) if i != self._index]
            return random.choice(choices)
        if self._index + 1 < n:
            return self._index + 1
        return 0 if self._repeat == 1 else None

    def _refresh_tracks(self):
        tracks = []
        try:
            metas = self._player.audioTracks()
        except Exception:
            metas = []
        for i, md in enumerate(metas):
            code, name = language_of(md)
            title = md.stringValue(QMediaMetaData.Key.Title)
            tracks.append({"index": i, "tag": code, "title": title,
                           "label": title or name or f"Track {i + 1}"})
        self._tracks = tracks
        self._active_track = self._player.activeAudioTrack() if tracks else -1
        self._sync_video()

        self.tracksChanged.emit()

    def _load(self, i: int, start: int = 0):
        if not (0 <= i < len(self._queue)):
            return
        self._save_resume()
        e = self._queue[i]
        self._index = i
        self._base_title = e["title"]
        self._meta_title = ""
        self._pos = max(0, int(start))
        self._pending_seek = max(0, int(start))
        self._dur = 0
        self._has_video = False
        self._tracks = []
        self._active_track = -1
        self._reset_subtitles(QUrl(e["url"]))
        self._player.setSource(QUrl(e["url"]))
        self._player.setPlaybackRate(self._speed)
        self._player.play()
        url = QUrl(e["url"])
        if url.isLocalFile():
            self._push_recent(e["url"])
            folder = url_str(QUrl.fromLocalFile(str(Path(url.toLocalFile()).parent)))
            if folder != self._last_folder:
                self._last_folder = folder
                self._s.setValue("lastFolder", folder)
                self.folderChanged.emit()
        for sig in (self.positionChanged, self.durationChanged, self.mediaChanged,
                    self.tracksChanged, self.queueChanged):
            sig.emit()
        self.trackStarted.emit(self.title)
        self.jumped.emit()

    # ------------------------------------------------------------------ subtitles
    def _reset_subtitles(self, url: QUrl):
        """Forget the previous file's subtitles and start reading this file's (background thread)."""
        if self._subset is not None:
            self._subset.stop()
        self._subs, self._active_sub = [], -1
        self._sub_ver, self._sub_text, self._sub_delay = -1, "", 0
        self._sub_auto_done = False
        if url.isLocalFile():
            self._subset = SubtitleSet(url.toLocalFile())
            self._subset.start()
        else:                                   # streams: only subtitle files the user adds
            self._subset = SubtitleSet("")
            self._subset.finished = True
        self._sub_timer.start()
        self.subDelayChanged.emit()
        self.subtitleChanged.emit()

    def _sync_subs(self):
        """Refresh the track list from the worker's results; pick a default track once."""
        s = self._subset
        if s is None:
            return
        tracks = s.snapshot()
        self._subs = [t.info(i) for i, t in enumerate(tracks)]
        if not self._sub_auto_done and self._active_sub < 0 and tracks:
            if self._prefs is None or self._prefs.get("autoSubs"):
                idx = s.best_default()
                if idx >= 0:
                    self._active_sub = idx
                    self._sub_auto_done = True
        self.tracksChanged.emit()

    def _sub_tick(self):
        s = self._subset
        if s is None:
            return
        if s.version != self._sub_ver:
            self._sub_ver = s.version
            self._sync_subs()
        text = ""
        if self._active_sub >= 0:
            tracks = s.snapshot()
            if self._active_sub < len(tracks):
                text = tracks[self._active_sub].text_at(int(self._player.position()) - self._sub_delay)
        if text != self._sub_text:
            self._sub_text = text
            self.subtitleChanged.emit()

    @staticmethod
    def _is_subtitle_url(x) -> bool:
        url = PlayerController._to_url(x)
        return url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in SIDECAR_EXTS

    def _push_recent(self, url: str):
        if url in self._recent:
            self._recent.remove(url)
        self._recent.insert(0, url)
        del self._recent[MAX_RECENT:]
        self._s.setValue("recentJson", json.dumps(self._recent))
        self._resume = {k: v for k, v in self._resume.items() if k in self._recent}
        self._write_resume()
        self.recentChanged.emit()

    def _write_resume(self):
        self._s.setValue("resume", json.dumps(self._resume))

    def _cur_url(self):
        return self._queue[self._index]["url"] if 0 <= self._index < len(self._queue) else None

    def _save_resume(self, notify: bool = False):
        url = self._cur_url()
        if url is None or url not in self._recent or self._pending_seek > 0:
            return
        pos, dur = int(self._pos), int(self._dur)
        if dur > 0 and pos >= dur - 5000:
            self._resume.pop(url, None)
        elif pos >= 3000:
            self._resume[url] = [pos, dur]
        else:
            return
        self._write_resume()
        if notify:
            self.recentChanged.emit()

    def _drop_resume(self):
        url = self._cur_url()
        if url and self._resume.pop(url, None) is not None:
            self._write_resume()
            self.recentChanged.emit()

    @Property(int, notify=positionChanged)
    def position(self): return self._pos

    @Property(int, notify=durationChanged)
    def duration(self): return self._dur

    @Property(bool, notify=playingChanged)
    def playing(self): return self._playing

    @Property(float, notify=volumeChanged)
    def volume(self): return self._volume

    @Property(bool, notify=mutedChanged)
    def muted(self): return self._muted

    @Property(float, notify=speedChanged)
    def speed(self): return self._speed

    @Property(bool, notify=mediaChanged)
    def hasMedia(self): return self._index >= 0

    @Property(bool, notify=mediaChanged)
    def hasVideo(self): return self._has_video

    @Property(str, notify=mediaChanged)
    def title(self): return self._meta_title or self._base_title

    @Property(str, notify=mediaChanged)
    def subtitle(self):
        n = len(self._queue)
        return f"{self._index + 1} of {n} in queue" if n > 1 and self._index >= 0 else ""

    @Property(int, notify=mediaChanged)
    def index(self): return self._index

    @Property("QVariantList", notify=queueChanged)
    def queue(self): return list(self._queue)

    @Property("QVariantList", notify=tracksChanged)
    def audioTracks(self): return list(self._tracks)

    @Property(int, notify=tracksChanged)
    def activeTrack(self): return self._active_track

    @Property("QVariantList", notify=tracksChanged)
    def subtitleTracks(self): return list(self._subs)

    @Property(int, notify=tracksChanged)
    def activeSubtitle(self): return self._active_sub

    @Property(str, notify=subtitleChanged)
    def subtitleText(self): return self._sub_text

    @Property(int, notify=subDelayChanged)
    def subtitleDelay(self): return self._sub_delay

    @Property(bool, notify=tracksChanged)
    def subtitleLoading(self):
        s = self._subset
        return bool(s is not None and (not s.finished or any(not t.done for t in s.snapshot())))

    @Property(bool, notify=mediaChanged)
    def isAudio(self):
        """True only when the current file is a music/audio file (decides if the visualiser shows)."""
        if not (0 <= self._index < len(self._queue)):
            return False
        name = self._queue[self._index]["url"].split("?", 1)[0]
        return media_kind(name) == "audio"

    @Property("QVariantList", notify=recentChanged)
    def recent(self):
        out = []
        for u in self._recent:
            url = QUrl(u)
            if url.isLocalFile() and os.path.exists(url.toLocalFile()):
                e = self._entry(url)
                r = self._resume.get(u)
                e["resume"] = r[0] if r else 0
                e["total"] = r[1] if r else 0
                out.append(e)
        return out

    @Property(float, notify=bufferChanged)
    def buffer(self): return self._buffer

    @Property(bool, notify=bufferChanged)
    def buffering(self): return self._buffering

    @Property(int, notify=modeChanged)
    def repeatMode(self): return self._repeat

    @Property(bool, notify=modeChanged)
    def shuffle(self): return self._shuffle

    @Property(str, notify=folderChanged)
    def lastFolder(self): return self._last_folder

    @Property(bool, constant=True)
    def nativeFrame(self): return self._native_frame

    @Property("QVariantList", constant=True)
    def fileFilters(self): return FILE_FILTERS

    @Property("QVariantList", constant=True)
    def subtitleFilters(self): return SUBTITLE_FILTERS

    @Slot(QObject)
    def attachVideoOutput(self, item):
        self._player.setVideoOutput(item)

    @Slot("QVariantList")
    def openUrls(self, urls):
        urls = list(urls or [])
        sub_urls = [u for u in urls if self._is_subtitle_url(u)]
        media_urls = [u for u in urls if not self._is_subtitle_url(u)]
        if sub_urls and not media_urls and self._index >= 0:      # a subtitle dropped on a playing video
            self.addSubtitleFiles(sub_urls)
            return
        items = self._collect(media_urls)
        if not items:
            self.errorMessage.emit("No playable files found")
            return
        self._save_resume()
        self._queue = items
        self._index = -1
        self._load(0)
        if sub_urls:
            self.addSubtitleFiles(sub_urls)

    @Slot(str)
    def playFromLibrary(self, path):
        p = Path(path)
        items = self._collect([QUrl.fromLocalFile(str(p.parent))])
        target = url_str(QUrl.fromLocalFile(str(p)))
        idx = next((i for i, e in enumerate(items) if e["url"] == target), -1)
        if idx < 0:
            items, idx = [self._entry(QUrl.fromLocalFile(str(p)))], 0
        self._save_resume()
        self._queue = items
        self._index = -1
        self.queueChanged.emit()
        self._load(idx)

    @Slot("QVariantList")
    def enqueueUrls(self, urls):
        items = self._collect(urls)
        if not items:
            self.errorMessage.emit("No playable files found")
            return
        self._queue += items
        self.queueChanged.emit()
        if self._index < 0:
            self._load(len(self._queue) - len(items))

    @Slot(int)
    def playIndex(self, i): self._load(i)

    @Slot(int)
    def openRecent(self, i):
        r = self.recent
        if 0 <= i < len(r):
            self.openUrls([QUrl(r[i]["url"])])

    @Slot(int)
    def continueRecent(self, i):
        r = self.recent
        if 0 <= i < len(r):
            items = self._collect([QUrl(r[i]["url"])])
            if not items:
                return
            start = max(0, r[i]["resume"] - 2000)
            self._save_resume()
            self._queue = items
            self._index = -1
            self._load(0, start)

    @Slot()
    def saveProgress(self):
        self._save_resume(notify=True)

    @Slot()
    def clearRecent(self):
        self._recent = []
        self._resume = {}
        self._write_resume()
        self._s.setValue("recentJson", "[]")
        self.recentChanged.emit()

    @Slot(int)
    def removeAt(self, i):
        if not (0 <= i < len(self._queue)):
            return
        del self._queue[i]
        if i < self._index:
            self._index -= 1
            self.queueChanged.emit()
            self.mediaChanged.emit()
        elif i == self._index:
            if self._queue:
                self._index = -1
                self._load(min(i, len(self._queue) - 1))
            else:
                self.clearQueue()
        else:
            self.queueChanged.emit()
            self.mediaChanged.emit()

    @Slot()
    def clearQueue(self):
        self._save_resume()
        self._player.stop()
        self._player.setSource(QUrl())
        self._queue = []
        self._index = -1
        self._pos = self._dur = 0
        self._has_video = False
        self._tracks = []
        if self._subset is not None:
            self._subset.stop()
        self._subset = None
        self._sub_timer.stop()
        self._subs, self._active_sub, self._sub_text, self._sub_delay = [], -1, "", 0
        self._base_title = self._meta_title = ""
        for sig in (self.subtitleChanged, self.subDelayChanged, self.queueChanged, self.mediaChanged, self.positionChanged,
                    self.durationChanged, self.tracksChanged):
            sig.emit()

    @Slot()
    def togglePlay(self):
        if self._index < 0:
            if self._queue:
                self._load(0)
            return
        if self._playing:
            self._player.pause()
        else:
            if self._player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
                self._player.setPosition(0)
            self._player.play()

    @Slot()
    def next(self):
        n = self._next_index()
        if n is None and self._queue:
            n = 0
        if n is not None:
            self._load(n)

    @Slot()
    def prev(self):
        if self._index < 0:
            return
        if self._pos > 3000 or self._index == 0:
            self.seek(0)
        else:
            self._load(self._index - 1)

    @Slot(int)
    def seek(self, ms):
        ms = max(0, int(ms))
        if self._dur:
            ms = min(ms, self._dur)
        self._player.setPosition(ms)
        self._pos = ms
        self.positionChanged.emit()
        self.jumped.emit()
        self._sub_tick()

    @Slot(int)
    def seekBy(self, delta):
        self.seek(self._pos + int(delta))

    @Slot(float)
    def setVolume(self, v):
        self._volume = max(0.0, min(1.0, float(v)))
        if self._volume > 0 and self._muted:
            self._muted = False
            self.mutedChanged.emit()
        self._apply_volume()
        self._s.setValue("volume", self._volume)
        self.volumeChanged.emit()

    @Slot()
    def toggleMute(self):
        self._muted = not self._muted
        if not self._muted and self._volume == 0:
            self._volume = 0.5
            self._s.setValue("volume", self._volume)
            self.volumeChanged.emit()
        self._apply_volume()
        self.mutedChanged.emit()

    @Slot(float)
    def setSpeed(self, r):
        self._speed = max(0.25, min(4.0, float(r)))
        self._player.setPlaybackRate(self._speed)
        self._s.setValue("speed", self._speed)
        self.speedChanged.emit()

    @Slot(int)
    def selectAudioTrack(self, i):
        if 0 <= i < len(self._tracks):
            self._player.setActiveAudioTrack(i)
            self._active_track = i
            self.tracksChanged.emit()

    @Slot(int)
    def selectSubtitle(self, i):
        """Show subtitle track i (an index into subtitleTracks); -1 turns subtitles off."""
        self._sub_auto_done = True                # the user chose: never override it automatically
        if i < 0:
            self._active_sub = -1
        elif 0 <= i < len(self._subs):
            info = self._subs[i]
            if not info.get("usable", False):
                self.errorMessage.emit("Image subtitles can\u2019t be shown \u2014 load a .srt or .ass file")
                return
            self._active_sub = i
        else:
            return
        self._sub_text = ""
        self._sub_tick()
        self.tracksChanged.emit()
        self.subtitleChanged.emit()

    @Slot("QVariantList")
    def addSubtitleFiles(self, urls):
        """Load external subtitle file(s) for the current video and switch to the last good one."""
        if self._subset is None or self._index < 0:
            self.errorMessage.emit("Open a video first")
            return
        last = -1
        for u in urls or []:
            url = self._to_url(u)
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if Path(path).suffix.lower() not in SIDECAR_EXTS:
                self.errorMessage.emit("Not a subtitle file")
                continue
            tr = self._subset.add_file(path)
            if tr is None:
                self.errorMessage.emit("Couldn\u2019t read that subtitle file")
            elif not tr.usable:
                self.errorMessage.emit("No subtitles found in that file")
            else:
                last = len(self._subset.snapshot()) - 1
        self._sub_ver = self._subset.version
        self._sync_subs()
        if last >= 0:
            self.selectSubtitle(last)

    @Slot(int)
    def adjustSubtitleDelay(self, delta_ms):
        self._sub_delay = max(-60000, min(60000, self._sub_delay + int(delta_ms)))
        self.subDelayChanged.emit()
        self._sub_tick()

    @Slot()
    def resetSubtitleDelay(self):
        self._sub_delay = 0
        self.subDelayChanged.emit()
        self._sub_tick()

    @Slot()
    def cycleRepeat(self):
        self._repeat = (self._repeat + 1) % 3
        self._s.setValue("repeat", self._repeat)
        self.modeChanged.emit()

    @Slot()
    def toggleShuffle(self):
        self._shuffle = not self._shuffle
        self._s.setValue("shuffle", self._shuffle)
        self.modeChanged.emit()

    def shutdown(self):
        self._save_resume()
        self._ticker.stop()
        self._sub_timer.stop()
        if self._subset is not None:
            self._subset.stop()
        self._player.stop()
        self._s.sync()