# VirtualBuddy v2 — "The Employee" Architecture

> Goal: turn buddy from a **command router** into a **continuously-learning employee**.
> It remembers, it learns what you teach it, it looks things up, it acts on the machine,
> and over time it gets *taught* (fine-tuned) so the brain itself knows the job — not just a lookup table.
>
> This document is the map. Every subsystem below has a folder under `buddy/`.
> The old MVP still runs; v2 is added **alongside** it and switched on by config flags.

---

## 1. The human analogy (how the pieces map to a person)

| Human faculty | VirtualBuddy part | Folder | Backed by |
|---|---|---|---|
| Senses (hear/read a command) | listener / server / control panel | `buddy/listener.py`, `buddy/net/` | Vosk, HTTP |
| **Short-term memory** (what we just said) | working memory | `buddy/memory/memory.py` | in-process ring buffer |
| **Episodic memory** (things that happened) | event log | `buddy/memory/store.py` | JSONL + embeddings |
| **Semantic memory** (facts you told me) | knowledge store | `buddy/memory/store.py` | JSONL + embeddings |
| **Procedural memory** (how to do things) | skills + learned adapters | `buddy/skills/`, `models/adapters/` | Python + LoRA |
| **Reflexes** (instant, no thinking) | intent classifier | `buddy/brain.py` | TF-IDF / cosine |
| **Deliberate thought** | the brain (small LLM) | `buddy/llm.py` + brain host | Ollama |
| **Hands** (act on the world) | executor | `buddy/actions/executor.py` | skills + guarded shell |
| **Learning from a mentor** | feedback loop | `buddy/learning/feedback.py` | ask "did I do that right?" |
| **Studying / going to school** | teaching pipeline | `buddy/learning/teach.py` | QLoRA fine-tune (server GPU) |
| **Looking it up** | research | `buddy/learning/learn.py` | web skill + distill |

