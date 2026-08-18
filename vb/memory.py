"""What the buddy remembers between sessions.

Two kinds of thing go in here and they are not the same:

    fact      something about the user or their machine that stays true.
              "the projects live in C:/Projects/MAIN", "prefers short answers".
    episode   what happened on a task, written when one finishes. The loop
              reads these back so the second attempt at a similar job starts
              from what the first one learned.

One FTS5 table holds both, with `created` and `kind` unindexed alongside the
text. A single table rather than a content table plus a shadow index, because
the two get out of step: an earlier version of this project crashed on rescan
for exactly that reason. FTS5 is compiled into the Python that ships on
Windows, but not everywhere, so a LIKE query stands in when it is missing.
"""
from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from vb import config

_conn: sqlite3.Connection | None = None
_fts = True


def db_path() -> Path:
    return config.data_dir() / "memory.db"


def _connect() -> sqlite3.Connection:
    global _conn, _fts
    if _conn is not None:
        return _conn
    conn = sqlite3.connect(db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS notes USING fts5("
            "  text, tags, kind UNINDEXED, created UNINDEXED)")
        _fts = True
    except sqlite3.OperationalError:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS notes ("
            "  text TEXT, tags TEXT, kind TEXT, created REAL)")
        _fts = False
    conn.commit()
    _conn = conn
    return conn


@dataclass
class Note:
    text: str
    kind: str
    tags: str
    created: float

    def age(self) -> str:
        days = (time.time() - self.created) / 86400
        if days < 1:
            return "today"
        if days < 2:
            return "yesterday"
        return f"{int(days)} days ago"


def remember(text: str, kind: str = "fact", tags: str = "") -> bool:
    """Store one thing. Duplicates are dropped rather than stacked."""
    text = (text or "").strip()
    if len(text) < 4:
        return False
    conn = _connect()
    existing = conn.execute(
        "SELECT 1 FROM notes WHERE text = ? LIMIT 1", (text,)).fetchone()
    if existing:
        return False
    conn.execute("INSERT INTO notes (text, tags, kind, created) VALUES (?,?,?,?)",
                 (text, tags, kind, time.time()))
    conn.commit()
    return True


# FTS5 treats these as syntax. A user's question is not a query language.
_FTS_PUNCT = re.compile(r"[^\w\s]")


def _fts_query(query: str) -> str:
    """Turn a sentence into something FTS5 will accept.

    Every term is quoted. Unquoted, a word like AND, OR, NOT or NEAR is an
    operator, and a question containing one raises OperationalError — which
    used to be swallowed into an empty result, so recall simply stopped working
    on some questions and nothing said why.
    """
    words = [w for w in _FTS_PUNCT.sub(" ", query).split() if len(w) > 2]
    return " OR ".join(f'"{w}"' for w in words[:12])


def recall(query: str, limit: int = 5, kind: str = "") -> list[Note]:
    """The notes most like this query, best first."""
    conn = _connect()
    where = " AND kind = ?" if kind else ""
    args: list = []
    if _fts:
        terms = _fts_query(query)
        if not terms:
            return recent(limit, kind)
        sql = ("SELECT text, kind, tags, created FROM notes "
               f"WHERE notes MATCH ?{where} ORDER BY rank LIMIT ?")
        args = [terms] + ([kind] if kind else []) + [limit]
    else:
        words = [w for w in query.split() if len(w) > 2][:5] or [query]
        like = " OR ".join("text LIKE ?" for _ in words)
        sql = ("SELECT text, kind, tags, created FROM notes "
               f"WHERE ({like}){where} ORDER BY created DESC LIMIT ?")
        args = [f"%{w}%" for w in words] + ([kind] if kind else []) + [limit]
    try:
        rows = conn.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        # A query FTS5 would not parse. Falling back to the most recent notes
        # beats returning nothing, which looks identical to having no memory.
        return recent(limit, kind)
    return [Note(r["text"], r["kind"], r["tags"], r["created"]) for r in rows]


def recent(limit: int = 5, kind: str = "") -> list[Note]:
    conn = _connect()
    sql = "SELECT text, kind, tags, created FROM notes"
    args: list = []
    if kind:
        sql += " WHERE kind = ?"
        args.append(kind)
    sql += " ORDER BY created DESC LIMIT ?"
    args.append(limit)
    rows = conn.execute(sql, args).fetchall()
    return [Note(r["text"], r["kind"], r["tags"], r["created"]) for r in rows]


def forget(fragment: str) -> int:
    """Delete notes containing this text. Returns how many went."""
    fragment = (fragment or "").strip()
    if len(fragment) < 3:
        return 0
    conn = _connect()
    cur = conn.execute("DELETE FROM notes WHERE text LIKE ?", (f"%{fragment}%",))
    conn.commit()
    return cur.rowcount


def count() -> int:
    return _connect().execute("SELECT COUNT(*) FROM notes").fetchone()[0]


CONSOLIDATE_AFTER = 40       # episodes before it is worth compressing them


def consolidate(limit: int = 40) -> str:
    """Fold a pile of episodes into a few durable lessons.

    Episodes accumulate one per task and individually say very little: this
    request took four steps, that one failed. Read together they say something
    worth keeping — which tools work on this machine, which paths come up, what
    reliably wastes a turn. So once there are enough, the small model is asked
    to write the lessons, those are stored as facts, and the episodes they came
    from are deleted.

    Cheap, and it runs at most once per batch of forty tasks.
    """
    from vb import backends

    episodes = recent(limit, kind="episode")
    if len(episodes) < CONSOLIDATE_AFTER:
        return ""
    listing = "\n".join(f"- {e.text}" for e in episodes)
    lessons = backends.ask_text(
        f"These are notes from tasks this assistant ran on one person's "
        f"computer:\n\n{listing}\n\n"
        f"Write at most five short lines stating what is reliably true here — "
        f"which tools work, which waste time, which folders come up. One fact "
        f"per line, no numbering, no preamble. Skip anything that happened "
        f"only once.",
        system="You compress many observations into a few durable facts.",
        tier="fast", timeout=60, max_tokens=300)
    if not lessons:
        return ""

    kept = 0
    for line in lessons.splitlines():
        line = line.strip().lstrip("-•* ").strip()
        if len(line) > 15 and remember(line, kind="fact", tags="learned"):
            kept += 1
    if not kept:
        return ""
    # Delete only what was actually read. `DELETE WHERE kind = 'episode'`
    # summarised the newest forty and destroyed everything older along with
    # them, so the more the buddy was used the more of its history one
    # consolidation threw away.
    conn = _connect()
    oldest = min(e.created for e in episodes)
    conn.execute("DELETE FROM notes WHERE kind = 'episode' AND created >= ?",
                 (oldest,))
    conn.commit()
    return f"Folded {len(episodes)} episodes into {kept} lasting facts."


def maybe_consolidate() -> str:
    """Consolidate only when there is enough to consolidate. Safe to call often."""
    try:
        count_episodes = _connect().execute(
            "SELECT COUNT(*) FROM notes WHERE kind = 'episode'").fetchone()[0]
        if count_episodes >= CONSOLIDATE_AFTER:
            return consolidate()
    except Exception:
        pass
    return ""


def context_for(request: str, limit: int = 4) -> str:
    """A short block of remembered things, for the top of a loop's prompt.

    Kept small on purpose. Memory that fills the context window makes the model
    worse at the thing it was actually asked to do.
    """
    notes = recall(request, limit=limit)
    if not notes:
        return ""
    lines = [f"- {n.text}" + (f" ({n.age()})" if n.kind == "episode" else "")
             for n in notes]
    return "What you already know:\n" + "\n".join(lines)
