import enum
from .QtCore import QObject, Signal
class QAudio:
    class VolumeScale: LogarithmicVolumeScale = 0; LinearVolumeScale = 1
    @staticmethod
    def convertVolume(v, a, b): return v * v
class _Dev:
    def isNull(self): return False
class QAudioOutput(QObject):
    def __init__(self, p=None): super().__init__(p); self._dev = None; self.vol = 1; self.muted = False
    def device(self): return self._dev
    def setDevice(self, d): self._dev = d
    def setVolume(self, v): self.vol = v
    def setMuted(self, m): self.muted = m
class QMediaDevices(QObject):
    audioOutputsChanged = Signal()
    @staticmethod
    def defaultAudioOutput(): return _Dev()
class _MD:
    def stringValue(self, k): return ""
    def value(self, k): return None
class QMediaMetaData:
    class Key: Title = 0; ContributingArtist = 1; AlbumArtist = 2; Language = 3
class QAudioFormat:
    class SampleFormat(enum.Enum):
        Unknown = 0; UInt8 = 1; Int16 = 2; Int32 = 3; Float = 4
class QAudioBufferOutput(QObject):
    audioBufferReceived = Signal()
class QMediaPlayer(QObject):
    class PlaybackState(enum.Enum): StoppedState = 0; PlayingState = 1; PausedState = 2
    class MediaStatus(enum.Enum):
        NoMedia = 0; LoadingMedia = 1; LoadedMedia = 2; StalledMedia = 3; BufferingMedia = 4; BufferedMedia = 5; EndOfMedia = 6; InvalidMedia = 7
    playbackStateChanged = Signal(); mediaStatusChanged = Signal(); durationChanged = Signal()
    hasVideoChanged = Signal(); tracksChanged = Signal(); metaDataChanged = Signal()
    bufferProgressChanged = Signal(); errorOccurred = Signal()
    def __init__(self, p=None):
        super().__init__(p); self.pos = 0; self.has_video = False; self.src = None; self.abo = None; self.calls = []
    def setAudioOutput(self, a): pass
    def setAudioBufferOutput(self, o): self.abo = o
    def setPlaybackRate(self, r): pass
    def position(self): return self.pos
    def setPosition(self, p): self.pos = p
    def setSource(self, u): self.src = u
    def play(self): self.calls.append("play")
    def pause(self): self.calls.append("pause")
    def stop(self): self.calls.append("stop")
    def mediaStatus(self): return QMediaPlayer.MediaStatus.LoadedMedia
    def audioTracks(self): return []
    def activeAudioTrack(self): return -1
    def setActiveAudioTrack(self, i): pass
    def metaData(self): return _MD()
    def setVideoOutput(self, o): pass
    def hasVideo(self): return self.has_video
    # Anything touching Qt's own subtitle API is a bug in Flow~ now -> make it loud in tests
    def subtitleTracks(self): raise AssertionError("native subtitleTracks() must not be used")
    def activeSubtitleTrack(self): raise AssertionError("native activeSubtitleTrack() must not be used")
    def setActiveSubtitleTrack(self, i): raise AssertionError("native setActiveSubtitleTrack() must not be used")
