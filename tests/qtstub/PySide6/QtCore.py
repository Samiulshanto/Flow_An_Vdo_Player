import os, urllib.parse
class _Bound:
    def __init__(self): self.slots = []
    def connect(self, f): self.slots.append(f)
    def disconnect(self, f=None): self.slots = [] if f is None else [s for s in self.slots if s != f]
    def emit(self, *a):
        for s in list(self.slots): s(*a)
class Signal:
    def __init__(self, *types): pass
    def __set_name__(self, owner, name): self.name = name
    def __get__(self, obj, typ=None):
        if obj is None: return self
        return obj.__dict__.setdefault("_sig_" + self.name, _Bound())
def Property(t, fget=None, notify=None, constant=False):
    def deco(f): return property(f)
    return deco if fget is None else property(fget)
def Slot(*a, **k):
    return lambda f: f
class QObject:
    def __init__(self, parent=None): self._parent = parent
class QTimer(QObject):
    timeout = Signal()
    def __init__(self, parent=None): super().__init__(parent); self.active = False; self.ms = 0
    def setInterval(self, ms): self.ms = ms
    def start(self, *a): self.active = True
    def stop(self): self.active = False
    @staticmethod
    def singleShot(ms, fn): fn()
class QUrl:
    def __init__(self, s=""): self._s = s if isinstance(s, str) else str(s)
    @staticmethod
    def fromLocalFile(p): return QUrl("file://" + urllib.parse.quote(os.path.abspath(p), safe="/,()+"))
    def isLocalFile(self): return self._s.startswith("file://")
    def toLocalFile(self): return urllib.parse.unquote(self._s[7:]) if self.isLocalFile() else ""
    def toEncoded(self):
        class B:
            def __init__(s, v): s.v = v
            def data(s): return s.v.encode("ascii")
        return B(self._s)
    def fileName(self): return urllib.parse.unquote(self._s.rsplit("/", 1)[-1])
    def host(self): return urllib.parse.urlparse(self._s).hostname or ""
    def scheme(self): return urllib.parse.urlparse(self._s).scheme
    def __eq__(self, o): return isinstance(o, QUrl) and o._s == self._s
    def __hash__(self): return hash(self._s)
class QSettings:
    class Format: IniFormat = 1
    def __init__(self, *a): self.d = {}
    def value(self, k, default=None): return self.d.get(k, default)
    def setValue(self, k, v): self.d[k] = v
    def sync(self): pass
class QLocale:
    class Language: AnyLanguage = 0; C = 1
    class LanguageCodeType: ISO639Part3 = 0
    def __init__(self, *a): pass
class QAbstractListModel(QObject): pass
class QModelIndex: pass
class QCoreApplication: pass
