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

```bash
git clone https://github.com/SahilSidhu7/VirtualBuddy
cd VirtualBuddy
pip install -r requirements.txt
python run.py
```

The buddy appears in the bottom-right of your screen. Click it to open the
panel, drag it anywhere, right-click for the menu.

`python run.py --cli` gives you the same thing in a terminal.

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

## The web layer

Two tiers, and the cheap one runs first.

| Tier | What it is | When it runs |
|---|---|---|
| HTTP | `httpx` + `trafilatura` extraction | always tried first, a few hundred ms |
| Browser | Playwright Chromium | page was blocked, or rendered nothing |

Chromium is a ~150MB download, so it is never fetched until a page actually
needs it. Search goes through DuckDuckGo's HTML endpoint with a SearXNG
fallback: no key, no quota.

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

| Skill | Does |
|---|---|
| `web_search` | search the web, list results with links |
| `research` | read several sources on a topic and write it up |
| `read_page` | fetch one page and give back its text |
| `extract_links` | list every link on a page |
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
  skills/       the skills themselves
  ui/           desktop sprite and command panel
tools/routetest.py   route-only self test (never executes skills)
```

## Testing

```bash
python tools/routetest.py
```

Routing is checked, execution is not: this suite must never launch apps or open
windows as a side effect of a test run.
