"""'Learn this' — buddy looks it up and remembers it.

Flow (human analogy: you tell an employee "go find out about X and remember it"):
  1. If you gave the fact directly ("remember that my server is 192.168.1.42") -> store it.
  2. Otherwise treat it as a research task -> web search -> distil -> store as a semantic memory.
  3. Optionally draft a skill stub if the lesson looks like a repeatable action.

Kept deliberately small and dependency-free: reuses the existing web skill and the
local LLM (if up) to distil. No new heavy deps.
"""
import re

from buddy.memory import memory as mem

_LEARN_RE = re.compile(
    r"^\s*(?:learn|remember|note|memorize)\s+(?:that\s+)?(.*)", re.I)

# "remember that X" where X is a direct fact vs "learn about Y" which needs a lookup
_LOOKUP_HINTS = ("about ", "how to ", "who ", "what is ", "what are ", "look up ", "find out ")


def looks_like_learn(text):
    return bool(_LEARN_RE.match(text or ""))


def _distil(topic, raw, cfg):
    """Squeeze a web result down to a couple of durable sentences, via the local LLM if available."""
    try:
        from buddy import llm
        if cfg.get("llm_enabled") and llm.is_up(cfg):
            prompt = (f"In 1-2 short sentences, state the durable facts to remember about "
                      f"'{topic}'. Be concrete. Source text:\n{raw[:1500]}")
            msg = llm.chat([{"role": "user", "content": prompt}], cfg)
            out = (msg.get("content") or "").strip()
            if out:
                return out
    except Exception:
        pass
    return raw[:400].strip()


def learn(text, ctx):
    """Entry point wired as a skill. `ctx` carries cfg (and anything else)."""
    cfg = ctx.get("cfg", {})
    m = _LEARN_RE.match(text or "")
    body = (m.group(1) if m else text or "").strip()
    if not body:
        return "Learn what? Try: 'remember that my server ip is 192.168.1.42'."

    needs_lookup = any(h in body.lower() for h in _LOOKUP_HINTS)

    if not needs_lookup:
        # direct fact -> store verbatim
        mem.remember(body, kind="semantic", meta={"source": "user"}, cfg=cfg)
        return f"Got it, I'll remember: {body}"

    # research task -> web -> distil -> store
    topic = re.sub(r"^(learn|find out|look up)\s+(about\s+)?", "", body, flags=re.I).strip()
    try:
        from buddy.skills.web import search as web_search
        raw = web_search(topic, ctx)
    except Exception as e:
        return f"Couldn't look that up ({e}). Tell me the fact directly and I'll remember it."
    fact = _distil(topic, raw, cfg)
    mem.remember(fact, kind="semantic", meta={"source": "web", "topic": topic}, cfg=cfg)
    return f"Looked it up and remembered: {fact}"


# skill contract so the loader picks it up
SKILLS = [{
    "name": "learn",
    "phrases": ["remember that", "learn about", "note that", "memorize",
                "look up and remember", "find out about"],
    "run": learn,
}]
