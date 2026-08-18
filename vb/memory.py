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

from vb import config, embed

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
    # The meaning of each note, beside the words of it. Separate table rather
    # than a column on the FTS5 one, because FTS5 indexes what you give it and
    # a 3KB blob of floats is not something anybody should be searching for
    # text in. `note` is the notes rowid; a note with no row here has simply
    # not been embedded yet, which is a normal state and not an error.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS vectors ("
        "  note INTEGER PRIMARY KEY, model TEXT, vec BLOB)")
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
    cursor = conn.execute(
        "INSERT INTO notes (text, tags, kind, created) VALUES (?,?,?,?)",
        (text, tags, kind, time.time()))
    conn.commit()
    # Embedded here rather than in a sweep, so a note is searchable by meaning
    # the moment it exists. Guarded because it reaches the network: a model
    # that is not loaded must make `remember` slow at worst, never failed —
    # the note is already committed above and keyword search already finds it.
    try:
        _embed_note(cursor.lastrowid, text)
    except Exception:
        pass
    return True


def _embed_note(rowid: int, text: str) -> bool:
    if rowid is None or not embed.available():
        return False
    vector = embed.embed_one(text)
    if not vector:
        return False
    conn = _connect()
    conn.execute("INSERT OR REPLACE INTO vectors (note, model, vec) VALUES (?,?,?)",
                 (rowid, embed.model(), embed.pack(vector)))
    conn.commit()
    return True


def backfill(batch: int = 64, on_progress=None) -> int:
    """Embed every note that has no vector yet. Returns how many were done.

    Runs in batches because one text costs 109ms and sixty-four cost 15ms
    each — the difference between a minute and seven seconds over a few
    hundred notes. Safe to call repeatedly: it only ever looks at what is
    missing, so an interrupted run resumes rather than restarts.
    """
    if not embed.available():
        return 0
    conn = _connect()
    name = embed.model()
    rows = conn.execute(
        "SELECT n.rowid AS id, n.text AS text FROM notes n "
        "LEFT JOIN vectors v ON v.note = n.rowid AND v.model = ? "
        "WHERE v.note IS NULL", (name,)).fetchall()
    done = 0
    for start in range(0, len(rows), batch):
        chunk = rows[start:start + batch]
        vectors = embed.embed([r["text"] for r in chunk])
        if not vectors:
            break
        conn.executemany(
            "INSERT OR REPLACE INTO vectors (note, model, vec) VALUES (?,?,?)",
            [(r["id"], name, embed.pack(v)) for r, v in zip(chunk, vectors)])
        conn.commit()
        done += len(chunk)
        if on_progress:
            on_progress(done, len(rows))
    return done


def index_stats() -> dict:
    """What is indexed and what is not — for `/memory` and the panel."""
    conn = _connect()
    total = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    name = embed.model()
    vectors = conn.execute(
        "SELECT COUNT(*) FROM vectors WHERE model = ?", (name,)).fetchone()[0] \
        if name else 0
    return {"notes": total, "vectors": vectors, "model": name or "none",
            "db": str(db_path()),
            "bytes": db_path().stat().st_size if db_path().exists() else 0}


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
    """The notes most like this query, best first.

    Keyword and meaning, fused. Either alone has a failure mode the other does
    not: BM25 scores "what am I working on" against a note reading "the
    projects live in C:/Projects/MAIN" at exactly zero, because they share no
    word; vectors happily rank a note about the wrong file first because it is
    *about* files. Running both and combining the ranks keeps exact terms —
    paths, filenames, error strings — working while paraphrases start working
    too.
    """
    keyword = _keyword_recall(query, limit=max(limit * 4, 20), kind=kind)
    if not embed.available():
        return keyword[:limit]
    semantic = _vector_recall(query, limit=max(limit * 4, 20), kind=kind)
    if not semantic:
        return keyword[:limit]
    return _fuse(keyword, semantic)[:limit]


# Reciprocal rank fusion. The constant damps the top of each list so one
# search cannot dominate on a single confident hit; 60 is the value from the
# original paper and there is no local measurement here that justifies moving
# it, so it stays where the literature put it.
RRF_K = 60


