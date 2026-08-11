# VirtualBuddy (VB)

Local PC assistant. Voice or app commands -> runs tasks, manages files, controls Claude, reports back.
Zero budget. Everything local. Simple files a non-tech person can read.

**🌐 Website:** https://sahilsidhu7.github.io/VirtualBuddy/
**🧩 Skills repo:** https://github.com/SahilSidhu7/virtualbuddy-skills

## Install (Windows / macOS / Linux)
```
git clone https://github.com/SahilSidhu7/VirtualBuddy
cd VirtualBuddy
python install.py          # add --voice for offline speech
python app.py              # control panel
```
Update anytime: `python update.py` (git pull + deps + retrain). Needs Python 3.9+
and, for the local brain, [Ollama](https://ollama.com).

Your settings + trained model live in **`~/.virtualbuddy/`** (config.yaml, workspace,
models, data) — so they survive updates and work for the installed app. First launch
offers to train the brain; it works immediately either way.

## What you can ask it
Everyday things, by typing or by voice ("buddy, ..."):

| You say | Buddy does |
|---|---|
| "open chrome", "fire up vs code" | launches the app |
| "close spotify", "switch to my browser", "show my desktop" | window control |
| "search youtube for lofi", "google how to boil an egg" | searches that site in a real browser |
| "open youtube", "take me to gmail" | opens the site |
| "who won the world cup", "what's the weather in delhi" | free web lookup, answered in place |
| **"what's happening on my pc"** | CPU, memory, disk, battery, uptime, busiest apps, what's in front |
| "what's using my cpu", "what's eating my ram" | top processes, merged by app |
| "what apps do i have open" | list of open windows |
| "how much disk space do i have", "am i online" | drives / connection + live speed |
| "open my downloads", "where is my resume", "what did i just download" | folders and file search |
| "turn the volume down", "mute", "pause the music", "next track" | volume + media keys |
| "set a timer for 5 minutes", "remind me in an hour to stretch" | timers and reminders |
| "what's on my clipboard", "save my clipboard to a file" | clipboard |
| "shut down my pc", "restart", "sleep", "sign me out" | **asks yes/no first**, then does it |
| "lock my screen", "take a screenshot", "what time is it" | the basics |

Anything buddy doesn't know yet goes to the planner (composes primitives), then
the local LLM, then a free web search — and only then to Claude, if you opted in.

## Characters
duck · robot · crab · elf (pixel-art). Pick in the control panel or set
`character:` in config.yaml. Add your own: a folder in `assets/character/<name>/`
with `idle_0.png`, `idle_1.png`, `talk_0.png`. Regenerate defaults:
`python -m tools.make_sprites && python -m tools.make_pixels`.

## Parts
- `buddy/listener.py` - wake word + speech-to-text (offline, optional)
- `buddy/brain.py`     - figures out what you want (embeddings) + picks a skill
- `buddy/voice.py`     - talks back (text-to-speech)
- `buddy/skills/`      - one file = one kind of task
- `buddy/character/`   - tiny character that roams the screen
- `run.py`             - starts everything

## Run
```
pip install -r requirements.txt   # heavy voice deps optional, see file
python app.py                     # control panel: settings, character, launch, train
python run.py                     # text mode works with zero extra installs
python run.py --voice             # add voice once deps installed
python run.py --character         # show the on-screen buddy
```

## Control panel (`app.py`)
One window, 3 tabs:
- Settings - wake word, sensitivity, voice on/off, Claude command, launch buttons.
- Character - live preview + "Regenerate default sprites". Drop your own PNGs in
  `assets/character/` (named `idle_0.png`, `talk_0.png` ...) to reskin.
- Skills & Training - lists what buddy knows + runs the 2-bot training loop.

## The on-screen buddy
Real animated sprite (idle bob + blink, talk frames while answering).
- drag it anywhere
- click / double-click -> type a command
- right-click -> quick menu (time, screenshot, status, lock, settings, quit)
Sprites are generated locally: `python -m tools.make_sprites`.

## Modes
- Text: type commands in terminal (always works)
- Voice: say "buddy ..." then your command
- Character: click the buddy, then speak/type

## How it decides what to do
1. Turn your words into a vector (embedding).
2. Compare to every skill's example phrases.
3. Best match wins. If nothing close -> ask Claude to handle it.

## Where answers come from (saves Claude tokens)
1. Confident skill match -> run the skill (slots pull the details reliably).
2. Local LLM via Ollama -> answers + reasons offline, no tokens.
3. Looks like a question -> free web search (DuckDuckGo + Wikipedia, no key).
4. Only if all fail -> Claude CLI (last resort).

## Local brain (Ollama) + tool-calling
Buddy uses your local Ollama for general answers - offline, free, private.
It can also **call skills itself**: for anything the fast classifier isn't
sure about, the LLM decides which skill(s) to run - including compound
commands like "what time is it and lock my pc in 20 seconds" (runs both).
Set the model in `config.yaml` (`llm_model`). ~7B (e.g. `qwen2.5:latest`) is a
good balance. First reply after idle loads the model into RAM (slow once),
then fast; buddy keeps it warm 10 min.

## PC <-> mobile <-> PC sync
Command buddy from your phone or another PC on the same WiFi.
```
python run.py --server     # or the "Start server" button in the control panel
```
It prints a URL like `http://192.168.1.20:8770`. Open it on your phone
(same WiFi), enter the token from `config.yaml`, then type or tap 🎤 to talk.
Every command needs the token - change `server_token` from the default.

Control another PC (both running the server): add peers in the Sync tab (give
each a nickname and pick a default), then:
```
> on gaming-pc lock the screen
> tell laptop to take a screenshot
> take a screenshot          # no name -> goes to your default peer
```
Buddy relays it and shows the reply as `[gaming-pc] ...`. Nicknames ("the rig")
and the default target are set in the Sync tab or `config.yaml`
(`peers:` + `default_peer:`).

## Buddy learns your commands
Every time buddy runs a command it remembers what worked (a command→skill graph
under `~/.virtualbuddy/memory/`). Next time you say something similar, it reuses
the skill that worked before instead of re-guessing — so it gets more *yours* the
more you use it. Early on it asks "did I get that right?"; your yes/no tunes the
memory. Confirmed commands also become the training set the fine-tuner batches up
(`command_memory: true` to toggle).

Matching uses hashed n-grams computed in-process, so recall is instant. Set
`graph_vectors: embed` if you'd rather pay ~2s per command for looser paraphrase
matching from the embedding model.

## Dashboard
`vb --dashboard` (or the character's right-click menu) opens the control panel:
a chat box that talks to buddy directly — type, or press 🎙 and speak one command —
plus character picker, settings, sync, and the advanced training tools.

## Power-saving mode
Frees resources: unloads the LLM from RAM, skips it entirely. Skills, web
search, and corrections still work. Toggle in the control panel, in
`config.yaml` (`power_save: true`), or in text mode:
```
> !power on      # LLM off, memory freed
> !power off     # LLM back on
```

## Community skills
One file = one skill. Share yours, install others:
```
python -m tools.install_skill path\to\skill.py     # or a URL
> !train                                            # activate it in buddy
```
Template, registry, and a showcase website live in `../VB-others/`.

## Buddy learns from you (no tokens)
If buddy picks the wrong skill, correct it once and retrain:
```
> pull up my documents folder      # buddy guessed wrong
> !fix open_app                    # tell it the right skill
> !train                           # bakes it in (2-bot loop) + reloads
```
Also: `!skills` lists what buddy knows.

## Make the brain smarter locally (2-bot loop, no Claude tokens)
Two local bots improve intent matching by themselves:
- BUILDER (`tools/builder.py`) - makes training phrases + trains a small classifier.
- CRITIC  (`tools/critic.py`)  - tests it on unseen wording, logs every miss.
The loop feeds misses back to the builder until accuracy is high:
```
python -m tools.loop            # target 95%, up to 6 rounds
python -m tools.loop 0.9 4      # custom target / rounds
```
Check it still understands the everyday commands (routing only — never runs them):
```
python -m tools.selftest
```
Output -> `models/intent_clf.joblib`. The brain auto-uses it if present.
Hit 99% on first round with the starter skills. All local, offline, free.
