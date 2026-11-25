"""Tests for flow/dsp.py (no Qt needed)."""
import math, os, struct, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from flow import dsp

SR = 44100

def sine(freq, n, sr=SR, amp=0.5):
    return [amp * math.sin(2 * math.pi * freq * i / sr) for i in range(n)]

def pcm16(vals):
    return struct.pack(f"<{len(vals)}h", *[int(v * 32767) for v in vals])


class Base:
    def setUp(self):
        self._saved = dsp.HAVE_NUMPY
        dsp.HAVE_NUMPY = self.numpy
    def tearDown(self):
        dsp.HAVE_NUMPY = self._saved

    def peak_band(self, freq, amp=0.5):
        a = dsp.Analyzer(bars=48)
        s = sine(freq, 4096, amp=amp)
        if self.numpy: s = dsp.np.array(s, dtype="float32")
        for _ in range(12): bars, _ = a.process(s, SR)
        return max(range(len(bars)), key=lambda i: bars[i]), bars

    def test_bass_vs_treble(self):
        lo, _ = self.peak_band(100)
        mid, _ = self.peak_band(1000)
        hi, _ = self.peak_band(8000)
        self.assertLess(lo, mid); self.assertLess(mid, hi)
        self.assertLess(lo, 10); self.assertGreater(hi, 34)

    def test_band_matches_frequency(self):
        a = dsp.Analyzer(bars=48)
        edges = dsp.Analyzer(bars=48)._band_edges(SR)
        idx, _ = self.peak_band(1000)
        if self.numpy:
            f = idx and (edges[idx] * SR / 2048)
        else:
            f = edges[idx]
        self.assertTrue(500 < f < 2000, f)

    def test_silence_is_flat(self):
        a = dsp.Analyzer()
        z = [0.0] * 4096
        if self.numpy: z = dsp.np.zeros(4096, dtype="float32")
        for _ in range(10): bars, wave = a.process(z, SR)
        self.assertLess(max(bars), 0.02)
        self.assertLess(max(abs(w) for w in wave), 0.02)

    def test_loud_louder_than_quiet(self):
        _, q = self.peak_band(440, amp=0.01)
        _, l = self.peak_band(440, amp=0.8)
        self.assertGreater(max(l), max(q) + 0.15)
        self.assertLessEqual(max(l), 1.0)

    def test_decay_after_stop(self):
        a = dsp.Analyzer()
        s = sine(300, 4096)
        if self.numpy: s = dsp.np.array(s, dtype="float32")
        for _ in range(10): a.process(s, SR)
        before = max(a.bars)
        for _ in range(30): a.silence()
        self.assertLess(max(a.bars), before * 0.05)

    def test_wave_follows_signal(self):
        a = dsp.Analyzer(wave_points=100)
        s = sine(50, 4096, amp=0.5)
        if self.numpy: s = dsp.np.array(s, dtype="float32")
        for _ in range(60): _, w = a.process(s, SR)
        self.assertEqual(len(w), 100)
        self.assertGreater(max(w), 0.5); self.assertLess(min(w), -0.5)
        self.assertTrue(all(-1.0 <= v <= 1.0 for v in w))

    def test_pcm_conversion(self):
        raw = pcm16([0.5, -0.5, 0.25, 0.25])           # stereo: 2 frames
        m = dsp.to_mono_floats(raw, "s16", 2)
        self.assertEqual(len(m), 2)
        self.assertAlmostEqual(float(m[0]), 0.0, places=3)
        self.assertAlmostEqual(float(m[1]), 0.25, places=3)
        f = dsp.to_mono_floats(struct.pack("<2f", 0.5, -1.0), "f32", 1)
        self.assertAlmostEqual(float(f[0]), 0.5, places=5)
        u = dsp.to_mono_floats(bytes([128, 255]), "u8", 1)
        self.assertAlmostEqual(float(u[0]), 0.0, places=3)
        i = dsp.to_mono_floats(struct.pack("<i", 1 << 30), "s32", 1)
        self.assertAlmostEqual(float(i[0]), 0.5, places=4)
        # odd trailing bytes must not crash
        dsp.to_mono_floats(raw + b"\x01", "s16", 2)


class WithNumpy(Base, unittest.TestCase):
    numpy = dsp.np is not None
class WithoutNumpy(Base, unittest.TestCase):
    numpy = False


class Bank(unittest.TestCase):
    def mk(self, start_ms, n=4410):
        return start_ms * 1000, SR, dsp.np.array(sine(440, n), dtype="float32") if dsp.HAVE_NUMPY else sine(440, n)

    def test_window_exact(self):
        b = dsp.SampleBank()
        for k in range(10):
            s, sr, a = self.mk(k * 100)
            b.add(s, sr, a)
        w, sr, exact = b.window(500_000, 2048)
        self.assertTrue(exact); self.assertEqual(len(w), 2048)

    def test_window_fallback_when_ahead(self):
        b = dsp.SampleBank()
        b.add(0, SR, dsp.np.ones(4410, dtype="float32"))
        w, sr, exact = b.window(60_000_000, 2048)       # player far past what we have
        self.assertFalse(exact); self.assertEqual(len(w), 2048)

    def test_window_picks_right_time(self):
        b = dsp.SampleBank()
        b.add(0, SR, dsp.np.zeros(44100, dtype="float32"))
        b.add(1_000_000, SR, dsp.np.ones(44100, dtype="float32"))
        w, _, ex = b.window(500_000, 1024)
        self.assertTrue(ex); self.assertEqual(float(abs(w).max()), 0.0)
        w, _, ex = b.window(1_800_000, 1024)
        self.assertTrue(ex); self.assertEqual(float(w.min()), 1.0)

    def test_trimming_and_empty(self):
        b = dsp.SampleBank(max_seconds=1.0)
        self.assertEqual(b.window(0, 100), (None, 0, False))
        for k in range(30):
            b.add(k * 100_000, SR, dsp.np.zeros(4410, dtype="float32"))
        self.assertLessEqual(b._total, 1.2)
        b.add(0, 0, [1])                                # bad rate ignored
        b.clear(); self.assertIsNone(b.latest_us)

    def test_clock(self):
        c = dsp.Clock()
        self.assertEqual(c.update(1000, 10.0, True), 1000)
        self.assertAlmostEqual(c.update(1000, 10.1, True), 1100, delta=1)
        self.assertEqual(c.update(1000, 10.1, False), 1000)
        self.assertLessEqual(c.update(1000, 20.0, True), 1250)   # capped


if __name__ == "__main__":
    unittest.main()