The design principle from the research: the 2025/26 agent field converged on the
**episodic + semantic + procedural** memory taxonomy (Letta's core/recall/archival tiers,
Mem0's bolt-on memory layer). We adopt the same three tiers but keep storage dead simple
(JSONL + a numpy cosine index) so the light client stays torch-free.

---

## 2. The learning loop (the heart of v2)

```
        you talk to buddy
               │
               ▼
      ┌──────────────────┐     recall relevant memories (cosine top-k)
      │   MEMORY (recall) │◀──────────────────────────────┐
      └────────┬─────────┘                                │
               ▼                                          │
      ┌──────────────────┐   confident?  yes → run skill  │
      │  BRAIN (route)    │───────────────────────────────┤
      └────────┬─────────┘   no → deliberate (LLM+tools)  │
               ▼                                          │
      ┌──────────────────┐                                │
      │  EXECUTOR (act)   │  runs the skill on the machine │
      └────────┬─────────┘                                │
               ▼                                          │
      ┌──────────────────┐  first N times per skill:      │
      │ FEEDBACK (ask)    │  "did I do that right?"        │
      └────────┬─────────┘                                │
               ▼                                          │
      writes an EPISODE + (if corrected) a LESSON ────────┘
               │
               ▼   when enough lessons pile up
      ┌──────────────────┐
      │  TEACH (fine-tune)│  QLoRA on the server GPU → new adapter
      └──────────────────┘  brain now *knows* it, no lookup needed
```

Two speeds of learning, deliberately separated:

1. **Fast / cheap — memory (instant).** Anything you tell buddy to learn, or any correction,
   is embedded and written to the store immediately. Recalled on the next relevant command.
   This is RAG. No GPU, works on the phone and laptop.
2. **Slow / heavy — teaching (batched).** Lessons accumulate. Once `teach_after_n_lessons`
   pile up, the **server** (1050ti) runs a small QLoRA job that bakes the procedural knowledge
   into a LoRA adapter for the chosen small model. The brain then handles those cases without
   a lookup. This is the "going to school at night" step.

> **Why not fine-tune on every lesson?** Research is blunt: a 4GB 1050ti is below the comfortable
> QLoRA floor. It *can* train 0.5B–1.5B models with Unsloth's memory optimizations, but each run
> is minutes, not milliseconds, and per-lesson training causes catastrophic forgetting. So we
> **batch** and use **adapter isolation** (one adapter per skill-domain, O-LoRA-style orthogonality
> the research recommends) to add knowledge without erasing the old.

---

## 3. Three-node deployment (server + laptop + phone)

```
   ┌───────────────────────────────────────────────┐
   │  SERVER  (1050ti)      role: "server"          │
   │  • Ollama (brain model + embeddings)           │
   │  • brain API  buddy/net/brain_server.py :8771  │
   │  • the ONE source-of-truth memory store        │
   │  • teaching pipeline (QLoRA, GPU)              │
   └───────────────▲───────────────▲───────────────┘
                   │ HTTP+token     │ HTTP+token
        ┌──────────┴──────┐   ┌─────┴──────────┐
        │ LAPTOP          │   │ PHONE          │
        │ role: "client"  │   │ role: "client" │
        │ • UI + character │   │ • thin UI      │
        │ • listener/voice │   │ • send command │
        │ • NO torch       │   │ • NO torch     │
        └─────────────────┘   └────────────────┘
```

- The **server** holds the brain, the memory, and does the heavy learning. It carries the torch/
  unsloth stack (`requirements-server.txt`).
- The **laptop and phone** are **clients**: they capture a command, POST it to the brain API,
  render the reply, and animate the character. They stay light (existing `requirements.txt`, no torch).
- `role: "standalone"` (the default, unchanged) keeps everything on one machine — nothing about
  the current single-PC experience breaks.

The existing `buddy/server.py` (phone → PC command relay) stays for peer/relay commands. The new
`buddy/net/` is specifically the **brain** channel: recall + route + act + learn against the one
server brain, so laptop and phone share **the same memory and the same learned adapters**.

---

## 4. On-screen character: sit vs roam

`buddy/character/roam.py` adds a physics layer to the existing overlay:

- **Sit** (`roam: false`, default): current behaviour — the buddy stays where you drop it.
- **Roam** (`roam: true`): the buddy treats the **top edge of the taskbar as the ground** and
  walks left/right along it, idling and turning at the screen edges, with gravity so that if you
  drag it up and let go it falls back to the taskbar floor.

Technique (from desktop-pet research — TaskSonic / convai-desktop-pet): a frameless, always-on-top,
transparent-color window; a simple `(x, y, vx, vy)` integrator; the "floor" y is
`screen_height - taskbar_height`. Dragging suspends physics; releasing resumes it.

---

## 5. Folder map (what lives where)

```
buddy/
  memory/            # human-like memory (NEW)
    store.py         #   vector store: JSONL + numpy cosine index  [WORKING]
    memory.py        #   episodic/semantic/procedural tiers + recall/remember API  [WORKING]
  learning/          # continuous learning (NEW)
    learn.py         #   "learn X" → web lookup → distill → remember (+ draft skill)  [WORKING core]
    feedback.py      #   "did I do that right?" loop → writes lessons  [WORKING]
    teach.py         #   batch QLoRA fine-tune on server GPU → adapter  [SCAFFOLD, guarded]
  actions/           # the hands (NEW)
    executor.py      #   one safe entry point to run a skill/tool on the machine  [WORKING wrapper]
  net/               # 3-node brain channel (NEW)
    brain_server.py  #   FastAPI/stdlib brain API (recall+route+act+learn)  [WORKING core]
    brain_client.py  #   client that talks to a remote brain  [WORKING core]
  character/
    roam.py          #   sit-vs-roam taskbar physics (NEW)  [WORKING]
    character.py     #   existing overlay (unchanged)
  brain.py, llm.py, agent.py, skills/ ...   # existing MVP, unchanged
tools/               # existing 2-bot training loop (unchanged) — feeds the classifier
requirements.txt         # light client (no torch)         — laptop & phone
requirements-server.txt  # heavy server (torch, unsloth)   — 1050ti brain host  (NEW)
```

Status tags: **WORKING** = runnable now. **SCAFFOLD** = real interface + guarded stub; the
GPU-heavy body lands when the server stack is installed, and no-ops cleanly on a light client.

---

## 6. Migration — phased, nothing breaks

- **Phase 0 (done in this pass):** folders, interfaces, config flags, memory store, feedback loop,
  roam physics, brain client/server core, teach scaffold. All behind flags; `role: standalone` +
  `memory_enabled` default keep single-PC behaviour intact.
- **Phase 1:** wire memory recall into `agent.handle` (prepend recalled memories to the LLM prompt)
  and wire the feedback ask after a skill runs. Small edits to `agent.py`.
- **Phase 2:** stand up the server — install `requirements-server.txt` on the 1050ti, set
  `role: server`, point laptop/phone at `brain_host`. Shared memory goes live.
- **Phase 3:** turn on teaching — first real QLoRA run once lessons accumulate; adapter loaded by Ollama.
- **Phase 4:** roam mode in the control panel; polish.

Each phase is independently shippable and reversible by flipping its flag.

---

## 7. Research basis

- Agent memory taxonomy (episodic/semantic/procedural; core/recall/archival tiers): Letta/MemGPT, Mem0.
- On-device QLoRA feasibility on 4GB (0.5–1.5B models, Unsloth optimizations): Unsloth docs.
- Continual learning without forgetting (LoRA adapter isolation, O-LoRA orthogonality): CL-LoRA / O-LoRA.
- Desktop-pet taskbar physics (transparent always-on-top window, gravity): TaskSonic, convai-desktop-pet.
- 3-node brain over HTTP (Ollama client/server, token-gated LAN): Ollama architecture docs.

Links live in the commit message / PR description for this change.
