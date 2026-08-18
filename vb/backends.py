"""Where thinking is bought from, and at what price.

VirtualBuddy runs an agent loop, and a loop asks the model many times per task
instead of once. That changes the economics: a hosted frontier model billed per
token is fine for one question and ruinous for forty. So the loop buys its
thinking in tiers, and the cheap tiers do most of the work.

    fast   a small local model. Classification, extraction, the critic's first
           pass. Milliseconds of GPU time, no money.
    work   the best local model this card can hold. Drives the loop.
    hard   only when `work` has already failed twice. Claude Code's CLI when
           the user has it — they already pay for that subscription, so it
           costs nothing extra per call — otherwise `work` again.

Every backend answers the same shape, `Reply`, whether or not it natively
speaks tool calls. Backends that do not (the CLI) get a JSON protocol bolted on
and parsed out, so the loop never has to care which one it is talking to.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from vb import config, llm

# Context window asked of Ollama, which otherwise defaults to 4096 and silently
# drops the oldest messages — the request and the tool output the answer is
# supposed to come from.
#
# 8192 rather than more, and that is measured rather than guessed. On the same
# ten tasks an 8B agent model scored 90% at both 8192 and 16384, so the extra
# room bought it nothing; a 3B fine-tune trained at sequence length 3072 fell
# from 60% to 40% at 16384 and started repeating itself. A context far past
# what a model was trained on is not free, and the ladder here can select
# models down to 1.7B. Raise it in config for a big model on a big card.
NUM_CTX = int(config.get("num_ctx", 8192) or 8192)
# Suppresses the degenerate repetition that shows up in small fine-tuned
# models — the same token until the step times out. Cheap here, expensive to
# fix in training.
REPEAT_PENALTY = float(config.get("repeat_penalty", 1.05) or 1.05)

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Small enough to be near-free to call, capable enough to answer a yes/no about
# a paragraph. Tried in order; the first one installed wins.
FAST_MODELS = ["qwen3:1.7b", "llama3.2:3b", "qwen3:4b"]


@dataclass
class ToolCall:
    name: str
    args: dict
    id: str = ""


@dataclass
class Reply:
    """One model turn. `content` and `tool_calls` can both be present."""
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    error: str | None = None
    backend: str = ""
    model: str = ""

    def __bool__(self) -> bool:
        return self.error is None


# --------------------------------------------------------------- tier choice
def _model_bytes(name: str) -> int:
    """On-disk size of an installed model, which is close enough to what it
    will occupy in VRAM once loaded."""
    for m in _catalogue():
        if m.get("name") == name or m.get("model") == name:
            return int(m.get("size") or 0)
    return 0


def _catalogue() -> list[dict]:
    if "catalogue" not in llm._state:
        try:
            llm._state["catalogue"] = llm._get("/api/tags").get("models", [])
        except Exception:
            llm._state["catalogue"] = []
    return llm._state["catalogue"]


def fast_model() -> str:
    """The small model the cheap tier uses — but only if the card can hold it
    *at the same time* as the work model.

    Two models that do not co-reside are worse than one. Ollama evicts the
    resident model to make room for the other, so every alternation between
    tiers pays a full cold load: measured at 9.7s per swap on an RTX 4060 with
    hermes-agent (6.6GB) and qwen3:1.7b (2.2GB) on an 8.2GB card. Worse, when
    the eviction does not free enough, `cudaMalloc` fails and Ollama reports
    `llama-server startup failed` — the loop then dies on a memory limit that
    looks like a broken install.

    So when both will not fit, the fast tier is the work model. It is already
    loaded, which makes it *faster* in wall-clock than the small one.
    """
    work = work_model()
    budget = llm.vram_mb() * 1024 * 1024
    for name in FAST_MODELS:
        if not llm.installed(name):
            continue
        if not budget:
            return name                       # no GPU: everything is on the CPU
        # 1.25x for the KV cache and compute buffers each model brings along.
        if (_model_bytes(name) + _model_bytes(work)) * 1.25 <= budget:
            return name
        break
    return work


def work_model() -> str:
    return config.get("llm_model") or llm.recommended_model()


_cli_refused = False


def claude_code_path() -> str | None:
    """The Claude Code CLI, if it is present, permitted, and will answer.

    Two corrections to what this tier was assumed to be. It is **not free**:
    a one-word probe reported `total_cost_usd` of 0.22, so every escalation is
    billed per token like any API. And it refuses outright when driven
    programmatically from inside another session, which is not a failure worth
    retrying — once refused, it is out for the rest of the run.
    """
    # The fallback here said True while `config.DEFAULTS` said False, so the
    # tier was on for anyone whose config predated the key — the opposite of
    # what the default was changed to, and it bills per token.
    if _cli_refused or not config.get("use_claude_code", False):
        return None
    return shutil.which("claude")


def describe_tiers() -> dict:
    hard = claude_code_path()
    return {
        "fast": fast_model(),
        "work": work_model(),
        "hard": "claude-code" if hard else work_model(),
        "claude_code": bool(hard),
    }


# ------------------------------------------------------------------- Ollama
def _ollama_chat(messages: list[dict], tools: list[dict] | None, model: str,
                 timeout: int, temperature: float, max_tokens: int) -> Reply:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "keep_alive": llm.KEEP_ALIVE,
        # Reasoning models return their chain of thought in a separate
        # `thinking` field, and with a tight `num_predict` the whole budget
        # goes there and `content` comes back empty — a model that looks mute.
        # Ignored by models without the capability, so it is safe to always
        # send. Set `think` true in config for a model whose tool choices
        # measurably improve with it.
        "think": bool(config.get("think", False)),
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            # Ollama's default context is 4096 tokens, and nothing here was
            # setting it. An agent turn is a system prompt, a tool menu, and
            # the whole transcript of everything the tools returned — a single
            # file listing clears 4096 on its own. Past that Ollama drops the
            # *oldest* messages, which are the request and the tool output the
            # answer is supposed to come from, so the model answers a question
            # it can no longer see. That looks exactly like a model being bad
            # and is a setting being wrong.
            "num_ctx": NUM_CTX,
            # Degenerate repetition — the same token emitted until the step
            # times out — is cheap to suppress here and expensive to fix in
            # training. The agent model this was measured against sets it too.
            "repeat_penalty": REPEAT_PENALTY,
        },
    }
    if tools:
        payload["tools"] = tools
    out = llm._post("/api/chat", payload, timeout)
    if not out:
        return Reply(error=llm.last_error() or "Ollama did not answer.",
                     backend="ollama", model=model)
    msg = out.get("message") or {}
    calls = []
    for raw in msg.get("tool_calls") or []:
        fn = raw.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        calls.append(ToolCall(name=str(fn.get("name", "")),
                              args=dict(args or {}), id=str(raw.get("id", ""))))
    content = llm.strip_thinking(msg.get("content") or "")
    if not content and not calls:
        content = llm.strip_thinking(msg.get("thinking") or "")
    if not calls:
        # Small models often describe the call in prose instead of emitting one.
        calls = parse_text_tool_calls(content)
        if calls:
            content = strip_json_blocks(content)
    return Reply(content=content, tool_calls=calls, backend="ollama", model=model)


# -------------------------------------------------------------- Claude Code
CLI_PROTOCOL = """
You are driving a tool loop. To use a tool, reply with a JSON object and
nothing else:

