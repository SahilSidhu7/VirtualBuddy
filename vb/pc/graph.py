"""Your PC as a graph, in one SQLite file.

Nodes are folders and files; edges are `contains` links between them, so the
tree is walkable in both directions and other relations (duplicates, tags) can
be added later without reshaping anything.

Names go into an FTS5 index for fast candidate lookup, and candidates are
re-ranked with textvec — full vectors for every file would be gigabytes, but
re-ranking a few hundred rows costs nothing.
"""
from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from vb import config, textvec

DB_PATH = config.HOME / "pc.db"

# Folders that are never worth indexing: machine-generated, huge, or not yours.
SKIP_DIRS = {
    "node_modules", ".git", ".svn", "__pycache__", ".venv", "venv", "env",
    ".next", ".nuxt", "dist", "build", ".cache", ".gradle", ".idea", ".vscode",
    "AppData", "Application Data", "$Recycle.Bin", "System Volume Information",
    "Windows", "Program Files", "Program Files (x86)", "ProgramData",
    "site-packages", ".conda", ".npm", ".m2", "OneDriveTemp",
}
SKIP_EXT = {".tmp", ".log", ".lock", ".pyc", ".pyo", ".obj", ".pdb", ".dll",
            ".sys", ".cab", ".msi", ".swp"}

SCHEMA_VERSION = "2"

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id      INTEGER PRIMARY KEY,
    path    TEXT UNIQUE NOT NULL,
    parent  TEXT DEFAULT '',            -- denormalised, so edges build in one SQL pass
    name    TEXT NOT NULL,
    kind    TEXT NOT NULL,              -- dir | file
    ext     TEXT DEFAULT '',
    size    INTEGER DEFAULT 0,
    mtime   REAL DEFAULT 0,
    depth   INTEGER DEFAULT 0,
    seen    REAL DEFAULT 0              -- scan stamp, for pruning deletions
);
CREATE INDEX IF NOT EXISTS nodes_parent ON nodes(parent);
CREATE INDEX IF NOT EXISTS nodes_name  ON nodes(name);
CREATE INDEX IF NOT EXISTS nodes_ext   ON nodes(ext);
CREATE INDEX IF NOT EXISTS nodes_size  ON nodes(size DESC);
CREATE INDEX IF NOT EXISTS nodes_mtime ON nodes(mtime DESC);

CREATE TABLE IF NOT EXISTS edges (
    src INTEGER NOT NULL,
    dst INTEGER NOT NULL,
    rel TEXT NOT NULL DEFAULT 'contains',
    PRIMARY KEY (src, dst, rel)
);
CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst, rel);

CREATE VIRTUAL TABLE IF NOT EXISTS node_fts USING fts5(
    name, path, content='', tokenize="unicode61 tokenchars '-_.'"
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


@dataclass
class Node:
    id: int
    path: str
    name: str
    kind: str
    ext: str
    size: int
    mtime: float

    @property
    def parent(self) -> str:
        return str(Path(self.path).parent)

    def human_size(self) -> str:
        return human_size(self.size)

    def age(self) -> str:
        return ago(self.mtime)


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def ago(mtime: float) -> str:
    secs = max(0, time.time() - mtime)
    for limit, div, unit in ((90, 1, "s"), (5400, 60, "min"), (129600, 3600, "h"),
                             (2592000, 86400, "d"), (31536000, 2592000, "mo")):
        if secs < limit:
            return f"{secs / div:.0f}{unit} ago"
    return f"{secs / 31536000:.0f}y ago"


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    # The index is derived data: on a schema change, throw it away and rescan
    # rather than writing migrations for a cache.
    row = con.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
    if (row["value"] if row else None) != SCHEMA_VERSION:
        con.executescript("DROP TABLE IF EXISTS nodes; DROP TABLE IF EXISTS edges;"
                          "DROP TABLE IF EXISTS node_fts;")
        con.executescript(SCHEMA)
        con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('schema', ?)",
                    (SCHEMA_VERSION,))
        con.commit()
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def default_roots() -> list[Path]:
    """What to index when the user hasn't said otherwise: their own stuff."""
    configured = config.get("index_roots")
    if configured:
        return [Path(p).expanduser() for p in configured]
    home = Path.home()
    names = ["Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music"]
    roots = [home / n for n in names if (home / n).is_dir()]
    for extra in (Path("C:/Projects"), home / "Projects", home / "src"):
        if extra.is_dir():
            roots.append(extra)
    return roots or [home]


def _row_to_node(row: sqlite3.Row) -> Node:
    return Node(id=row["id"], path=row["path"], name=row["name"], kind=row["kind"],
                ext=row["ext"], size=row["size"], mtime=row["mtime"])


