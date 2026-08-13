# VirtualBuddy

A small companion that lives on your desktop and runs prebuilt skills. Type or
talk to it, it finds the skill that matches, and either shows you the match or
just runs it.

Its main job is the web: searching, scraping, and researching across sites. All
of that works with no API keys, no accounts, and no cloud model. A local LLM is
optional and only makes the write-ups better.

```
you › research the best budget monitors
→ research(topic='best budget monitors')   [0.62]     Run  /  Other
```

## Install

**Windows:** download
[VirtualBuddy-Setup.exe](https://github.com/SahilSidhu7/VirtualBuddy/releases/latest/download/VirtualBuddy-Setup.exe)
and double-click it. 29MB, no admin rights, and setup offers to start it when
you sign in. There is also a
[portable zip](https://github.com/SahilSidhu7/VirtualBuddy/releases/latest/download/VirtualBuddy-portable.zip)
if you would rather it wrote nothing outside its own folder.

**From source, any OS:**

```bash
git clone https://github.com/SahilSidhu7/VirtualBuddy
cd VirtualBuddy
pip install -r requirements.txt
python run.py
```

The buddy appears in the bottom-right of your screen. Click it to open the
panel, drag it anywhere, right-click for the menu.

`python run.py --cli` gives you the same thing in a terminal, and
`python run.py --selftest` checks an install without opening a window.

### Starting with Windows

Tick the box during setup, or right-click your buddy and choose **Start with
Windows** at any time. It is a shortcut in your Startup folder: visible in
Explorer, deletable by hand, nothing written to the registry.

## How it works

Every skill declares the phrasings it answers to. At startup those phrases are
turned into vectors with hashed word and character n-grams (`vb/textvec.py`) —
no model download, no network, sub-millisecond. Your prompt is scored against
them by cosine similarity, and the best skill wins.

* **Manual mode** shows you the match, its confidence, and the arguments it
  pulled out of your sentence. Nothing runs until you say so.
* **Auto mode** runs the top match when it scores above `0.45`. Skills marked
  dangerous still ask.

Arguments come from `vb/slots.py`: strip the words that made the skill match,
keep what is left. `open spotify` gives `target=spotify`, `search the web for
tide times` gives `query=tide times`.

Similarity alone can't separate skills that share vocabulary — "open my
downloads" and "what's in my downloads" are one word apart and mean different
things. So a skill can also declare `triggers`: regexes that give it away.
Matching one adds a bounded bonus (max +0.34) to the cosine score, never enough
to win on keywords alone.

## The web layer

Two tiers, and the cheap one runs first.

| Tier | What it is | When it runs |
|---|---|---|
| HTTP | `httpx` + `trafilatura` extraction | always tried first, a few hundred ms |
| Browser | Playwright Chromium | page was blocked, or rendered nothing |

Chromium is a ~150MB download, so it is never fetched until a page actually
needs it. Search goes through DuckDuckGo's HTML endpoint with a SearXNG
fallback: no key, no quota.

## Your PC as a graph

Say **index my pc** once. The buddy walks your own folders (Desktop, Documents,
Downloads, Pictures, Videos, Music, and any project folders it finds) and stores
them in `~/.virtualbuddy/pc.db` as nodes and `contains` edges. Machine-generated
folders — `node_modules`, `.git`, `AppData`, `Windows`, `Program Files` — are
skipped, so the index stays about your stuff.

On this machine that's 48,000 files in under 3 seconds. Re-running is a diff:
new files are added, deleted ones are dropped.

Then you can ask:

```
where did i put my resume          what's eating my disk space
what's in my downloads             what did i work on today
how many pdfs do i have            what's on my pc
```

Lookups are FTS5 for candidates, then textvec to rank them by meaning, so
"holiday photos" finds a folder called `Goa 2024` if the words line up.

### Writing files

`create a file called notes.txt on my desktop saying remember the milk`, `add a
line to notes.txt saying call mum`, `in notes.txt replace monday with tuesday`.

Three rules the buddy will not break: it never writes inside Windows, Program
Files or ProgramData; it never overwrites an existing file unless you say
"overwrite"; and it will not append text to a non-text file. Moving and deleting
always ask first, and deleting goes to the Recycle Bin.

When you give a bare filename, it's matched against the graph — but only by
exact name, never fuzzily. A fuzzy match is right for *find my tax pdf* and
catastrophic for *append this to X*.

## Smart mode (optional)

If [Ollama](https://ollama.com) is running with `qwen3:4b`, the research and
read skills use it to write up what they found. That model runs in about 2.6GB
of VRAM, so a 4GB card handles it.

Without it, every skill still works: you get the extracted text and the sources
instead of a synthesis. The right-click menu downloads the model for you.

## Voice

Press **Talk** and speak. Recognition is offline, via Vosk. The first press
installs `vosk` and `sounddevice` and downloads a 40MB English model into
`~/.virtualbuddy/models`.

## Skills

**Web**

| Skill | Does |
|---|---|
| `web_search` | search the web, list results with links |
| `research` | read several sources on a topic and write it up |
| `read_page` | fetch one page and give back its text |
| `extract_links` | list every link on a page |

**Your PC**

| Skill | Does |
|---|---|
| `index_pc` | scan your folders into the graph |
| `find_file` | find a file or folder anywhere |
| `whats_in` | list what's inside a folder |
| `disk_hogs` | biggest files and heaviest folders |
| `recent_files` | what you changed recently |
| `pc_summary` | totals and a breakdown by file type |

**Files**

| Skill | Does |
|---|---|
| `create_folder` / `create_file` | make things |
| `read_file` | show a text file |
| `edit_file` | append a line, or replace text |
| `move_file` | move or rename (asks first) |
| `delete_file` | send to the recycle bin (asks first) |

**Task manager**

| Skill | Does |
|---|---|
| `running_apps` | what's running, CPU and memory per app |
| `kill_app` | close a program (asks first) |
| `pc_health` | battery, disk space, uptime |
| `add_task` / `list_tasks` / `complete_task` | personal to-do list |

**Apps**

| Skill | Does |
|---|---|
| `open_app` | launch an installed application |
| `open_site` | open a website |
| `open_folder` | open a folder |

### Adding one

Drop a module in `vb/skills/`. It is picked up at startup.

```python
from vb import slots
from vb.registry import Result, skill

@skill("say_hello",
       "Greet someone by name",
       ["say hello to priya", "greet my friend"],
       slots=lambda text: {"name": slots.after(text, ("hello", "greet"))})
def say_hello(name: str = "", **_) -> Result:
    return Result(text=f"Hello, {name or 'you'}.")
```

`phrases` is what the router matches against, so write them the way you would
actually say them. Set `danger=True` on anything irreversible and it will ask
first even in auto mode.

## Layout

```
vb/
  router.py     semantic search over the skill list
  registry.py   the @skill decorator and discovery
  slots.py      pulling arguments out of a sentence
  agent.py      route, confirm, run
  llm.py        optional Ollama client
  voice.py      optional offline speech input
  web/          search, tiered fetch, extraction
  pc/           the file graph, and guarded file editing
  skills/       the skills themselves
  ui/           desktop sprite and command panel
tools/routetest.py   route-only self test (never executes skills)
```

## Testing

```bash
python tools/routetest.py
```

79 phrasings, 60 declared and 19 deliberately unseen. The unseen ones are the
point: a declared phrase scores 1.00 and proves nothing.

Routing is checked, execution is not. This suite must never launch an app, open
a window, or write a file as a side effect of a test run — `kill_app` and
`delete_file` are real.
