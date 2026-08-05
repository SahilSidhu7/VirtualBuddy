# How the brain is trained (and how users get it)

## What we actually "fine-tuned"
We did **not** fine-tune a large language model. That's expensive and needs GPUs.
Instead we trained a tiny, fast **intent classifier** that maps a command to the
right skill — adapted (“fine-tuned”) to *our* skills and the way people phrase them.

Two pieces work together:

1. **Embeddings** (the understanding). Text → a vector, via your local Ollama model
   `nomic-embed-text` (no torch, no cloud). Similar meanings land near each other,
   so "secure my machine" sits close to "lock the screen".
2. **Classifier** (the decision). A small logistic-regression head on top of those
   vectors, trained to pick the correct skill. This file is `models/intent_clf.joblib`
   (a few KB).

The LLM itself (e.g. `qwen2.5`) is used **as-is** from Ollama — we shape its behaviour
with a system prompt + tool definitions (function calling), not by retraining it.

## How it's trained — the 2-bot loop
All local, no Claude tokens (`tools/`):

- **Builder** (`builder.py`) reads every skill's example phrases and *augments* them
  with templates ("please …", "can you … now") → a few thousand training examples.
  It also re-learns from past mistakes (`data/failures.jsonl`).
- **Critic** (`critic.py`) tests the model on **held-out** phrasings it never trained
  on (different templates) — a fair exam. Every miss is logged.
- **Loop** (`loop.py`) runs builder → critic → feed misses back → retrain, until
  accuracy hits target. Current default skills: **100%** on 2,088 unseen phrasings.

```
python -m tools.loop 0.95 6
```

It keeps improving from *you* too: correct a wrong call with `!fix <skill>`, then
`!train`. That correction becomes training data.

## How users get the model
Three honest layers, so it always works:

1. **Out of the box — no model file needed.** If there's no trained classifier, the
   brain routes by raw embedding similarity (cosine). Good enough to be useful
   immediately. This is why installers don't need to ship weights.
2. **Trained on-device (recommended).** From source, `python install.py` trains it.
   In the packaged app, use the control-panel button or `!train`. It runs on the
   user's own Ollama, so **no model weights are ever downloaded or shipped** — and it
   learns the user's *own* installed community skills, which a shared model couldn't.
3. **Shared model (optional).** `models/intent_clf.joblib` can be copied between your
   machines *if they use the same `embed_model`* (the vector dimensions must match).
   It's git-ignored by default because on-device training is better per user.

## Why this design
- **Cheap + fast:** trains in seconds, runs in milliseconds, tiny file.
- **Private + offline:** embeddings and training are local.
- **Personalised:** each user's model fits their exact skill set.
- **Robust:** deterministic slots + cosine fallback mean it degrades gracefully.
