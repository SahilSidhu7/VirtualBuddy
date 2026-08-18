"""Skills the buddy writes for itself.

This is the part that makes a run worth more than its answer. When a task
finishes and the critic is satisfied, the model is asked to write down how it
did it — the steps that worked, the things that wasted a turn, the shape of the
arguments that turned out to matter. That goes in a markdown file, and the next
time a similar request arrives the file is pasted into the prompt before the
model chooses anything.

Procedural memory, not code. The file cannot execute, so a bad skill costs a
worse prompt and nothing else; an executable one written by a 8B model at two
in the morning could cost a directory. It also means a skill can be read,
edited and deleted by hand, in a text editor, which is the only review process
that actually happens.

The format is deliberately close to the agentskills.io convention Hermes uses,
so a skill written here is legible there and the other way round.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from vb import backends, config

MAX_SKILLS = 200
MAX_INJECTED = 2            # how many go into a prompt at once
SLUG = re.compile(r"[^a-z0-9]+")


def skills_dir() -> Path:
    """Where learned skills live: the user's data folder, never the install
    directory, so an update or a reinstall cannot wipe what it learned."""
    return config.data_dir("skills")


@dataclass
class Learned:
    name: str
    title: str
    triggers: list[str]
    body: str
    path: Path
    # How many times this note has been pasted into a prompt. Named honestly:
    # an earlier version called it `used` and reported it as usefulness, when
    # all it ever counted was being shown.
    shown: int = 0
    created: float = 0.0

    def as_prompt(self) -> str:
        return f"### {self.title}\n{self.body.strip()}"


# ------------------------------------------------------------------ storage
FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.S)


def _parse(path: Path) -> Learned | None:
    try:
        text = path.read_text("utf-8")
    except OSError:
        return None
    match = FRONT.match(text)
    if not match:
        return None
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip().lower()] = value.strip()
    triggers = [t.strip().lower() for t in meta.get("triggers", "").split(",")
                if t.strip()]
    if not triggers:
        return None
    return Learned(
        name=meta.get("name", path.stem),
        title=meta.get("title", meta.get("name", path.stem)),
        triggers=triggers,
        body=match.group(2).strip(),
        path=path,
        shown=int(meta.get("shown", meta.get("used", "0")) or 0),
        created=float(meta.get("created", "0") or 0),
    )


def all_learned() -> list[Learned]:
    out = []
    for path in sorted(skills_dir().glob("*.md")):
        parsed = _parse(path)
        if parsed:
            out.append(parsed)
    return out


def _slug(text: str) -> str:
    return SLUG.sub("-", text.lower()).strip("-")[:60] or "skill"


# Words that mark the end of the *task* and the start of the *place it was done
# in*. "find the largest file **in** the datasets folder" is the same procedure
# as "find the largest file **in** Downloads", and the note is only worth
# keeping once.
_PREPOSITIONS = {"in", "of", "on", "from", "under", "inside", "within",
                 "for", "at"}
_FILLER = {"a", "an", "the", "and", "my", "this", "specific", "user"}
# Different words for the same thing. Whichever the model reached for that turn
# should not decide whether a note is a duplicate.
_SYNONYMS = {"directory": "folder", "dir": "folder", "dirs": "folder",
             "folders": "folder", "files": "file", "sizes": "size",
             "space": "size", "py": "python", "lines": "line"}


def _shape(name: str) -> str:
    """The task a note is about, with the particular place stripped off.

    Comparing the *bodies* was tried first and does not work: measured over all
    4,950 pairs of the 100 notes one unguarded run produced, two notes about
    genuinely different jobs ("count the lines in README", "check disk usage")
    scored 0.671, while a pair that really was the same job scored 0.624. The
    prose overlaps more than the meaning does, so there is no threshold that
    separates them.

    The title does separate them, once the place is removed — cutting at the
    first preposition folds those 100 notes into 36 with no cluster mixing two
    different jobs. No list of folder names is needed, which matters because
    the next machine's folders will be different ones.
    """
    words = []
    for word in re.split(r"[-_]+", name.lower()):
        if not word:
            continue
        if word in _PREPOSITIONS:
            break
        if word in _FILLER:
            continue
        words.append(_SYNONYMS.get(word, word))
    return " ".join(words) or name.lower()


def _near_duplicate(title: str) -> Learned | None:
    """An existing note about the same task, or None."""
    want = _shape(_slug(title))
    for note in all_learned():
        if _shape(note.name) == want:
            return note
    return None


def _add_triggers(note: Learned, triggers: list[str]) -> None:
    """Widen an existing note to also fire on a new phrasing."""
    merged = list(note.triggers)
    for t in triggers:
        if t not in merged:
            merged.append(t)
    merged = merged[:12]
    if merged == note.triggers:
        return
    try:
        raw = note.path.read_text("utf-8")
        note.path.write_text(
            re.sub(r"^triggers:.*$", "triggers: " + ", ".join(merged),
                   raw, count=1, flags=re.M), "utf-8")
        note.triggers = merged
    except OSError:
        pass


# An absolute path in a procedure note is a note that only works once. The
# model is told to generalise and does not reliably do it, so the path is taken
# out here, where it is a two-line certainty rather than an instruction.
# The quotes around a path are part of what has to be replaced. Substituting
# only the path itself turned `Path(r"C:/Projects")` into `Path(r""<FOLDER>"")`
# — which Python parses, as a chained comparison, and means nothing.
_ABS_PATH = re.compile(
    r"""(?P<open>r?["'])?"""
    r"""(?:[A-Za-z]:[\\/][^\s"'`,;)]*|(?<![\w/])/(?:home|Users)/[^\s"'`,;)]*)"""
    r"""(?(open)["']|)""")

# The placeholder has to survive being pasted into a script. An earlier version
# substituted the words "the folder the user names", which produced notes
# containing `pathlib.Path(the_folder_the_user_names)` — a NameError the model
# then copied faithfully. A quoted string is a placeholder a person reads as
# one and Python parses as one.
PLACEHOLDER = '"<FOLDER>"'


def _generalise(body: str) -> str:
    return _ABS_PATH.sub(PLACEHOLDER, body)


# Tool calls the note tells a future run to make: `disk_hogs(where='memory')`.
_MENTIONED = re.compile(r"\b([a-z_][a-z0-9_]{2,})\s*\(", re.I)
_PROSE_WORDS = {"run", "use", "call", "get", "print", "open", "the", "and",
                "then", "with", "code", "step", "note", "for", "see"}


def _verify(body: str, outcome) -> str:
    """Why this note should not be saved, or '' when it is fine.

    The critic checks the answer. Nothing checked the note *about* the answer,
    and the notes turned out to be where the fabrication went: one claimed
    `disk_hogs(where='memory')` was the way to find memory hogs, when
    `disk_hogs` takes a folder path and the run had never called it. That note
    was then pasted into every later memory question as "your own notes".

    The rule that catches it is blunt and holds: a procedure may only name
    tools the run it came from actually used and got a result from. Anything
    else is the model writing fiction about its own work.
    """
    from vb import tools

    used = {s.tool for s in outcome.steps if s.ok}
    known = tools.all_tools()
    for name in set(_MENTIONED.findall(body)):
        lowered = name.lower()
        if lowered in _PROSE_WORDS or lowered not in known:
            continue           # prose, or a Python call — not a tool claim
        if lowered not in used:
            return (f"it recommends {name}(), which this run never "
                    f"successfully used")
    return ""


def save(title: str, triggers: list[str], body: str) -> Learned | None:
    """Write a skill file. Returns None when it is not worth keeping."""
    title = (title or "").strip()
    body = _generalise((body or "").strip())
    triggers = [t.strip().lower() for t in triggers if t.strip()][:8]
    if not title or not triggers or len(body) < 40:
        return None
    if len(all_learned()) >= MAX_SKILLS:
        return None

    name = _slug(title)
    path = skills_dir() / f"{name}.md"
    if path.exists():
        # Learning the same task twice must not silently replace the note —
        # and especially not a note the user has edited by hand, which is the
        # whole reason these are plain markdown. Keep what is there.
        return _parse(path)

    twin = _near_duplicate(title)
    if twin is not None:
        # The same procedure under a different name. Matching on the slug alone
        # was not enough: one folder-counting procedure had been saved eight
        # times as count-py-files, -in-folder, -in-directory, -in-docs-folder
        # and so on, and because `matching()` picks by word overlap a single
        # request pulled several of them into the prompt at once — the same
        # instructions repeated, crowding out the transcript they were meant to
        # help with. Fold the new triggers into the note that already exists.
        _add_triggers(twin, triggers)
        return twin
    front = (f"---\nname: {name}\ntitle: {title}\n"
             f"triggers: {', '.join(triggers)}\n"
             f"created: {time.time():.0f}\nshown: 0\n---\n\n")
    try:
        path.write_text(front + body + "\n", "utf-8")
    except OSError:
        return None
    return _parse(path)


def forget(name: str) -> bool:
    path = skills_dir() / f"{_slug(name)}.md"
    try:
        path.unlink()
        return True
    except OSError:
        return False


def _bump(learned: Learned) -> None:
    """Record that a note was shown. Never let a counter break a run.

    The count is re-read from the file rather than taken from the in-memory
    object, which may be stale — bumping the same `Learned` twice previously
    wrote `1` both times.
    """
    try:
        text = learned.path.read_text("utf-8")
        current = re.search(r"^shown: (\d+)$", text, re.M)
        now = int(current.group(1)) + 1 if current else learned.shown + 1
        if current:
            text = re.sub(r"^shown: \d+$", f"shown: {now}", text, count=1, flags=re.M)
        else:
            text = re.sub(r"^used: \d+$", f"shown: {now}", text, count=1, flags=re.M)
        learned.path.write_text(text, "utf-8")
        learned.shown = now
    except (OSError, ValueError):
        pass


# ------------------------------------------------------------------ recall
_WORD = re.compile(r"[a-z0-9]{3,}")


def matching(request: str, limit: int = MAX_INJECTED) -> list[Learned]:
    """Skills whose triggers overlap this request, best first.

    Word overlap, not a model call and not an embedding. Selecting which
    instructions to show costs nothing, which is the only reason it can happen
    on every single request.
    """
    words = set(_WORD.findall((request or "").lower()))
    if not words:
        return []
    scored = []
    for learned in all_learned():
        hits = 0
        for trigger in learned.triggers:
            parts = set(_WORD.findall(trigger))
            if parts and parts <= words:
                hits += 2                      # whole phrase present
            elif parts & words:
                hits += 1
        if hits:
            scored.append((hits, learned.shown, learned))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [row[2] for row in scored[:limit]]


def context_for(request: str) -> str:
    """The block of learned instructions to put in front of the model."""
    found = matching(request)
    if not found:
        return ""
    for learned in found:
        _bump(learned)
    blocks = "\n\n".join(l.as_prompt() for l in found)
    return ("You have done something like this before. Your own notes:\n\n"
            f"{blocks}\n\n"
            "Follow them where they fit, and ignore them where the request "
            "differs.")


# ------------------------------------------------------------------ writing
SYSTEM = ("You write short, practical procedure notes for yourself to reuse. "
          "You are specific about commands and paths. You never pad.")

PROMPT = """You just finished this request successfully:
{request}

These are the steps you actually ran:
{steps}

Write a note so that next time you can do it in fewer steps. Format exactly:

TITLE: a short name for the procedure, under eight words
TRIGGERS: four or five comma-separated phrases a user might say to ask for this
STEPS:
1. what to do first, naming the tool and the shape of its arguments
2. ...
PITFALLS:
- anything that wasted a step this time, and what to do instead

Rules:
- Write the general procedure, not this one request. If the request named a
  particular folder or site, say "the folder the user names", not the path.
- Only include a pitfall you actually hit. Do not invent warnings.
- If this task was trivial enough that a note would not help, reply with
  exactly: SKIP
"""


def _section(text: str, name: str) -> str:
    match = re.search(rf"^{name}:\s*(.*?)(?=^[A-Z]{{4,}}:|\Z)", text,
                      re.S | re.M)
    return match.group(1).strip() if match else ""


def learn_from(outcome) -> Learned | None:
    """Turn a successful run into a reusable note. None when not worth it.

    Deliberately cheap and deliberately fussy. It only fires on runs that took
    real work, and the model is given an explicit way out — SKIP — because a
    library full of notes about listing a directory is worse than an empty one.
    """
    # One good step is not too small to learn from — it is the best case. The
    # note worth writing is "this took one well-formed script, here it is",
    # and gating on step count threw exactly those away while keeping the
    # six-step flounders. What matters is that a step actually produced
    # something and the request reached the loop at all.
    from vb import critic
    productive = [s for s in outcome.steps
                  if s.ok and critic.clean_output(s.output)]
    if not productive or not outcome.answer:
        return None
    if config.get("learn_skills", "auto") == "off":
        return None

    transcript = "\n".join(
        f"{s.n}. {s.describe()} -> {'ok' if s.ok else 'FAILED'}: {s.output[:180]}"
        for s in outcome.steps)
    # The fast tier, and a short leash. This runs after the user already has
    # their answer, so every second here is a second they wait for nothing.
    reply = backends.ask_text(
        PROMPT.format(request=outcome.request[:400], steps=transcript[:2500]),
        system=SYSTEM, tier="fast", timeout=45, max_tokens=400)
    if not reply or reply.strip().upper().startswith("SKIP"):
        return None

    title = _section(reply, "TITLE").splitlines()[0].strip() if _section(reply, "TITLE") else ""
    triggers = [t for t in _section(reply, "TRIGGERS").replace("\n", " ").split(",")]
    body_steps = _section(reply, "STEPS")
    pitfalls = _section(reply, "PITFALLS")
    if not body_steps:
        return None
    body = f"**Steps**\n{body_steps}"
    if pitfalls:
        body += f"\n\n**Pitfalls**\n{pitfalls}"

    wrong = _verify(body, outcome)
    if wrong:
        # Silently dropped. A note that fails this check is not a note worth
        # showing the user a warning about; it is the model having made
        # something up, and the right response is to keep it out of the prompt.
        return None
    return save(title, triggers, body)


def summary() -> str:
    found = all_learned()
    if not found:
        return "Nothing learned yet."
    lines = [f"  {l.title}  ·  shown {l.shown}×  ·  {', '.join(l.triggers[:3])}"
             for l in sorted(found, key=lambda x: -x.shown)]
    return f"{len(found)} learned skills:\n" + "\n".join(lines)
