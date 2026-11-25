"""Tests for flow/subs.py (no Qt needed).   Run:  python -m unittest discover -s tests -v"""
import os, shutil, struct, subprocess, sys, tempfile, time, unittest, zlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from flow import subs

SRT = """1
00:00:01,000 --> 00:00:03,000
Hello <i>world</i>

2
00:00:04,500 --> 00:00:06,000
{\\an8}Top line
Second line

3
00:00:08,000 --> 00:00:09,500
Caf\u00e9 &amp; bar
"""
ASS = """[Script Info]
Title: t
[V4+ Styles]
Format: Name, Fontname
Style: Default,Arial
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\i1}Hello{\\i0}\\Nworld, with comma
Dialogue: 0,0:00:05.00,0:00:06.50,Default,,0,0,0,,{\\p1}m 0 0 l 10 10{\\p0}
Dialogue: 0,0:00:07.00,0:00:08.00,Default,,0,0,0,,Plain
"""
HAVE_FFMPEG = shutil.which("ffmpeg") is not None


# ---- tiny EBML writer so we can build odd Matroska files ffmpeg won't make
def vint_size(n):
    for ln in range(1, 9):
        if n < (1 << (7 * ln)) - 1:
            return ((1 << (7 * ln)) | n).to_bytes(ln, "big")
    raise ValueError

