"""Runs the real flow/player.py + flow/visualizer.py against the tiny Qt stand-in in tests/qtstub."""
import math, os, shutil, struct, sys, tempfile, time, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests", "qtstub"))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from PySide6.QtCore import QSettings, QUrl
from PySide6.QtMultimedia import QAudioFormat
from PySide6.QtQml import QQmlPropertyMap
from flow.constants import DEFAULTS, FX_PRESETS
from flow.prefs import Prefs
from flow.player import PlayerController
from flow.visualizer import Visualizer
from test_subs import SRT, build_mkv


def make_ctl():
    qs = QSettings()
    prefs = Prefs(qs)
    ctl = PlayerController(qs, prefs=prefs)
    return ctl, prefs


def wait(ctl, cond, t=5):
    t0 = time.time()
    while time.time() - t0 < t:
        ctl._sub_tick()
        if cond(): return True
        time.sleep(0.02)
    return False


class VideoFlag(unittest.TestCase):
    def test_second_video_still_reports_video(self):
        """Qt does not re-emit hasVideoChanged for video -> video; Picture button depends on hasVideo."""
        ctl, _ = make_ctl()
        mp = ctl.media_player
        mp.has_video = True
        ctl.openUrls(["/tmp/a.mp4", "/tmp/b.mp4"])
        mp.hasVideoChanged.emit(True)
        self.assertTrue(ctl.hasVideo)
        ctl.next()                                   # Qt keeps hasVideo True and stays silent
        mp.mediaStatusChanged.emit(mp.mediaStatus())
        self.assertTrue(ctl.hasVideo)


