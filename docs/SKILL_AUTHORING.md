# Writing a VirtualBuddy skill

This file is the full contract for authoring a buddy skill. When buddy can't do
something, it hands this guide + the failed command to Claude, and Claude writes a
new skill file that follows these rules exactly. Follow it precisely — the file is
validated and loaded automatically.

## The contract

A skill is a single Python file that defines a module-level list named `SKILLS`:

```python
SKILLS = [
    {
        "name": "unique_snake_case_name",   # required, unique across all skills
        "desc": "one short line",           # optional but recommended
        "phrases": ["say it like this",     # required, 4-8 example phrasings
                    "and this way too"],     # the classifier learns from these
        "run": my_function,                  # required, callable (see below)
    },
]
```

### The run function

```python
def my_function(text, ctx):
    # text: the user's exact command, e.g. "what's the weather in Delhi"
    # ctx:  a dict with:
    #   ctx["cfg"]   -> settings dict (workspace, ollama_url, etc.)
    #   ctx["mem"]   -> memory (optional; ctx.get("mem"))
    #   ctx["graph"] -> command graph (optional)
    return "a short human string to say back"   # ALWAYS return a string
```

Rules for `run`:
- Return a **short string** (one or two sentences). Never print; never return None.
- Catch your own errors and return a friendly message instead of raising.
- Do NOT block forever. Use timeouts on network calls.
- Extract details (numbers, filenames, durations) with the helpers below.

## Helpers you SHOULD use (already installed, no new deps)

```python
from buddy import slots        # deterministic detail extraction
slots.app(text)                # "open chrome" -> "chrome"
slots.filename(text)           # -> "notes.txt"
slots.number(text)             # first integer
slots.duration_seconds(text)   # "in 5 min" -> 300
slots.clean(text)              # strip polite filler

from buddy import llm          # local Ollama model (free, offline)
llm.ask("summarise: ...", ctx["cfg"])   # -> string answer

from buddy import primitives   # safe machine actions
primitives.run("open_app", {"name": "chrome"})
primitives.launch_app("code")  # PATH-independent app launch (Windows-safe)
# web primitives (if web_automation on): web_open, web_read, web_click, web_fill
```

Prefer the standard library (`urllib`, `json`, `os`, `subprocess`, `datetime`) over
new pip packages. If you truly need a package, note it in `desc` — but avoid it.

## Style rules

- Keep the whole file small and readable.
- One file may define several related skills in `SKILLS`.
- Functions that touch the machine should be safe and reversible; never delete or
  overwrite user data without it being the explicit request.
- Never hard-code secrets. Read config from `ctx["cfg"]` when needed.
- Match the tone of the built-in skills: concise, plain, no emojis unless asked.

## A complete example — weather via a free API

```python
"""Weather for a city using the free wttr.in service (no key)."""
import json, urllib.request, urllib.parse
from buddy import slots

def _city(text):
    t = slots.clean(text)
    for w in ("weather", "in", "for", "whats", "what is", "the"):
        t = t.replace(w, " ")
    return " ".join(t.split()) or "here"

def weather(text, ctx):
    city = _city(text)
    url = "https://wttr.in/" + urllib.parse.quote(city) + "?format=j1"
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.load(r)
        cur = data["current_condition"][0]
        return f"{city.title()}: {cur['temp_C']}°C, {cur['weatherDesc'][0]['value']}."
    except Exception as e:
        return f"Couldn't get weather for {city}: {e}"

SKILLS = [
    {"name": "weather", "desc": "current weather for a city",
     "phrases": ["what's the weather", "weather in London", "is it raining",
                 "temperature outside", "how hot is it in Delhi"],
     "run": weather},
]
```

## Output format when Claude generates a skill

Return **only** the complete Python file, nothing else — no markdown fences, no
prose before or after. It must import cleanly, define `SKILLS`, and each skill's
`run` must be callable. The command that triggered this should route to the new
skill afterwards, so make the `phrases` cover how the user actually said it.
