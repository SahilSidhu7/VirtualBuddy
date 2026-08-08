# VirtualBuddy v3 — Self-Growing Skills (Primitive Planner)

Status: design. Extends v2 (see `ARCHITECTURE_V2.md`). Goal in one line:
**buddy does tasks it was never coded for, by composing a small fixed set of safe
machine primitives — then remembers the working sequence as a new skill — using a
tiny local model, disk memory, no API keys, no paid tokens.**

---

## 1. The problem with the old mental model

Original idea: "user asks → if no skill, buddy web-searches and **writes a new
skill with the LLM**." That is code generation. A RAM-light local model (0.5–3B)
writes buggy, unsafe Python. It never worked reliably and it can wreck the machine.

We drop code generation. We keep the *outcome* the user wanted (buddy grows new
abilities) but change the *mechanism*.

## 2. Core idea — compose, don't generate

Two layers:

**A. Primitives (hand-coded once).** A fixed toolbox — the *only* ways buddy can
touch the machine. The model never writes these; it only calls them with arguments.
Because the set is small and reviewed, it is safe and testable.

**B. Planner + memory.** For an unknown command, a small local model produces a
**plan** = an ordered list of primitive calls. Buddy executes it (guarded). If it
worked, buddy **saves the plan as a learned skill** on disk. Next time the same
command is a memory hit — no model needed.

"buddy creates a skill" = **buddy records a working sequence of primitives**, not
generated code. Self-growing, safe, cheap.

## 3. The primitive toolbox

Hand-coded in `buddy/primitives/`. Each primitive: a Python function with a typed
signature + a one-line description + a `risk` level (`safe` / `confirm`).

| primitive | args | risk | notes |
|---|---|---|---|
| `open_app` | name | safe | reuse `slots.app` + `skills/system._open_app` |
| `close_window` | title | confirm | |
| `run_shell` | cmd | confirm | PowerShell/cmd; **always confirm** unless allowlisted |
| `read_file` | path | safe | |
| `write_file` | path, text | confirm | |
| `list_dir` | path | safe | |
| `type_text` | text | safe | pyautogui |
| `keypress` | keys | safe | e.g. `ctrl+s` |
| `mouse_click` | x, y | confirm | |
| `clipboard_get` / `clipboard_set` | (text) | safe | |
| `screenshot` | — | safe | reuse existing |
| `ocr_screen` | — | safe | optional; lets buddy *read* the screen |
| `http_get` | url | safe | |
| `wait` | seconds | safe | |

Everything buddy does on the machine = a sequence of these. That is the whole
answer to "how does buddy interact with the machine": **it only ever runs
primitives.** Adding a new capability = adding one reviewed primitive, rarely.

## 4. The pipeline (per command)

```
message
 1. feedback verdict?  -> record, done                 (existing)
 2. remote (peer)?     -> relay, done                  (existing)
 3. command graph      -> known plan/skill? run it      [disk, instant]   (existing)
 4. classifier         -> known hand-coded skill? run   [disk, instant]   (existing)
 5. PLANNER (new)      -> small LLM builds primitive plan
                          -> show plan, execute guarded
                          -> worked? SAVE as learned skill (graph)  [disk]
 6. info question?     -> web search                    (existing)
 7. Claude CLI         -> last resort                   (existing)
```

Steps 1–4 and 6–7 already exist. **v3 is step 5.** It slots into `_fallback` in
`buddy/agent.py`, before the current LLM-tools call (or replaces it).

## 5. The planner (step 5) in detail

Input: the user text + relevant recalled memories + the primitive list (as tool
schemas, same format as `tools_llm.build_tools()`).

Output: ordered `[{primitive, args}, ...]`.

Two model modes, pick by what's installed:
- **Tool-calling** (qwen2.5:3b/1.5b supports it): model emits tool calls directly.
  We already do single-shot tool calling in `agent._llm_tools`; the planner is the
  multi-step version.
- **JSON plan**: model returns a JSON array of steps. We parse + validate against
  the primitive schema. Reject/repair anything not in the toolbox.

Guardrails:
- Any step whose primitive is `risk: confirm` (or shell not on the allowlist) →
  buddy asks the user before running that step. Reuse the v2 feedback confirm loop.
- First N successful runs of a *new* learned skill are always confirmed, then trusted.
- Every step logged to episodic memory + `audit` (what ran, args, result).

Save on success: `cmdgraph.record(text, learned_skill_name)` plus the plan stored
in a new `plans/` store keyed by skill name. A learned skill = `{name, steps}`
runnable without the model.

## 6. Model + memory choices (the constraints)

- **Model**: `qwen2.5:3b` (fallback `1.5b`) via Ollama. ~2–3 GB RAM, no key, decent
  tool-calling. Used *only* on unknown commands — every learned command drops back
  to the instant disk path. Power-save unloads it (existing `llm.unload`).
- **Memory = disk**: `command_graph.json` (learned command→skill), `plans/*.json`
  (primitive sequences), episodic/semantic JSONL + numpy vecs (existing `memory/`).
  Grows on disk, ~0 RAM.
- Web search stays for *knowledge* questions only, never for building skills.

## 7. Safety (must-haves, not optional)

`run_shell`, `write_file`, `mouse_click`, `close_window` can damage the system.

- Allowlist of safe shell commands; everything else confirmed.
- Buddy previews the full plan before first execution; user approves.
- Destructive verbs (delete, format, rm, del, remove-item, kill) → always confirm.
- Audit log of every primitive run with args + result.
- Never auto-run a freshly-generated plan silently.

## 8. Build order

1. `buddy/primitives/` — 3–4 primitives first (open_app, run_shell(confirm),
   write_file(confirm), screenshot), each with schema + risk. **Minimal slice.**
2. `buddy/planner.py` — build plan (JSON mode first, simplest), validate, execute
   with confirm gate, save on success.
3. Wire into `agent._fallback` behind a config flag (`planner_enabled`).
4. Grow the primitive set + allowlist once the loop is proven.

---

## 9. Dashboard + character redesign (parallel track)

Current dashboard (`app.py`): 4-tab Notebook, buggy, exposes internals users
shouldn't see. Redesign goals:

- **Hide the learning/training internals.** No "2-bot training loop", no
  failures/score jargon in the user-facing UI. Training runs silently in the
  background (already auto-runs on first run). Move any dev-only controls behind an
  "Advanced" toggle or drop them from the shipped UI.
- **Text ↔ Voice = one toggle switch**, not two separate launch buttons. One
  "Start buddy" action + a mode toggle.
- **"Set character" button.** Changing character needs an app restart. After the
  user picks a new character, show a clear "Restart to apply" button that restarts
  buddy cleanly (kill running character proc + relaunch).
- **Buddy state animations** so the user always knows what's happening. Character
  has visible states: `idle`, `listening` (voice active), `thinking` (planner/LLM
  running), `working` (executing a primitive), `done`/`error`. Today only
  `idle`/`talk` exist (`character/character.py`). Add sprite states + a small status
  signal (glow/badge) the agent drives via a callback.
- Fix existing bugs: prompt bubble already has a watchdog (good); audit the rest
  (peer list refresh, sprite preview leaks, config comment stripping on save).

Character wiring: agent emits state events (`on_state("thinking")` etc.); the
character subscribes and swaps sprite sets. This reuses the existing `talk()`
mechanism, generalized to N states.
