"""Live audio visualiser feed. Exposed to QML as `wavefeed`.

Taps the audio that QMediaPlayer is really playing (QAudioBufferOutput, Qt 6.8+), analyses the
slice that is sounding right now (flow/dsp.py) and publishes spectrum `bars` + a `wave` line.
If this Qt has no QAudioBufferOutput the feed simply stays flat and `available` is False.
"""
from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from .dsp import Analyzer, Clock, SampleBank, to_mono_floats

try:
    from PySide6.QtMultimedia import QAudioBufferOutput, QAudioFormat
except ImportError:                                   # Qt older than 6.8
    QAudioBufferOutput = None
    QAudioFormat = None

if TYPE_CHECKING:
    from .player import PlayerController

BARS = 48
WAVE_POINTS = 160
FPS_MS = 16                       # ~60 fps while visible
STALE_SECONDS = 0.6               # no fresh audio for this long -> let the display fall to silence


class Visualizer(QObject):
    frame = Signal()
    activeChanged = Signal()

    def __init__(self, controller: "PlayerController"):
        super().__init__()
        self._ctl = controller
        self._bank = SampleBank(max_seconds=5.0)
        self._an = Analyzer(bars=BARS, wave_points=WAVE_POINTS)
        self._clock = Clock()
        self._active = False
        self._last_buf = 0.0
        self._available = False
        self._out = None
        self._fmt_names = {}
        self._warned = False
        self._was_flat = False

        if QAudioBufferOutput is not None:
            try:
                SF = QAudioFormat.SampleFormat
                self._fmt_names = {SF.UInt8: "u8", SF.Int16: "s16", SF.Int32: "s32", SF.Float: "f32"}
                self._out = QAudioBufferOutput(self)
                self._out.audioBufferReceived.connect(self._on_buffer)
                controller.media_player.setAudioBufferOutput(self._out)
                self._available = True
            except Exception as e:                    # never take the app down for a visual
                print(f"[Flow~] visualizer unavailable: {type(e).__name__}: {e}", file=sys.stderr)
                self._out = None
        else:
            print("[Flow~] visualizer: this Qt has no QAudioBufferOutput (needs PySide6 >= 6.8)", file=sys.stderr)

        controller.trackStarted.connect(lambda _t: self.reset())
        controller.jumped.connect(self.reset)

        self._timer = QTimer(self)
        self._timer.setInterval(FPS_MS)
        self._timer.timeout.connect(self._tick)

    # ----- QML surface
    @Property("QVariantList", notify=frame)
    def bars(self): return self._an.bars

    @Property("QVariantList", notify=frame)
    def wave(self): return self._an.wave

    @Property(float, notify=frame)
    def level(self): return float(self._an.level)

    @Property(bool, constant=True)
    def available(self): return self._available

    @Property(bool, notify=activeChanged)
    def active(self): return self._active

    @Slot(bool)
    def setActive(self, on: bool):
        on = bool(on)
        if on == self._active:
            return
        self._active = on
        if on:
            self._timer.start()
        else:
            self._timer.stop()
            self._bank.clear()
        self.activeChanged.emit()

    @Slot()
    def reset(self):
        self._bank.clear()
        self._an.silence(0.0)
        self.frame.emit()

    def shutdown(self):
        self._timer.stop()
        self._active = False

    # ----- audio in
    def _on_buffer(self, buf):
        if not self._active:
            return
        try:
            fmt = buf.format()
            name = self._fmt_names.get(fmt.sampleFormat())
            if name is None or not buf.isValid():
                return
            samples = to_mono_floats(buf.constData(), name, fmt.channelCount())
            start = buf.startTime()
            if start is None or start < 0:
                start = self._bank.latest_us or 0
            self._bank.add(int(start), int(fmt.sampleRate()), samples)
            self._last_buf = time.monotonic()
        except Exception as e:
            if not self._warned:
                self._warned = True
                print(f"[Flow~] visualizer: could not read audio buffer: {type(e).__name__}: {e}",
                      file=sys.stderr)

    # ----- one display frame
    def _tick(self):
        now = time.monotonic()
        ctl = self._ctl
        playing = ctl.playing
        if playing and now - self._last_buf < STALE_SECONDS:
            pos_ms = self._clock.update(ctl.media_player.position(), now, True, ctl.speed)
            samples, sr, _exact = self._bank.window(int(pos_ms * 1000), 2048)
            self._an.process(samples, sr)
        else:
            self._clock.update(ctl.media_player.position(), now, False, 1.0)
            self._an.silence()
            flat = max(self._an.bars) < 0.004 and max(abs(w) for w in self._an.wave) < 0.004
            if flat and self._was_flat:           # nothing moving: don't repaint 60 times a second
                return
            self._was_flat = flat
            self.frame.emit()
            return
        self._was_flat = False
        self.frame.emit()
