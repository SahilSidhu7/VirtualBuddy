# How the brain is trained (and how users get it)

## What we actually "fine-tuned"
We did **not** fine-tune a large language model. That's expensive and needs GPUs.
Instead we trained a tiny, fast **intent classifier** that maps a command to the
right skill — adapted (“fine-tuned”) to *our* skills and the way people phrase them.

How it works:

- **Classifier.** A TF-IDF vectorizer (word 1–2 grams + character 3–5 grams) feeding a
  logistic-regression model. It learns, from example phrasings of each skill, which
  skill a command means. Saved as `~/.virtualbuddy/models/intent_clf.joblib` (a few KB).
- **Runs in-process, instantly.** Routing takes well under a millisecond and needs
  **no Ollama and no internet** — so every command is snappy.
- **The LLM is the safety net.** When the classifier isn't confident (a paraphrase with
  no shared words, e.g. "secure my machine"), the command falls through to the local
  LLM, which answers or calls the right skill itself.

The LLM (e.g. `qwen2.5`) is used **as-is** from Ollama — shaped by a system prompt +
tool definitions (function calling), not retrained. Ollama is only needed for the
LLM brain, not for routing.

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
   In the packaged app, first launch offers to train, or use `!train`. Training is
   pure scikit-learn — **no Ollama, no internet, seconds** — and it learns the user's
   *own* installed community skills, which a shared model couldn't.
3. **Shared model (optional).** `~/.virtualbuddy/models/intent_clf.joblib` can be copied
   between machines. It's git-ignored by default because on-device training is trivial.

## Why this design
- **Cheap + fast:** trains in seconds, runs in milliseconds, tiny file.
- **Private + offline:** embeddings and training are local.
- **Personalised:** each user's model fits their exact skill set.
- **Robust:** deterministic slots + cosine fallback mean it degrades gracefully.