def el(eid, payload, unknown=False):
    idb = eid.to_bytes((eid.bit_length() + 7) // 8, "big")
    size = b"\x01\xff\xff\xff\xff\xff\xff\xff" if unknown else vint_size(len(payload))
    return idb + size + payload

def u(n): return n.to_bytes(max(1, (n.bit_length() + 7) // 8), "big")

def build_mkv(path, tracks, blocks, unknown_cluster=False, group=False, scale=1_000_000):
    """tracks: [(num, type, codec, lang, name, comp)], blocks: [(num, ms, dur_ms, bytes)]"""
    te = b""
    for num, typ, codec, lang, name, comp in tracks:
        e = el(0xD7, u(num)) + el(0x83, u(typ)) + el(0x86, codec.encode()) + el(0x22B59C, lang.encode())
        if name: e += el(0x536E, name.encode())
        if comp == "zlib":
            e += el(0x6D80, el(0x6240, el(0x5031, u(0)) + el(0x5034, el(0x4254, b"\x00"))))
        te += el(0xAE, e)
    info = el(0x1549A966, el(0x2AD7B1, u(scale)))
    clusters = b""
    for num, ms, dur, data in blocks:
        tn, typ = num, [t for t in tracks if t[0] == num][0]
        if typ[5] == "zlib": data = zlib.compress(data)
        hdr = bytes([0x80 | tn]) + struct.pack(">h", 0) + b"\x00"
        base = ms * 1_000_000 // scale
        if group:
            body = el(0xE7, u(base)) + el(0xA0, el(0xA1, hdr + data) + el(0x9B, u(dur * 1_000_000 // scale)))
        else:
            body = el(0xE7, u(base)) + el(0xA3, hdr + data)
        clusters += el(0x1F43B675, body, unknown=unknown_cluster)
    seg = info + el(0x1654AE6B, te) + clusters
    with open(path, "wb") as f:
        f.write(el(0x1A45DFA3, el(0x4282, b"matroska")) + el(0x18538067, seg))


class Parsers(unittest.TestCase):
    def test_srt(self):
        c = subs.parse_srt(SRT)
        self.assertEqual(len(c), 3)
        self.assertEqual(c[0], (1000, 3000, "Hello world"))
        self.assertEqual(c[1][2], "Top line\nSecond line")
        self.assertEqual(c[2][2], "Caf\u00e9 & bar")

    def test_srt_messy(self):
        messy = "\ufeff1\r\n0:00:01.5 --> 0:00:02.5\r\nno hours dots\r\n2\r\n00:00:03,000 --> 00:00:04,000\r\nmissing blank line\r\n\r\n\r\n\r\n3\r\n00:00:05,000 --> 00:00:06,000\r\n\r\n"
        c = subs.parse_srt(messy)
        self.assertEqual([x[2] for x in c], ["no hours dots", "missing blank line"])
        self.assertEqual(c[0][0], 1500)

    def test_vtt(self):
        v = "WEBVTT\n\nNOTE hi\n\n00:01.000 --> 00:02.000\nShort stamp\n\n01:00:00.000 --> 01:00:01.000 align:start\nLong\n"
        c = subs.parse_vtt(v)
        self.assertEqual(c[0], (1000, 2000, "Short stamp"))
        self.assertEqual(c[1][0], 3600000)

    def test_ass(self):
        c = subs.parse_ass(ASS)
        self.assertEqual(c[0], (1000, 3000, "Hello\nworld, with comma"))
        self.assertEqual([x[2] for x in c], ["Hello\nworld, with comma", "Plain"])   # drawing dropped

    def test_encodings(self):
        self.assertEqual(subs.decode_bytes("caf\u00e9".encode("cp1252")), "caf\u00e9")
        self.assertEqual(subs.decode_bytes("caf\u00e9".encode("utf-16")), "caf\u00e9")
        self.assertEqual(subs.decode_bytes(b"\xef\xbb\xbfabc"), "abc")

    def test_text_at_overlap(self):
        t = subs.SubTrack(label="x")
        t.add(0, 5000, "long"); t.add(1000, 2000, "short"); t.add(3000, 3500, "later")
        self.assertEqual(t.text_at(1500), "long\nshort")
        self.assertEqual(t.text_at(2500), "long")
        self.assertEqual(t.text_at(5000), "")
        t.add(500, 900, "out of order")
        self.assertEqual(t.text_at(600), "long\nout of order")

    def test_microdvd(self):
        c = subs.parse_microdvd("{1}{1}25\n{25}{50}Hi|there\n")
        self.assertEqual(c[0], (1000, 2000, "Hi\nthere"))


class Mkv(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def load(self, path, wait=5):
        s = subs.SubtitleSet(path); s.start()
        t0 = time.time()
        while not s.finished and time.time() - t0 < wait: time.sleep(0.02)
        self.assertTrue(s.finished)
        return s

    def test_handmade_all_variants(self):
        p = os.path.join(self.d, "m.mkv")
        tracks = [(1, 1, "V_MPEG4/ISO/AVC", "und", "", None),
                  (2, 17, "S_TEXT/UTF8", "eng", "Full", None),
                  (3, 17, "S_TEXT/UTF8", "hin", "", "zlib"),
                  (4, 17, "S_HDMV/PGS", "eng", "", None),
                  (5, 17, "S_TEXT/ASS", "fre", "", None)]
        blocks = [(1, 0, 40, b"\x00" * 500),
                  (2, 1000, 2000, b"Hello\nworld"),
                  (3, 1500, 1000, b"compressed"),
                  (4, 1600, 1000, b"PGSDATA"),
                  (5, 2000, 1500, b"0,0,Default,,0,0,0,,{\\b1}Bonjour\\Nmonde"),
                  (2, 4000, 1000, b"<i>second</i>")]
        for unk in (False, True):
            for grp in (False, True):
                build_mkv(p, tracks, blocks, unknown_cluster=unk, group=grp)
                s = self.load(p)
                tr = s.snapshot()
                self.assertEqual(len(tr), 4, (unk, grp))
                self.assertEqual(tr[0].text_at(1500), "Hello\nworld")
                self.assertEqual(tr[0].text_at(4500), "second")
                self.assertEqual(tr[0].label, "English \u00b7 Full")
                self.assertEqual(tr[1].text_at(1800), "compressed")
                self.assertEqual(tr[1].lang, "hin")
                self.assertEqual(tr[2].kind, "image"); self.assertFalse(tr[2].usable)
                self.assertIn("PGS", tr[2].label)
                self.assertEqual(tr[3].text_at(2500), "Bonjour\nmonde")
                info = [t.info(i) for i, t in enumerate(tr)]
                self.assertFalse(info[2]["usable"])

    def test_timescale(self):
        p = os.path.join(self.d, "t.mkv")
        build_mkv(p, [(1, 17, "S_TEXT/UTF8", "eng", "", None)], [(1, 5000, 2000, b"x")], scale=100_000)
        s = self.load(p)
        self.assertEqual(s.snapshot()[0].text_at(5500), "x")

    def test_corrupt_files_never_crash(self):
        p = os.path.join(self.d, "bad.mkv")
        good = os.path.join(self.d, "g.mkv")
        build_mkv(good, [(1, 17, "S_TEXT/UTF8", "eng", "", None)], [(1, 0, 1000, b"hello")] * 3)
        data = open(good, "rb").read()
        for name, blob in [("empty", b""), ("junk", os.urandom(4096)), ("trunc", data[:len(data) // 2]),
                           ("trunc2", data[:60]), ("ebmlonly", data[:12])]:
            open(p, "wb").write(blob)
            self.load(p)                                  # must finish without raising

    def test_sidecar_priority_and_labels(self):
        v = os.path.join(self.d, "Movie.2020.mkv"); open(v, "wb").write(b"")
        open(os.path.join(self.d, "Movie.2020.en.srt"), "w").write(SRT)
        open(os.path.join(self.d, "Movie.2020.hi.srt"), "w").write(SRT)
        open(os.path.join(self.d, "Other.srt"), "w").write(SRT)
        os.makedirs(os.path.join(self.d, "Subs"))
        open(os.path.join(self.d, "Subs", "2_English.srt"), "w").write(SRT)
        s = self.load(v)
        labels = [t.label for t in s.snapshot()]
        self.assertEqual(len(labels), 3, labels)
        self.assertTrue(any("English" in l for l in labels))
        self.assertEqual(s.best_default(), 0)

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg missing")
    def test_ffmpeg_made_mkv_mp4(self):
        open(os.path.join(self.d, "a.srt"), "w").write(SRT)
        open(os.path.join(self.d, "b.ass"), "w").write(ASS)
        base = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=d=10:s=160x120:r=10",
                "-f", "lavfi", "-i", "sine=d=10", "-i", os.path.join(self.d, "a.srt"),
                "-i", os.path.join(self.d, "b.ass"), "-map", "0:v", "-map", "1:a", "-map", "2", "-map", "3",
                "-c:v", "mpeg4", "-c:a", "aac", "-metadata:s:s:0", "language=eng", "-metadata:s:s:1", "language=spa"]
        mkv = os.path.join(self.d, "f.mkv")
        subprocess.run(base + ["-c:s:0", "srt", "-c:s:1", "ass", mkv], check=True)
        s = self.load(mkv)
        tr = s.snapshot()
        self.assertEqual(len(tr), 2)
        self.assertEqual(tr[0].lang, "eng")
        self.assertEqual(tr[0].text_at(1500), "Hello world")
        self.assertEqual(tr[1].lang, "spa")
        self.assertEqual(tr[1].text_at(1500), "Hello\nworld, with comma")
        self.assertEqual(tr[1].text_at(7500), "Plain")
        mp4 = os.path.join(self.d, "f.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=d=10:s=160x120:r=10",
                        "-i", os.path.join(self.d, "a.srt"), "-map", "0:v", "-map", "1", "-c:v", "mpeg4",
                        "-c:s", "mov_text", "-metadata:s:s:0", "language=fra", mp4], check=True)
        s = self.load(mp4)
        tr = s.snapshot()
        self.assertEqual(len(tr), 1, [t.label for t in tr])
        self.assertEqual(tr[0].lang, "fra")
        self.assertEqual(tr[0].text_at(1500), "Hello world")
        self.assertEqual(tr[0].text_at(5000), "Top line\nSecond line")
        # same mp4 through the ffmpeg fallback path
        avi = os.path.join(self.d, "f.avi")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=d=10:s=160x120:r=10",
                        "-c:v", "mpeg4", avi], check=True)
        s = self.load(avi)
        self.assertEqual(s.snapshot(), [])

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg missing")
    def test_ts_container_uses_ffmpeg_fallback(self):
        open(os.path.join(self.d, "a.srt"), "w").write(SRT)
        ts = os.path.join(self.d, "f.mkv")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=d=10:s=160x120:r=10",
                        "-i", os.path.join(self.d, "a.srt"), "-map", "0:v", "-map", "1", "-c:v", "mpeg4",
                        "-c:s", "srt", ts], check=True)
        # force fallback path by pretending it is an unknown container
        s = subs.SubtitleSet(ts)
        s._load_ffmpeg()
        tr = s.snapshot()
        self.assertEqual(len(tr), 1)
        self.assertEqual(tr[0].text_at(1500), "Hello world")


if __name__ == "__main__":
    unittest.main()
