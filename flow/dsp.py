"""Audio analysis for the live visualiser. No Qt in here, so it can be tested on its own.

The player hands us the audio it is actually playing (decoded buffers with timestamps). We keep a
short history of it (`SampleBank`), cut out the slice that is sounding right now, and turn that
slice into spectrum bars and a waveform (`Analyzer`). Nothing here is animated by a formula:
silence is flat, a bass drum moves the left bars, a hi-hat moves the right ones.
"""
from __future__ import annotations

import math
from array import array
from collections import deque

try:                                     # numpy makes this ~50x faster, but is optional
    import numpy as np
except Exception:                        # pragma: no cover
    np = None

HAVE_NUMPY = np is not None


def to_mono_floats(raw, sample_format: str, channels: int):
    """Raw PCM bytes -> mono float samples in [-1, 1].  sample_format: u8 | s16 | s32 | f32."""
    channels = max(1, int(channels))
    if HAVE_NUMPY:
        dt = {"u8": np.uint8, "s16": np.int16, "s32": np.int32, "f32": np.float32}[sample_format]
        raw = bytes(raw) if not isinstance(raw, (bytes, bytearray)) else raw
        size = np.dtype(dt).itemsize
        raw = raw[: (len(raw) // (size * channels)) * size * channels]      # whole frames only
        a = np.frombuffer(raw, dtype=dt)
        if sample_format == "u8":
            a = (a.astype(np.float32) - 128.0) / 128.0
        elif sample_format == "s16":
            a = a.astype(np.float32) / 32768.0
        elif sample_format == "s32":
            a = a.astype(np.float32) / 2147483648.0
        else:
            a = a.astype(np.float32, copy=False)
        if channels > 1:
            a = a.reshape(-1, channels).mean(axis=1)
        return np.nan_to_num(a, nan=0.0, posinf=0.0, neginf=0.0)
    code = {"u8": "B", "s16": "h", "s32": "i", "f32": "f"}[sample_format]
    arr = array(code)
    n = (len(raw) // arr.itemsize) // channels * channels
    arr.frombytes(bytes(raw)[: n * arr.itemsize])
    scale = {"u8": 1.0, "s16": 32768.0, "s32": 2147483648.0, "f32": 1.0}[sample_format]
    out = []
    for i in range(0, n, channels):
        s = sum(arr[i:i + channels]) / channels
        out.append((s - 128.0) / 128.0 if sample_format == "u8" else s / scale)
    return out


class SampleBank:
    """Short rolling history of decoded audio, addressed by media time (microseconds)."""

    def __init__(self, max_seconds: float = 6.0):
        self.max_seconds = max_seconds
        self.chunks: deque = deque()          # (start_us, sample_rate, samples)
        self._total = 0.0

    def clear(self):
        self.chunks.clear()
        self._total = 0.0

    def add(self, start_us: int, sample_rate: int, samples):
        n = len(samples)
        if n == 0 or sample_rate <= 0:
            return
        self.chunks.append((int(start_us), int(sample_rate), samples))
        self._total += n / sample_rate
        while self._total > self.max_seconds and len(self.chunks) > 1:
            _, sr, old = self.chunks.popleft()
            self._total -= len(old) / sr

    @property
    def latest_us(self):
        if not self.chunks:
            return None
        s, sr, a = self.chunks[-1]
        return s + int(len(a) * 1_000_000 / sr)

    def window(self, end_us: int, n: int):
        """-> (samples, sample_rate, exact). The `n` samples that end at `end_us`.
        If we have no audio for that moment (buffers not there yet) the newest samples are used
        instead, with exact=False."""
        if not self.chunks:
            return None, 0, False
        sr = self.chunks[-1][1]
        span = int(n * 1_000_000 / sr)
        want_a, want_b = end_us - span, end_us
        picked = []
        for s, rate, arr in self.chunks:
            e = s + int(len(arr) * 1_000_000 / rate)
            if e > want_a and s < want_b and rate == sr:
                picked.append((s, arr))
        covered = 0
        for s, arr in picked:
            e = s + int(len(arr) * 1_000_000 / sr)
            covered += min(e, want_b) - max(s, want_a)
        if picked and covered >= 0.6 * span:
            picked.sort(key=lambda x: x[0])
            if HAVE_NUMPY:
                data = np.concatenate([a for _, a in picked])
            else:
                data = [x for _, a in picked for x in a]
            first = picked[0][0]
            skip = max(0, int((want_a - first) * sr / 1_000_000))
            data = data[skip:]
            return data[-n:], sr, True
        # fall back: tail of the newest chunks
        parts, got = [], 0
        for s, rate, arr in reversed(self.chunks):
            if rate != sr:
                continue
            parts.append(arr)
            got += len(arr)
            if got >= n:
                break
        parts.reverse()
        data = np.concatenate(parts) if HAVE_NUMPY else [x for a in parts for x in a]
        return data[-n:], sr, False


class Analyzer:
    """Turns a slice of samples into `bars` (spectrum, 0..1) and `wave` (waveform, -1..1)."""

    def __init__(self, bars: int = 48, wave_points: int = 160, fft_size: int = 2048):
        self.n_bars = bars
        self.n_wave = wave_points
        self.n_fft = fft_size
        self.bars = [0.0] * bars
        self.wave = [0.0] * wave_points
        self.level = 0.0
        self._peak = [0.0] * bars
        self._gain = 1.0
        self._edges_for = None
        self._edges = None
        if HAVE_NUMPY:
            self._win = np.hanning(fft_size).astype(np.float32)

    # ----- frequency band layout: log-spaced from 40 Hz up to 16 kHz
    def _band_edges(self, sr: int):
        if self._edges_for == sr:
            return self._edges
        lo, hi = 40.0, min(16000.0, sr / 2.0 - 1)
        edges = [lo * (hi / lo) ** (i / self.n_bars) for i in range(self.n_bars + 1)]
        if HAVE_NUMPY:
            bins = np.array([e * self.n_fft / sr for e in edges])
            idx = np.floor(bins).astype(int)
            for i in range(1, len(idx)):            # every band owns at least one bin
                if idx[i] <= idx[i - 1]:
                    idx[i] = idx[i - 1] + 1
            idx = np.minimum(idx, self.n_fft // 2)
            self._edges = idx
        else:
            self._edges = edges
        self._edges_for = sr
        return self._edges

    def silence(self, decay: float = 0.82):
        self.bars = [b * decay for b in self.bars]
        self._peak = [p * 0.9 for p in self._peak]
        self.wave = [w * decay for w in self.wave]
        self.level *= decay
        return self.bars, self.wave

    def process(self, samples, sr: int):
        """Update bars/wave from the newest samples."""
        if samples is None or len(samples) < 64 or sr <= 0:
            return self.silence()
        if HAVE_NUMPY:
            raw = self._bars_numpy(samples, sr)
            wave = self._wave_numpy(samples)
        else:
            raw = self._bars_python(samples, sr)
            wave = self._wave_python(samples)
        # smoothing: fast attack, slower release, so it feels like a real meter
        out = []
        for i, v in enumerate(raw):
            cur = self.bars[i]
            cur = cur + (v - cur) * 0.6 if v > cur else cur + (v - cur) * 0.22
            out.append(min(1.0, max(0.0, cur)))
        self.bars = out
        self.wave = wave
        return self.bars, self.wave

    # ----- numpy path
    def _bars_numpy(self, samples, sr):
        n = self.n_fft
        x = np.asarray(samples, dtype=np.float32)
        if len(x) < n:
            x = np.concatenate([np.zeros(n - len(x), dtype=np.float32), x])
        x = x[-n:]
        spec = np.abs(np.fft.rfft(x * self._win)) / (n / 4.0)
        idx = self._band_edges(sr)
        vals = np.empty(self.n_bars, dtype=np.float32)
        for i in range(self.n_bars):
            a, b = int(idx[i]), int(idx[i + 1])
            seg = spec[a:max(b, a + 1)]
            vals[i] = float(seg.max()) if len(seg) else 0.0
        db = 20.0 * np.log10(vals + 1e-9)
        # tilt: music rolls off ~3 dB/oct, so lift the highs a little to keep them visible
        tilt = np.linspace(0.0, 14.0, self.n_bars)
        out = np.clip((db + tilt + 72.0) / 62.0, 0.0, 1.0)
        return out.tolist()

    def _wave_numpy(self, samples):
        x = np.asarray(samples, dtype=np.float32)[-1024:]
        peak = float(np.max(np.abs(x))) if len(x) else 0.0
        self.level = self.level * 0.7 + min(1.0, float(np.sqrt(np.mean(x * x))) * 3.0) * 0.3 if len(x) else 0.0
        # gentle auto-gain so quiet tracks still draw a readable line, loud ones never clip
        target = 0.9 / peak if peak > 0.02 else self._gain
        target = min(target, 6.0)
        self._gain += (target - self._gain) * 0.08
        if len(x) < self.n_wave:
            x = np.concatenate([np.zeros(self.n_wave - len(x), dtype=np.float32), x])
        step = len(x) // self.n_wave
        blocks = x[: step * self.n_wave].reshape(self.n_wave, step)
        pts = blocks[np.arange(self.n_wave), np.argmax(np.abs(blocks), axis=1)]
        return np.clip(pts * self._gain, -1.0, 1.0).tolist()

    # ----- pure python path (no numpy): Goertzel per band over a short window
    def _bars_python(self, samples, sr):
        n = 512
        x = list(samples)[-n:]
        if len(x) < n:
            x = [0.0] * (n - len(x)) + x
        win = [0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1)) for i in range(n)]
        xs = [a * b for a, b in zip(x, win)]
        edges = self._band_edges(sr)
        out = []
        for i in range(self.n_bars):
            f = math.sqrt(edges[i] * edges[i + 1])
            k = f * n / sr
            w = 2 * math.pi * k / n
            c = 2 * math.cos(w)
            s1 = s2 = 0.0
            for v in xs:
                s0 = v + c * s1 - s2
                s2, s1 = s1, s0
            p = s1 * s1 + s2 * s2 - c * s1 * s2
            mag = math.sqrt(max(p, 0.0)) / (n / 4.0)
            db = 20 * math.log10(mag + 1e-9)
            tilt = 14.0 * i / max(1, self.n_bars - 1)
            out.append(min(1.0, max(0.0, (db + tilt + 72.0) / 62.0)))
        return out

    def _wave_python(self, samples):
        x = list(samples)[-1024:]
        if not x:
            return [0.0] * self.n_wave
        peak = max(abs(v) for v in x)
        rms = math.sqrt(sum(v * v for v in x) / len(x))
        self.level = self.level * 0.7 + min(1.0, rms * 3.0) * 0.3
        target = min(0.9 / peak, 6.0) if peak > 0.02 else self._gain
        self._gain += (target - self._gain) * 0.08
        if len(x) < self.n_wave:
            x = [0.0] * (self.n_wave - len(x)) + x
        step = len(x) // self.n_wave
        pts = []
        for i in range(self.n_wave):
            blk = x[i * step:(i + 1) * step]
            pts.append(max(blk, key=abs) * self._gain)
        return [max(-1.0, min(1.0, p)) for p in pts]


class Clock:
    """Smooth media-time estimate between the (coarse, jittery) player position updates."""

    def __init__(self):
        self._pos = 0.0
        self._at = 0.0

    def update(self, pos_ms: float, now: float, playing: bool, rate: float = 1.0) -> float:
        if pos_ms != self._pos:
            self._pos, self._at = pos_ms, now
            return pos_ms
        if not playing:
            return pos_ms
        # never run more than a quarter second ahead of the last real position
        return self._pos + min(250.0, (now - self._at) * 1000.0 * max(0.1, rate))
