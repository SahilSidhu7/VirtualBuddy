"""The model, bought from NVIDIA's free API instead of run on the card.

build.nvidia.com serves an OpenAI-compatible endpoint with frontier-size models
for nothing but an API key. On the same tool-calling probe a 550B model
answered in 1.1s, where the best thing an 8GB card could hold scored 70-90% on
the eval and the default it picked scored 20%. The card was the ceiling; this
removes it.

Two things about the free tier shape everything below:

* **Which models answer changes.** On the day this was written, some listed
  models 404ed for the account ("Function ... Not found for account") and
  others queued for over a minute before answering. So every tier is a chain,
  not a name: a 404 drops that model for the rest of the session, a 429 or a
  timeout moves on to the next one, and the first that answers wins.
* **It is rate limited**, roughly 40 requests a minute. One backoff, then the
  next model, rather than hammering the same one.

No SDK: the rest of the app speaks HTTP through `urllib`, and one more
dependency in a frozen build is one more thing to break.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from vb import config

BASE_URL = "https://integrate.api.nvidia.com/v1"

# Measured 2026-10-22 against a free key, best first. All three returned a
# correct native tool call; the first two in about a second.
WORK_MODELS = ["nvidia/nemotron-3-ultra-550b-a55b", "openai/gpt-oss-20b",
               "nvidia/nemotron-3.5-lightning-30b-a3b"]
FAST_MODELS = ["nvidia/nemotron-3.5-lightning-30b-a3b", "openai/gpt-oss-20b"]
VISION_MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"
EMBED_MODEL = "nvidia/nemotron-3.5-embed-1b"

TIMEOUT = 120
BACKOFF = 4.0

_dead: set[str] = set()          # 404ed for this account; skip until restart
_lock = threading.Lock()
_last_error: str | None = None
_state: dict = {}


# --------------------------------------------------------------------- key
def _read_env_file(path: Path) -> str:
    try:
        for line in path.read_text("utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "NVIDIA_API_KEY":
                return value.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def api_key() -> str:
    """The key, from wherever it was put. First found wins.

    The environment, then `.env` in the data folder, then config.json, then a
    key baked into a test build. The baked one is generated at build time from
    a CI secret and is gitignored, so it never reaches the public installer.
    """
    key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if key:
        return key
    key = _read_env_file(config.HOME / ".env")
    if key:
        return key
    key = (config.get("nvidia_api_key") or "").strip()
    if key:
        return key
    try:
        from vb import _bundled_key            # type: ignore[attr-defined]
        return getattr(_bundled_key, "KEY", "")
    except ImportError:
        return ""


def base_url() -> str:
    return (config.get("provider_base_url") or BASE_URL).rstrip("/")


def chain(tier: str) -> list[str]:
    """The models to try for a tier, configured ones first, dead ones gone."""
    if tier == "fast":
        names = config.get("fast_models") or FAST_MODELS
    else:
        names = config.get("work_models") or WORK_MODELS
    if isinstance(names, str):
        names = [names]
    return [n for n in names if n not in _dead] or list(names)


def last_error() -> str | None:
    return _last_error


# -------------------------------------------------------------------- HTTP
class ProviderError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _request(path: str, payload: dict | None, timeout: float) -> dict:
    key = api_key()
    if not key:
        raise ProviderError(401, "No NVIDIA API key. Put NVIDIA_API_KEY in "
                                 f"{config.HOME / '.env'}.")
    req = urllib.request.Request(
        base_url() + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        raise ProviderError(exc.code, f"NVIDIA API said {exc.code}: {body}")
    except Exception as exc:                       # timeouts, DNS, resets
        raise ProviderError(0, f"{type(exc).__name__}: {exc}")


def _post_chain(models: list[str], build, timeout: float) -> tuple[dict, str]:
    """POST to /chat/completions, walking the chain until one answers."""
    global _last_error
    last = None
    for model in models:
        for attempt in (0, 1):
            try:
                out = _request("/chat/completions", build(model), timeout)
                _last_error = None
                return out, model
            except ProviderError as exc:
                last = exc
                if exc.code == 404:
                    with _lock:
                        _dead.add(model)
                    break
                if exc.code in (401, 403):
                    _last_error = str(exc)
                    raise
                if exc.code == 429 and attempt == 0:
                    time.sleep(BACKOFF)
                    continue
                break                              # 5xx / timeout: next model
    _last_error = str(last) if last else "No model answered."
    raise last or ProviderError(0, _last_error)


# -------------------------------------------------------------------- chat
def to_openai(messages: list[dict]) -> list[dict]:
    """The loop's transcript, in the shape an OpenAI endpoint accepts.

    The loop was written against Ollama, which takes tool arguments as a dict
    and tool results with no id. OpenAI wants arguments as a JSON string, an
    `id` on every call and a matching `tool_call_id` on its result, and it
    rejects a request that has a call without one. Ids are invented here when
    the loop did not keep them, and paired to results in order.
    """
    out, pending = [], []
    for i, m in enumerate(messages):
        m = dict(m)
        if m.get("role") == "assistant" and m.get("tool_calls"):
            calls = []
            for j, c in enumerate(m["tool_calls"]):
                fn = dict(c.get("function") or {})
                args = fn.get("arguments", {})
                if not isinstance(args, str):
                    args = json.dumps(args or {})
                cid = c.get("id") or f"call_{i}_{j}"
                pending.append(cid)
                calls.append({"id": cid, "type": "function",
                              "function": {"name": fn.get("name", ""),
                                           "arguments": args}})
            m["tool_calls"] = calls
            m["content"] = m.get("content") or ""
        elif m.get("role") == "tool":
            cid = m.get("tool_call_id")
            if cid and cid in pending:
                pending.remove(cid)
            elif not cid:
                cid = pending.pop(0) if pending else f"call_{i}"
            m["tool_call_id"] = cid
            m.pop("tool_name", None)
            m["content"] = str(m.get("content") or "")
        out.append(m)
    return out


def chat(messages: list[dict], tools: list[dict] | None = None, *,
         tier: str = "work", temperature: float = 0.2, max_tokens: int = 1200,
         timeout: float = TIMEOUT, json_mode: bool = False,
         think: bool | None = None) -> tuple[dict, str]:
    """One completion. Returns (assistant message, model that answered).

    Raises ProviderError when every model in the chain failed. `think` None
    means the default: reasoning on for the work tier, off for the fast one.
    """
    if think is None:
        think = tier != "fast" and bool(config.get("think", True))
    msgs = to_openai(messages)

    def build(model: str) -> dict:
        payload = {"model": model, "messages": msgs, "temperature": temperature,
                   "max_tokens": max_tokens, "stream": False}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        # Nemotron models reason before answering unless told not to, and with
        # a short budget the reasoning takes all of it: `content` comes back
        # None and the thoughts arrive where the answer should be. Measured on
        # the fast model, a YES/NO went from 2.0s and no answer to 0.5s and
        # "YES". The loop keeps thinking on the work tier — choosing the next
        # tool is what it is there for. One-shot writing turns it off.
        if model.startswith("nvidia/") and not think:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        return payload

    out, model = _post_chain(chain(tier), build, timeout)
    choice = (out.get("choices") or [{}])[0]
    return choice.get("message") or {}, model


# ------------------------------------------------------------------ others
def embed(texts: list[str], input_type: str = "passage") -> list[list[float]] | None:
    """Vectors, or None. `input_type` is "query" for a search, "passage" for
    what is being indexed — NVIDIA's retrieval models are asymmetric and
    reject a request without it."""
    global _last_error
    if not texts:
        return None
    payload = {"model": config.get("embed_model") or EMBED_MODEL,
               "input": texts, "input_type": input_type,
               "encoding_format": "float", "truncate": "END"}
    try:
        out = _request("/embeddings", payload, TIMEOUT)
    except ProviderError as exc:
        _last_error = str(exc)
        return None
    data = sorted(out.get("data") or [], key=lambda d: d.get("index", 0))
    vecs = [d.get("embedding") for d in data]
    return vecs if len(vecs) == len(texts) and all(vecs) else None


def vision(prompt: str, image_b64: str, mime: str = "image/png",
           max_tokens: int = 700) -> str | None:
    global _last_error
    msg = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url",
         "image_url": {"url": f"data:{mime};base64,{image_b64}"}}]}]
    model = config.get("vision_model") or VISION_MODEL
    try:
        out = _request("/chat/completions",
                       {"model": model, "messages": msg, "max_tokens": max_tokens,
                        "temperature": 0.2}, TIMEOUT)
    except ProviderError as exc:
        _last_error = str(exc)
        return None
    return ((out.get("choices") or [{}])[0].get("message") or {}).get("content")


def models() -> list[str]:
    """Every model this key can see. Cached; an empty list when offline."""
    if "models" not in _state:
        try:
            _state["models"] = sorted(m["id"] for m in
                                      _request("/models", None, 15).get("data", []))
        except ProviderError:
            return []
    return _state["models"]


def ping() -> tuple[bool, str]:
    """Is there a key, and does the API take it? (ok, human message)."""
    if not api_key():
        return False, ("No NVIDIA API key yet. Get a free one at "
                       "build.nvidia.com and put NVIDIA_API_KEY=... in "
                       f"{config.HOME / '.env'}.")
    try:
        _request("/models", None, 15)
        return True, f"Ready ({chain('work')[0]})."
    except ProviderError as exc:
        if exc.code in (401, 403):
            return False, "The NVIDIA API key was rejected."
        return False, f"Cannot reach the NVIDIA API. {exc}"