class PCGraph:
    def __init__(self, con: sqlite3.Connection | None = None):
        self.con = con or connect()

    # -- building --------------------------------------------------------
    def scan(self, roots: list[Path] | None = None, *, max_depth: int = 12,
             on_progress=None) -> dict:
        """Walk the roots and refresh the graph. Safe to re-run; it's a diff.

        Uses os.scandir rather than Path.stat(): on Windows the directory
        listing already carries size and mtime, so reading them costs nothing,
        while a stat() per file means a syscall each — and on OneDrive-backed
        folders it can wake a cloud placeholder. That difference was 81 minutes
        versus well under one on this machine.
        """
        roots = roots or default_roots()
        stamp = time.time()
        files = dirs = 0
        rows: list[tuple] = []
        cur = self.con.cursor()

        def flush():
            cur.executemany(
                "INSERT INTO nodes(path, parent, name, kind, ext, size, mtime, depth, seen)"
                " VALUES (?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(path) DO UPDATE SET size=excluded.size,"
                "   mtime=excluded.mtime, seen=excluded.seen, depth=excluded.depth,"
                "   parent=excluded.parent", rows)
            rows.clear()

        for root in roots:
            root = root.resolve()
            if not root.is_dir():
                continue
            rows.append((str(root), str(root.parent), root.name or str(root),
                         "dir", "", 0, 0.0, 0, stamp))
            stack = [(root, 0)]
            while stack:
                here, depth = stack.pop()
                try:
                    entries = list(os.scandir(here))
                except OSError:
                    continue
                for entry in entries:
                    name = entry.name
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if is_dir:
                        if name in SKIP_DIRS or name.startswith("."):
                            continue
                        dirs += 1
                        rows.append((entry.path, str(here), name, "dir", "",
                                     0, st.st_mtime, depth + 1, stamp))
                        if depth + 1 < max_depth:
                            stack.append((Path(entry.path), depth + 1))
                    else:
                        ext = os.path.splitext(name)[1].lower()
                        if ext in SKIP_EXT or name.startswith("~$"):
                            continue
                        files += 1
                        rows.append((entry.path, str(here), name, "file", ext,
                                     st.st_size, st.st_mtime, depth + 1, stamp))
                    if len(rows) >= 5000:
                        flush()
                if on_progress and dirs % 500 == 0:
                    on_progress(files, dirs, str(here))
        if rows:
            flush()

        # Edges in one pass, now that every node knows its parent's path.
        cur.execute("INSERT OR IGNORE INTO edges(src, dst, rel)"
                    " SELECT p.id, c.id, 'contains' FROM nodes c"
                    " JOIN nodes p ON p.path = c.parent WHERE c.seen = ?", (stamp,))

        # Anything not touched by this pass is gone from disk.
        removed = cur.execute("SELECT count(*) FROM nodes WHERE seen < ?",
                              (stamp,)).fetchone()[0]
        cur.execute("DELETE FROM edges WHERE src IN (SELECT id FROM nodes WHERE seen < ?)"
                    "   OR dst IN (SELECT id FROM nodes WHERE seen < ?)", (stamp, stamp))
        cur.execute("DELETE FROM nodes WHERE seen < ?", (stamp,))
        cur.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('scanned_at', ?)",
                    (str(stamp),))
        cur.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('roots', ?)",
                    ("|".join(str(r) for r in roots),))
        self.con.commit()
        self._rebuild_fts()
        return {"files": files, "dirs": dirs, "removed": removed,
                "roots": [str(r) for r in roots], "seconds": time.time() - stamp}

    def _rebuild_fts(self):
        self.con.execute("DELETE FROM node_fts")
        self.con.execute(
            "INSERT INTO node_fts(rowid, name, path) SELECT id, name, path FROM nodes")
        self.con.commit()

    # -- state -----------------------------------------------------------
    def is_built(self) -> bool:
        return self.count() > 0

    def count(self, kind: str | None = None) -> int:
        if kind:
            return self.con.execute("SELECT count(*) FROM nodes WHERE kind=?",
                                    (kind,)).fetchone()[0]
        return self.con.execute("SELECT count(*) FROM nodes").fetchone()[0]

    def scanned_at(self) -> float:
        row = self.con.execute("SELECT value FROM meta WHERE key='scanned_at'").fetchone()
        return float(row[0]) if row else 0.0

    def roots(self) -> list[str]:
        row = self.con.execute("SELECT value FROM meta WHERE key='roots'").fetchone()
        return row[0].split("|") if row else []

    # -- queries ---------------------------------------------------------
    def search(self, text: str, *, kind: str | None = None, limit: int = 12,
               pool: int = 400) -> list[Node]:
        """Name search: FTS for candidates, textvec to rank them by meaning."""
        terms = [t for t in _tokens(text) if len(t) > 1]
        if not terms:
            return []
        query = " OR ".join(f'"{t}"*' for t in terms)
        sql = ("SELECT n.* FROM node_fts f JOIN nodes n ON n.id = f.rowid"
               " WHERE node_fts MATCH ?")
        args: list = [query]
        if kind:
            sql += " AND n.kind = ?"
            args.append(kind)
        sql += " LIMIT ?"
        args.append(pool)
        try:
            rows = self.con.execute(sql, args).fetchall()
        except sqlite3.OperationalError:
            return []
        if not rows:
            return []
        names = [f"{r['name']} {Path(r['path']).parent.name}" for r in rows]
        sims = textvec.similarity(textvec.encode(names), textvec.encode(text)[0])
        ranked = sorted(zip(rows, sims), key=lambda p: p[1], reverse=True)
        return [_row_to_node(r) for r, _ in ranked[:limit]]

    def children(self, path: str, *, kind: str | None = None,
                 limit: int = 200) -> list[Node]:
        sql = ("SELECT c.* FROM nodes p JOIN edges e ON e.src = p.id"
               " JOIN nodes c ON c.id = e.dst"
               " WHERE p.path = ? AND e.rel = 'contains'")
        args: list = [str(Path(path))]
        if kind:
            sql += " AND c.kind = ?"
            args.append(kind)
        # Folders first — "kind DESC" sorted 'file' above 'dir' alphabetically,
        # so a folder with many files pushed every subfolder past the limit.
        sql += " ORDER BY (c.kind = 'file'), c.name LIMIT ?"
        args.append(limit)
        return [_row_to_node(r) for r in self.con.execute(sql, args)]

    def biggest(self, limit: int = 12, under: str | None = None) -> list[Node]:
        sql = "SELECT * FROM nodes WHERE kind='file'"
        args: list = []
        if under:
            sql += " AND path LIKE ?"
            args.append(str(Path(under)) + "%")
        sql += " ORDER BY size DESC LIMIT ?"
        args.append(limit)
        return [_row_to_node(r) for r in self.con.execute(sql, args)]

    def recent(self, limit: int = 12, under: str | None = None,
               ext: str | None = None) -> list[Node]:
        sql = "SELECT * FROM nodes WHERE kind='file'"
        args: list = []
        if under:
            sql += " AND path LIKE ?"
            args.append(str(Path(under)) + "%")
        if ext:
            sql += " AND ext = ?"
            args.append(ext if ext.startswith(".") else "." + ext)
        sql += " ORDER BY mtime DESC LIMIT ?"
        args.append(limit)
        return [_row_to_node(r) for r in self.con.execute(sql, args)]

    def by_ext(self, ext: str, limit: int = 20) -> list[Node]:
        ext = ext if ext.startswith(".") else "." + ext
        return [_row_to_node(r) for r in self.con.execute(
            "SELECT * FROM nodes WHERE ext=? ORDER BY mtime DESC LIMIT ?",
            (ext.lower(), limit))]

    def ext_summary(self, limit: int = 12, under: str | None = None) -> list[tuple]:
        sql = ("SELECT ext, count(*) AS n, sum(size) AS bytes FROM nodes"
               " WHERE kind='file' AND ext != ''")
        args: list = []
        if under:
            sql += " AND path LIKE ?"
            args.append(str(Path(under)) + "%")
        sql += " GROUP BY ext ORDER BY bytes DESC LIMIT ?"
        args.append(limit)
        return [(r["ext"], r["n"], r["bytes"] or 0) for r in self.con.execute(sql, args)]

    def folder_sizes(self, under: str | None = None, limit: int = 12) -> list[tuple]:
        """Total bytes per top-level folder beneath `under` (or per root)."""
        base = str(Path(under)) if under else None
        rows = self.con.execute(
            "SELECT path, size FROM nodes WHERE kind='file'" +
            (" AND path LIKE ?" if base else ""),
            ((base + "%",) if base else ())).fetchall()
        totals: dict[str, list] = {}
        cut = len(Path(base).parts) if base else None
        for row in rows:
            parts = Path(row["path"]).parts
            idx = cut if cut is not None else 0
            if len(parts) <= idx + 1:
                continue
            key = str(Path(*parts[: idx + 1])) if cut is not None else str(Path(*parts[:4]))
            entry = totals.setdefault(key, [0, 0])
            entry[0] += row["size"] or 0
            entry[1] += 1
        ordered = sorted(totals.items(), key=lambda kv: kv[1][0], reverse=True)
        return [(path, size, n) for path, (size, n) in ordered[:limit]]

    def stats(self) -> dict:
        row = self.con.execute(
            "SELECT count(*) AS files, sum(size) AS bytes FROM nodes WHERE kind='file'"
        ).fetchone()
        return {"files": row["files"] or 0, "bytes": row["bytes"] or 0,
                "dirs": self.count("dir"), "scanned_at": self.scanned_at(),
                "roots": self.roots()}

    def resolve_folder(self, text: str) -> Node | None:
        """Turn "my downloads" into an indexed folder node."""
        hits = self.search(text, kind="dir", limit=5)
        if not hits:
            return None
        # Prefer the shallowest match: "Downloads" over "Downloads/old/Downloads".
        return min(hits, key=lambda n: len(Path(n.path).parts))


def _tokens(text: str) -> list[str]:
    import re
    return re.findall(r"[\w]+", text.lower())


_graph: PCGraph | None = None


def graph() -> PCGraph:
    """Process-wide handle; the connection is opened once and reused."""
    global _graph
    if _graph is None:
        _graph = PCGraph()
    return _graph