class Subtitles(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.v = os.path.join(self.d, "Movie.mkv")
        build_mkv(self.v, [(1, 1, "V_MPEG4/ISO/AVC", "und", "", None),
                           (2, 17, "S_TEXT/UTF8", "eng", "Full", None),
                           (3, 17, "S_HDMV/PGS", "hin", "", None)],
                  [(1, 0, 40, b"x" * 100), (2, 1000, 2000, b"Hello"), (2, 5000, 1000, b"Later")])
    def tearDown(self): shutil.rmtree(self.d, ignore_errors=True)

    def test_load_select_delay_off(self):
        ctl, prefs = make_ctl()
        errors = []; ctl.errorMessage.connect(errors.append)
        ctl.openUrls([self.v])
        self.assertTrue(wait(ctl, lambda: len(ctl.subtitleTracks) == 2))
        t = ctl.subtitleTracks
        self.assertTrue(t[0]["usable"]); self.assertFalse(t[1]["usable"])
        self.assertEqual(ctl.activeSubtitle, 0)                        # Matroska tracks are "default" unless flagged off
        ctl.selectSubtitle(0)
        ctl.media_player.pos = 1500; ctl._sub_tick()
        self.assertEqual(ctl.subtitleText, "Hello")
        ctl.media_player.pos = 4500; ctl._sub_tick()
        self.assertEqual(ctl.subtitleText, "")
        ctl.adjustSubtitleDelay(2000)                                   # subtitles 2 s later
        ctl.media_player.pos = 4500; ctl._sub_tick()
        self.assertEqual(ctl.subtitleText, "Hello")
        ctl.resetSubtitleDelay(); self.assertEqual(ctl.subtitleDelay, 0)
        ctl.selectSubtitle(1)                                           # image track -> message, no change
        self.assertEqual(ctl.activeSubtitle, 0); self.assertTrue(errors)
        ctl.selectSubtitle(-1); ctl.media_player.pos = 1500; ctl._sub_tick()
        self.assertEqual(ctl.subtitleText, "")
        ctl.selectSubtitle(99); self.assertEqual(ctl.activeSubtitle, -1)

    def test_default_flag_autoselect_and_pref(self):
        for auto, expect in ((True, 0), (False, -1)):
            ctl, prefs = make_ctl()
            prefs.map.set("autoSubs", auto)
            v = os.path.join(self.d, "flagged.mkv")
            tr = [(1, 1, "V_X", "und", "", None), (2, 17, "S_TEXT/UTF8", "eng", "", None)]
            build_mkv(v, tr, [(2, 1000, 1000, b"Hi")])
            ctl.openUrls([v])
            wait(ctl, lambda: len(ctl.subtitleTracks) == 1)
            self.assertEqual(ctl.activeSubtitle, expect, auto)

    def test_sidecar_auto_and_external_load_and_drop(self):
        open(os.path.join(self.d, "Movie.en.srt"), "w").write(SRT)
        ctl, _ = make_ctl()
        ctl.openUrls([self.v])
        self.assertTrue(wait(ctl, lambda: len(ctl.subtitleTracks) == 3))
        self.assertEqual(ctl.activeSubtitle, 0)                          # the sidecar wins
        ctl.media_player.pos = 1500; ctl._sub_tick()
        self.assertEqual(ctl.subtitleText, "Hello world")
        other = os.path.join(self.d, "elsewhere.srt")
        open(other, "w").write("1\n00:00:01,000 --> 00:00:02,000\nDropped\n")
        ctl.openUrls([QUrl.fromLocalFile(other)])                        # drop a subtitle on the playing video
        self.assertEqual(len(ctl.subtitleTracks), 4)
        self.assertEqual(ctl.activeSubtitle, 3)
        ctl.media_player.pos = 1500; ctl._sub_tick()
        self.assertEqual(ctl.subtitleText, "Dropped")
        self.assertEqual(ctl.index, 0)                                   # still the same video
        bad = os.path.join(self.d, "bad.srt"); open(bad, "wb").write(b"\x00\x01garbage")
        errs = []; ctl.errorMessage.connect(errs.append)
        ctl.addSubtitleFiles([bad]); self.assertTrue(errs)
        self.assertEqual(ctl.activeSubtitle, 3)                          # unchanged
        ctl.addSubtitleFiles([os.path.join(self.d, "Movie.mkv")]); self.assertIn("Not a subtitle file", errs)

    def test_subtitle_without_media_and_clear(self):
        ctl, _ = make_ctl()
        errs = []; ctl.errorMessage.connect(errs.append)
        ctl.addSubtitleFiles([os.path.join(self.d, "x.srt")]); self.assertEqual(errs, ["Open a video first"])
        ctl.openUrls([self.v]); wait(ctl, lambda: ctl.subtitleTracks)
        ctl.clearQueue()
        self.assertEqual(ctl.subtitleTracks, []); self.assertEqual(ctl.subtitleText, "")
        ctl._sub_tick()                                                  # must not raise with no media

    def test_switching_files_resets_state(self):
        open(os.path.join(self.d, "Movie.en.srt"), "w").write(SRT)
        v2 = os.path.join(self.d, "Plain.mkv")
        build_mkv(v2, [(1, 1, "V_X", "und", "", None)], [(1, 0, 40, b"x")])
        ctl, _ = make_ctl()
        ctl.openUrls([self.v]); wait(ctl, lambda: len(ctl.subtitleTracks) == 3)
        ctl.adjustSubtitleDelay(500)
        ctl.enqueueUrls([v2]); ctl.playIndex(1)
        self.assertEqual(ctl.subtitleDelay, 0)
        wait(ctl, lambda: not ctl.subtitleLoading)
        self.assertEqual(ctl.subtitleTracks, []); self.assertEqual(ctl.activeSubtitle, -1)
        ctl.seek(1000); ctl.seekBy(500)

    def test_stream_url_has_no_tracks_but_accepts_files(self):
        ctl, _ = make_ctl()
        ctl.openUrls(["https://example.com/live.mp4"])
        self.assertEqual(ctl.subtitleTracks, [])
        s = os.path.join(self.d, "s.srt"); open(s, "w").write(SRT)
        ctl.addSubtitleFiles([QUrl.fromLocalFile(s)])
        self.assertEqual(len(ctl.subtitleTracks), 1); self.assertEqual(ctl.activeSubtitle, 0)


class FakeBuf:
    def __init__(self, samples, sr=44100, start_us=0, fmt=None):
        self._raw = struct.pack(f"<{len(samples)}h", *[int(s * 32767) for s in samples])
        self._sr, self._start, self._fmt = sr, start_us, fmt
    def isValid(self): return True
    def format(self):
        b = self
        class F:
            def sampleFormat(s): return b._fmt
            def channelCount(s): return 1
            def sampleRate(s): return b._sr
        return F()
    def constData(self): return memoryview(self._raw)
    def startTime(self): return self._start


class VisualizerTest(unittest.TestCase):
    def test_reacts_to_audio_and_silences(self):
        ctl, _ = make_ctl()
        v = Visualizer(ctl)
        self.assertTrue(v.available)
        self.assertIs(ctl.media_player.abo, v._out)
        frames = []; v.frame.connect(lambda: frames.append(1))
        v.setActive(True)
        ctl._playing = True
        fmt = QAudioFormat.SampleFormat.Int16
        # feed 1 s of 100 Hz (bass) as 20 ms buffers while "playing"
        sr = 44100
        for k in range(50):
            n = 882
            sig = [0.6 * math.sin(2 * math.pi * 100 * (k * n + i) / sr) for i in range(n)]
            v._on_buffer(FakeBuf(sig, sr, k * 20000, fmt))
            ctl.media_player.pos = k * 20 + 20
            v._tick()
        bars = v.bars
        self.assertEqual(len(bars), 48)
        peak = max(range(48), key=lambda i: bars[i])
        self.assertLess(peak, 10); self.assertGreater(bars[peak], 0.4)
        self.assertGreater(max(v.wave), 0.3)
        self.assertTrue(frames)
        # audio stops arriving -> display falls to silence, then stops repainting
        time.sleep(0.7)
        for _ in range(80): v._tick()
        self.assertLess(max(v.bars), 0.02)
        n = len(frames)
        for _ in range(20): v._tick()
        self.assertEqual(len(frames), n)                                 # flat: no more frames emitted
        v.setActive(False); self.assertFalse(v._timer.active)

    def test_bad_buffers_never_raise(self):
        ctl, _ = make_ctl()
        v = Visualizer(ctl); v.setActive(True)
        class Bad(FakeBuf):
            def constData(self): raise RuntimeError("boom")
        v._on_buffer(Bad([0.1] * 10, fmt=QAudioFormat.SampleFormat.Int16))
        v._on_buffer(FakeBuf([0.1] * 10, fmt=QAudioFormat.SampleFormat.Unknown))
        v.reset(); v._tick()


class Prefs_(unittest.TestCase):
    def test_new_defaults_and_presets(self):
        for k in ("autoSubs", "subSize", "subBox", "fxPreset", "fxBrightness", "fxContrast",
                  "fxSaturation", "fxWarmth", "fxVignette", "fxLetterbox", "vizStyle"):
            self.assertIn(k, DEFAULTS)
        keys = {k for k in DEFAULTS if k.startswith("fx") and k != "fxPreset"}
        for name, p in FX_PRESETS.items():
            self.assertEqual(set(p), keys, name)
        ctl, prefs = make_ctl()
        self.assertEqual(prefs.get("fxPreset"), "off"); self.assertEqual(prefs.get("subSize"), 1.0)
        self.assertIs(prefs.get("fxLetterbox"), False)
        qs = QSettings(); qs.setValue("prefs/fxBrightness", "0.04"); qs.setValue("prefs/fxLetterbox", "true")
        qs.setValue("prefs/subSize", "garbage")
        p2 = Prefs(qs)
        self.assertAlmostEqual(p2.get("fxBrightness"), 0.04); self.assertIs(p2.get("fxLetterbox"), True)
        self.assertEqual(p2.get("subSize"), 1.0)                          # bad value -> default


if __name__ == "__main__":
    unittest.main()