def _fuse(*lists: list[Note]) -> list[Note]:
    """Combine ranked lists by position rather than by score.

    Scores cannot be compared across the two searches — BM25 is unbounded and
    cosine is -1..1 — so normalising them means inventing a conversion. Ranks
    need no conversion, which is the whole appeal.
    """
    scores: dict[str, float] = {}
    seen: dict[str, Note] = {}
    for ranked in lists:
        for position, note in enumerate(ranked):
            key = note.text
            seen.setdefault(key, note)
            scores[key] = (scores.get(key, 0.0)
                           + KIND_WEIGHT.get(note.kind, 1.0)
                           / (RRF_K + position + 1))
    order = sorted(scores, key=lambda k: -scores[k])
    return [seen[k] for k in order]


# A fact is something that stays true; an episode is one thing that happened
# once. Asked "what am I working on", the buddy answered with three episodes
# about counting files in a folder while "the projects live in
# C:/Projects/MAIN" sat below them — every episode mentions a task, so they
# crowd out the handful of notes that describe the user rather than a moment.
# Facts are not always right and episodes are not noise, so this is a thumb on
# the scale rather than a filter.
#
# `project` outranks `fact` because the fact table is not what its name
# suggests. Alongside things the user said, `consolidate()` writes machine-made
# observations about tooling — "`list_dir` reliably counts Python files in
# directories like ..." — and once facts were boosted those crowded out the
# curated one-line project descriptions, which are the notes that answer
# questions about the person rather than about the harness.
KIND_WEIGHT = {"project": 2.0, "fact": 1.6, "episode": 1.0}


def _vector_recall(query: str, limit: int, kind: str = "") -> list[Note]:
    """Nearest notes by meaning.

    **The vectors stay on disk.** They are read, scored and dropped on every
    search rather than held in a module-level cache: the whole point of an
    index that lives in a file is that idle memory costs nothing, and a buddy
    that sits in the tray all day should not be holding megabytes of floats it
    last used at breakfast. Reading them back is a sequential scan of one
    SQLite table, which at this size is a few milliseconds — far below the
    ~109ms the query's own embedding costs, so caching them would optimise the
    part that is already free.
    """
    vector = embed.embed_one(query)
    if not vector:
        return []
    conn = _connect()
    name = embed.model()
    sql = ("SELECT n.rowid, n.text, n.kind, n.tags, n.created, v.vec "
           "FROM vectors v JOIN notes n ON n.rowid = v.note "
           "WHERE v.model = ?")
    args: list = [name]
    if kind:
        sql += " AND n.kind = ?"
        args.append(kind)
    try:
        rows = conn.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []
    if not rows:
        return []

    scored = _rank(vector, rows)
    return [Note(r["text"], r["kind"], r["tags"], r["created"])
            for _score, r in scored[:limit]]


def _rank(query_vec: list[float], rows) -> list:
    """Cosine similarity of the query against every stored vector.

    numpy when it is there, plain Python when it is not. numpy is a dependency
    already, but the fallback is four lines and means a broken install degrades
    to slow rather than to no memory at all.
    """
    try:
        import numpy as np

        matrix = np.frombuffer(b"".join(r["vec"] for r in rows),
                               dtype=np.float32).reshape(len(rows), -1)
        q = np.asarray(query_vec, dtype=np.float32)
        # Normalising both sides turns the dot product into cosine. The +1e-9
        # is there because a zero vector is possible from a failed embed and
        # dividing by its norm would poison the whole column with NaN.
        norms = np.linalg.norm(matrix, axis=1) * float(np.linalg.norm(q)) + 1e-9
        sims = (matrix @ q) / norms
        order = np.argsort(-sims)
        return [(float(sims[i]), rows[i]) for i in order]
    except Exception:
        out = []
        for r in rows:
            v = embed.unpack(r["vec"])
            dot = sum(a * b for a, b in zip(v, query_vec))
            mag = (sum(a * a for a in v) ** 0.5) * (sum(b * b for b in query_vec) ** 0.5)
            out.append((dot / (mag or 1e-9), r))
        out.sort(key=lambda pair: -pair[0])
        return out


def _keyword_recall(query: str, limit: int = 5, kind: str = "") -> list[Note]:
    """The original BM25 search, unchanged. Still the half that gets exact
    terms right."""
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