{"tool": "<name>", "args": {...}}

To answer the user instead, reply with plain prose and no JSON.
"""


def _claude_code_chat(messages: list[dict], tools: list[dict] | None,
                      timeout: int) -> Reply:
    """Shell out to the Claude Code CLI.

    It has no chat endpoint and no tool schema, so the transcript is flattened
    into one prompt and tool calls come back as JSON we parse ourselves. Slower
    per turn than Ollama and it needs a network round trip, which is exactly
    why this is the tier of last resort.
    """
    exe = claude_code_path()
    if not exe:
        return Reply(error="Claude Code is not installed.", backend="claude-code")

    parts = []
    for m in messages:
        role = m.get("role", "user")
        text = m.get("content") or ""
        if role == "system":
            parts.append(text)
        elif role == "tool":
            parts.append(f"[tool result] {text}")
        else:
            parts.append(f"[{role}] {text}")
    if tools:
        listing = "\n".join(
            f"- {t['function']['name']}: {t['function'].get('description','')}"
            for t in tools)
        parts.append(f"Tools you may call:\n{listing}\n{CLI_PROTOCOL}")
    prompt = "\n\n".join(p for p in parts if p)

    # The prompt goes down stdin, not into argv. Windows caps a command line at
    # 32,767 characters, and a transcript with a dozen tool observations in it
    # passes that comfortably — the run then died with an OSError that looked
    # like the CLI was missing. `--allowedTools ""` matters just as much: this
    # is a full agent with its own tools, and left unconstrained it goes and
    # does the task itself instead of replying with the tool call we asked for,
    # which is a different program's work appearing as ours.
    try:
        done = subprocess.run(
            [exe, "-p", "--output-format", "json", "--allowedTools", ""],
            input=prompt, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return Reply(error=f"Claude Code timed out after {timeout}s.",
                     backend="claude-code")
    except OSError as exc:
        return Reply(error=f"Claude Code would not start: {exc}",
                     backend="claude-code")
    if done.returncode != 0:
        return Reply(error=(done.stderr or "Claude Code failed.").strip()[:300],
                     backend="claude-code")

    text = done.stdout.strip()
    try:                       # --output-format json wraps the reply
        payload = json.loads(text)
        # It answers with HTTP-200-shaped failure: exit code zero, `is_error`
        # true, `stop_reason` "refusal". Driven from inside another session it
        # refuses outright, so treating a zero exit as success meant the loop
        # burned a slow call and then silently fell back every single time.
        if payload.get("is_error") or payload.get("stop_reason") == "refusal":
            global _cli_refused
            _cli_refused = True
            return Reply(error="Claude Code refused the request.",
                         backend="claude-code")
        text = payload.get("result") or payload.get("content") or text
        if isinstance(text, list):     # content blocks
            text = "".join(b.get("text", "") for b in text if isinstance(b, dict))
    except (json.JSONDecodeError, AttributeError):
        pass
    calls = parse_text_tool_calls(text)
    return Reply(content=strip_json_blocks(text) if calls else text,
                 tool_calls=calls, backend="claude-code", model="claude-code")


# ------------------------------------------------------- text tool protocol
FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def _candidate_objects(text: str) -> list[str]:
    found = FENCE.findall(text)
    if found:
        return found
    # A bare object somewhere in the prose. Balance the braces rather than
    # regexing them, because tool arguments nest.
    out, depth, start = [], 0, -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                out.append(text[start:i + 1])
    return out


def parse_text_tool_calls(text: str) -> list[ToolCall]:
    """Pull `{"tool": ..., "args": {...}}` out of a prose reply.

    Backends without native tool calling need this, and so do small local
    models, which announce the call in text about a third of the time even when
    tools were passed properly.
    """
    calls = []
    for blob in _candidate_objects(text or ""):
        try:
            obj = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        name = obj.get("tool") or obj.get("name") or obj.get("function")
        if isinstance(name, dict):
            name = name.get("name")
        if not name:
            continue
        args = obj.get("args") or obj.get("arguments") or obj.get("parameters") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        if isinstance(args, dict):
            calls.append(ToolCall(name=str(name), args=args))
    return calls[:1]           # one call per turn: the loop observes between them


def strip_json_blocks(text: str) -> str:
    return FENCE.sub("", text or "").strip()


_checked_at = 0.0
SERVER_TTL = 30.0


def _server_up() -> bool:
    """Is Ollama answering? Cached briefly.

    The loop asks once per turn, and `llm.running()` is an HTTP round trip that
    also re-lists every installed model. Ollama does not stop and start again
    inside a single task, so half a minute of memory costs nothing and saves a
    request per step.
    """
    global _checked_at
    import time
    now = time.time()
    if now - _checked_at < SERVER_TTL and llm._state.get("models") is not None:
        return True
    up = llm.running()
    _checked_at = now if up else 0.0
    return up


# ------------------------------------------------------------------ the door
def chat(messages: list[dict], tools: list[dict] | None = None, *,
         tier: str = "work", timeout: int = 180, temperature: float = 0.2,
         max_tokens: int = 1200) -> Reply:
    """One model turn at the given tier."""
    if tier == "hard" and claude_code_path():
        reply = _claude_code_chat(messages, tools, timeout)
        if reply:
            return reply
        # Falling back rather than failing: a missing CLI must never be the
        # reason a task dies when there is a working local model.
    model = fast_model() if tier == "fast" else work_model()
    if not _server_up():
        return Reply(error=llm.status()["message"], backend="ollama", model=model)
    return _ollama_chat(messages, tools, model, timeout, temperature, max_tokens)


def ask_text(prompt: str, system: str = "", *, tier: str = "fast",
             timeout: int = 60, max_tokens: int = 400) -> str | None:
    """A single question with no tools. Used by the critic and by summarising."""
    messages = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
    reply = chat(messages, tier=tier, timeout=timeout, max_tokens=max_tokens)
    return reply.content or None if reply else None
