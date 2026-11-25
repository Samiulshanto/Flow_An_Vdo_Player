"""Library scanner + the tree model shown in the browser panel. Exposed to QML as `library`."""
from __future__ import annotations

import getpass
import json
import os
import string
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Property, QAbstractListModel, QModelIndex, QUrl, Signal, Slot

from .constants import IS_WIN, MEDIA_EXTS
from .paths import data_dir
from .utils import fmt_size, library_entry, media_kind, natural_name

if TYPE_CHECKING:
    from .player import PlayerController


SKIP_ANYWHERE = {
    "node_modules", "__pycache__", "site-packages", "venv", "appdata", "steamapps",
    "$recycle.bin", "system volume information", "windows.old"
}
SKIP_ROOT_LEVEL = {
    "windows", "program files", "program files (x86)", "programdata", "recovery",
    "perflogs", "msocache", "intel", "system", "library", "applications", "proc",
    "sys", "dev", "bin", "sbin", "etc", "usr", "var", "lib", "lib64", "opt", "snap",
    "boot", "tmp", "cores", "private", "wsl", "wslg"
}
SKIP_SUFFIXES = (
    ".app", ".framework", ".bundle", ".photoslibrary", ".tvlibrary",
    ".imovielibrary", ".fcpbundle", ".xcodeproj", ".lproj"
)
MAX_DEPTH = 12


def _windows_drives():
    """Fixed and removable drives only (skips CD-ROM and network drives, which can hang)."""
    out = []
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        mask = k32.GetLogicalDrives()
        for i, c in enumerate(string.ascii_uppercase):
            if mask & (1 << i):
                root = f"{c}:\\"
                if k32.GetDriveTypeW(root) in (2, 3):     # DRIVE_REMOVABLE, DRIVE_FIXED
                    out.append((root, root))
    except Exception:
        out = [(f"{c}:\\", f"{c}:\\") for c in string.ascii_uppercase if os.path.exists(f"{c}:\\")]
    return out


def discover_roots():
    """[(label, path, is_home)] - the home folder first, then other drives."""
    home = str(Path.home())
    roots = [("~", home, True)]
    cands = []
    try:
        if IS_WIN:
            cands = _windows_drives()
        elif sys.platform == "darwin":
            if os.path.isdir("/Volumes"):
                cands = [(e.name, e.path) for e in os.scandir("/Volumes") if not e.name.startswith(".")]
        else:
            try:
                user = getpass.getuser()
            except Exception:
                user = os.environ.get("USER", "")
            for base in (f"/media/{user}", f"/run/media/{user}", "/mnt"):
                if os.path.isdir(base):
                    cands += [(e.name, e.path) for e in os.scandir(base)
                              if e.is_dir() and not e.name.startswith(".")]
    except OSError:
        pass
    seen = {os.path.realpath(home)}
    for label, p in cands:
        rp = os.path.realpath(p)
        if rp == os.path.realpath(os.sep) or rp in seen:
            continue
        seen.add(rp)
        roots.append((label, p, False))
    return roots


class _Node:
    __slots__ = ("name", "path", "dirs", "files", "count")

    def __init__(self, name, path):
        self.name, self.path = name, path
        self.dirs, self.files, self.count = {}, [], 0

    def tally(self):
        self.count = len(self.files) + sum(c.tally() for c in self.dirs.values())
        return self.count

    def prune(self):
        """Drop sub-folders that contain no files (after filtering)."""
        for k in list(self.dirs):
            c = self.dirs[k]
            c.prune()
            if not c.files and not c.dirs:
                del self.dirs[k]


class LibraryModel(QAbstractListModel):
    scanningChanged = Signal()
    statusChanged = Signal()
    filterChanged = Signal()
    _partial = Signal(int, object, int)
    _finished = Signal(int, object)

    ROLES = ["kind", "label", "fpath", "prefix", "open", "cnt", "size", "depth", "media", "cat"]
    BASE = 256

    def __init__(self, player: PlayerController):
        super().__init__()
        self._player = player
        self._rows: list[dict] = []
        self._snapshot: dict = {}
        self._expanded: set[str] = set()
        self._seen: set[str] = set()
        self._gen = 0
        self._scanning = False
        self._status = ""
        self._use_partials = True
        self._filter = "all"
        self._cache = Path(data_dir()) / "library.json"
        self._partial.connect(self._on_partial)
        self._finished.connect(self._on_finished)
        self._load_cache()

    def roleNames(self):
        return {self.BASE + i + 1: n.encode() for i, n in enumerate(self.ROLES)}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        k = role - self.BASE - 1
        return self._rows[index.row()][self.ROLES[k]] if 0 <= k < len(self.ROLES) else None

    def _apply(self, new: list):
        old = self._rows
        no, nn = len(old), len(new)
        i = 0
        while i < no and i < nn and old[i] == new[i]:
            i += 1
        j = 0
        while j < no - i and j < nn - i and old[no - 1 - j] == new[nn - 1 - j]:
            j += 1
        if no - i - j > 0:
            self.beginRemoveRows(QModelIndex(), i, no - j - 1)
            self._rows = old[:i] + old[no - j:]
            self.endRemoveRows()
        if nn - i - j > 0:
            self.beginInsertRows(QModelIndex(), i, nn - j - 1)
            self._rows = new
            self.endInsertRows()
        else:
            self._rows = new

    @Property(bool, notify=scanningChanged)
    def scanning(self): return self._scanning

    @Property(str, notify=filterChanged)
    def filter(self): return self._filter

    @Slot(str)
    def setFilter(self, f):
        if f in ("all", "movies", "series", "extras", "audio") and f != self._filter:
            self._filter = f
            self._rebuild()
            self.filterChanged.emit()

    @Slot(str, result=int)
    def countOf(self, kind):
        n = 0
        for v in self._snapshot.values():
            for files in v["dirs"].values():
                for f in files:
                    if kind == "all" or f[2] == kind:
                        n += 1
        return n

    def _match(self, f):
        return self._filter == "all" or f[2] == self._filter

    @Property(str, notify=statusChanged)
    def status(self): return self._status

    def _set_status(self, t):
        if t != self._status:
            self._status = t
            self.statusChanged.emit()

    def _load_cache(self):
        try:
            data = json.loads(self._cache.read_text(encoding="utf-8"))
            roots = {r: v for r, v in data.get("roots", {}).items() if os.path.isdir(r)}
            for v in roots.values():
                dirs = {}
                for d, files in v["dirs"].items():
                    ents = [e for e in (f if len(f) >= 5 else library_entry(f[0], f[1], d) for f in files) if e]
                    if ents:
                        dirs[d] = ents
                v["dirs"] = dirs
            self._snapshot = roots
        except Exception:
            self._snapshot = {}
        if self._snapshot:
            self._rebuild()
            self._set_status(self._summary())

    def _save_cache(self):
        try:
            self._cache.parent.mkdir(parents=True, exist_ok=True)
            self._cache.write_text(json.dumps({"roots": self._snapshot}), encoding="utf-8")
        except Exception:
            pass

    def _summary(self):
        files = sum(len(f) for v in self._snapshot.values() for f in v["dirs"].values())
        dirs = sum(len(v["dirs"]) for v in self._snapshot.values())
        return f"{files} files in {dirs} folders"

    @Slot()
    def rescan(self):
        self._gen += 1
        gen = self._gen
        self._scanning = True
        self._use_partials = not self._snapshot
        self._set_status("refreshing library\u2026" if self._snapshot else "scanning\u2026")
        self.scanningChanged.emit()
        depth = self._player._prefs.get("scanDepth") if self._player._prefs else MAX_DEPTH
        threading.Thread(target=self._worker, args=(gen, int(depth)), daemon=True).start()

    def stop(self):
        self._gen += 1

    def _worker(self, gen, max_depth):
        roots = discover_roots()              # off the UI thread: drive checks can be slow
        result, seen, found, last = {}, set(), 0, time.monotonic()

        def snap():
            return {k: {"label": v["label"], "dirs": dict(v["dirs"])} for k, v in result.items()}

        for label, root, is_home in roots:
            entry = result[root] = {"label": label, "dirs": {}}
            stack = [(root, 0)]
            while stack:
                if gen != self._gen:
                    return
                d, depth = stack.pop()
                try:
                    real = os.path.realpath(d)
                except OSError:
                    continue
                if real in seen:
                    continue
                seen.add(real)
                files, subs = [], []
                try:
                    with os.scandir(d) as it:
                        for e in it:
                            name = e.name
                            if name.startswith((".", "$")):
                                continue
                            try:
                                if e.is_dir(follow_symlinks=False):
                                    low = name.lower()
                                    if (depth >= max_depth or low in SKIP_ANYWHERE
                                            or low.endswith(SKIP_SUFFIXES)
                                            or (depth == 0 and not is_home and low in SKIP_ROOT_LEVEL)):
                                        continue
                                    if IS_WIN and (e.stat(follow_symlinks=False).st_file_attributes & 6):
                                        continue
                                    subs.append(e.path)
                                elif e.is_file() and os.path.splitext(name)[1][1:].lower() in MEDIA_EXTS:
                                    ent = library_entry(name, e.stat().st_size, d)
                                    if ent:
                                        files.append(ent)
                            except OSError:
                                continue
                except OSError:
                    continue
                if files:
                    files.sort(key=lambda f: natural_name(f[0]))
                    entry["dirs"][d] = files
                    found += len(files)
                stack.extend((s, depth + 1) for s in sorted(subs, reverse=True))
                if time.monotonic() - last > 1.0:
                    last = time.monotonic()
                    self._partial.emit(gen, snap(), found)
        self._finished.emit(gen, snap())

    def _on_partial(self, gen, snap, found):
        if gen != self._gen:
            return
        self._set_status(f"scanning\u2026 {found} found")
        if self._use_partials:
            self._snapshot = snap
            self._rebuild()

    def _on_finished(self, gen, snap):
        if gen != self._gen:
            return
        self._snapshot = snap
        self._scanning = False
        self.scanningChanged.emit()
        self._rebuild()
        self._set_status(self._summary())
        self._save_cache()

    def _rebuild(self):
        roots = []
        for rpath, data in self._snapshot.items():
            root = _Node(data["label"], rpath)
            for d, files in data["dirs"].items():
                node = root
                rel = os.path.relpath(d, rpath)
                if rel != ".":
                    for part in rel.split(os.sep):
                        child = node.dirs.get(part)
                        if child is None:
                            child = node.dirs[part] = _Node(part, os.path.join(node.path, part))
                        node = child
                node.files = [f for f in files if self._match(f)]
            root.prune()
            if root.tally() > 0:
                roots.append(root)
        small = sum(len(v["dirs"]) for v in self._snapshot.values()) <= 120
        rows: list[dict] = []
        for root in roots:
            self._emit(rows, root, "", [], "", 0, small, True)
        self._apply(rows)

    CATS = (("movies", "Movies"), ("series", "Web Series"), ("extras", "Extras"), ("audio", "Audio"))

    def _open_default(self, key, default):
        if key not in self._seen:
            self._seen.add(key)
            if default:
                self._expanded.add(key)
        return key in self._expanded

    def _emit(self, rows, node, prefix, child_anc, parent, depth, small, root=False):
        name = node.name
        if not root:
            while len(node.dirs) == 1 and not node.files:
                (child,) = node.dirs.values()
                name += "/" + child.name
                node = child
        path = node.path
        is_open = self._open_default(path, depth <= 1 or small)
        rows.append({"kind": "dir", "label": name, "fpath": path, "prefix": prefix, "open": is_open,
                     "cnt": node.count, "size": "", "depth": depth, "parent": parent, "media": "", "cat": "",
                     "files": []})
        if not is_open:
            return
        items = ([("d", c) for c in sorted(node.dirs.values(), key=lambda c: natural_name(c.name))]
                 + self._group_files(node))
        self._emit_items(rows, items, child_anc, path, depth + 1, small, path)

    @staticmethod
    def _file_item(base, f):
        return ("f", f, os.path.join(base, f[0]))

    def _group_files(self, node):
        """Organise one folder's files: Movies / Web Series (by show + season) / Extras / Audio."""
        by = {c: [] for c, _ in self.CATS}
        for f in node.files:
            by[f[2]].append(f)
        present = [(c, lab) for c, lab in self.CATS if by[c]]
        out = []
        for cat, label in present:
            fs = sorted(by[cat], key=lambda f: natural_name(f[0]))
            if cat == "series":
                shows = {}
                for f in fs:
                    shows.setdefault((f[3], f[4]), []).append(f)
                kids = []
                for (show, season), lst in sorted(shows.items(), key=lambda kv: (kv[0][0].lower(), kv[0][1])):
                    lab = show + (f"  S{season:02d}" if season else "")
                    paths = [os.path.join(node.path, f[0]) for f in lst]
                    kids.append(("g", lab, f"show:{show}|{season}", "show",
                                 [self._file_item(node.path, f) for f in lst], len(lst), paths))
            else:
                kids = [self._file_item(node.path, f) for f in fs]
            if len(present) == 1 and cat != "series":
                out += kids                      # single kind of file: no header needed
            elif len(present) == 1:
                out += kids                      # only series: show groups directly
            else:
                paths = [os.path.join(node.path, f[0]) for f in fs]
                out.append(("g", label, cat, cat, kids, len(fs), paths))
        return out

    def _emit_items(self, rows, items, child_anc, parent, depth, small, base):
        for k, it in enumerate(items):
            last = k == len(items) - 1
            pre = "".join(child_anc) + ("\u2514\u2500\u2500 " if last else "\u251c\u2500\u2500 ")
            nxt = child_anc + ["    " if last else "\u2502   "]
            t = it[0]
            if t == "d":
                self._emit(rows, it[1], pre, nxt, parent, depth, small)
            elif t == "g":
                _, label, key, tag, kids, cnt, paths = it
                gkey = parent + "\x00" + key
                is_open = self._open_default(gkey, tag != "show" or small)
                rows.append({"kind": "group", "label": label, "fpath": gkey, "prefix": pre, "open": is_open,
                             "cnt": cnt, "size": "", "depth": depth, "parent": parent, "media": tag,
                             "cat": tag, "files": paths})
                if is_open:
                    self._emit_items(rows, kids, nxt, gkey, depth + 1, small, base)
            else:
                f = it[1]
                rows.append({"kind": "file", "label": f[0], "fpath": it[2], "prefix": pre, "open": False,
                             "cnt": 0, "size": fmt_size(f[1]), "depth": depth, "parent": parent,
                             "media": media_kind(f[0]), "cat": f[2], "files": []})

    @Slot(int, result=str)
    def pathAt(self, i): return self._rows[i]["fpath"] if 0 <= i < len(self._rows) else ""

    @Slot(str, result=int)
    def indexOfPath(self, p):
        return next((i for i, r in enumerate(self._rows) if r["fpath"] == p), -1)

    @Slot(int, result=bool)
    def isDir(self, i): return 0 <= i < len(self._rows) and self._rows[i]["kind"] in ("dir", "group")

    @Slot(int, result=bool)
    def isOpen(self, i): return 0 <= i < len(self._rows) and bool(self._rows[i]["open"])

    @Slot(int, result=int)
    def parentIndex(self, i):
        if not (0 <= i < len(self._rows)):
            return -1
        par = self._rows[i]["parent"]
        return next((k for k in range(i - 1, -1, -1) if self._rows[k]["fpath"] == par), -1) if par else -1

    @Slot(int, bool)
    def setOpen(self, i, flag):
        if self.isDir(i):
            p = self._rows[i]["fpath"]
            (self._expanded.add if flag else self._expanded.discard)(p)
            self._rebuild()

    @Slot(int)
    def activate(self, i):
        if not (0 <= i < len(self._rows)):
            return
        r = self._rows[i]
        if r["kind"] == "dir":
            self.setOpen(i, not r["open"])
        else:
            self._player.playFromLibrary(r["fpath"])

    @Slot(int)
    def playFolder(self, i):
        """Play a whole folder, or just the files of a group (a season, all movies, ...)."""
        if not (0 <= i < len(self._rows)):
            return
        r = self._rows[i]
        if r["kind"] == "dir":
            self._player.openUrls([QUrl.fromLocalFile(r["fpath"])])
        elif r["kind"] == "group" and r["files"]:
            self._player.openUrls([QUrl.fromLocalFile(p) for p in r["files"]])
