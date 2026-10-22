"""Where thinking is bought from, and at what price.

VirtualBuddy runs an agent loop, and a loop asks the model many times per task
instead of once. So the loop buys its thinking in tiers, and the cheap tiers
do most of the work. All of them come from NVIDIA's free API (`vb.provider`);
the price that matters now is the rate limit, not the graphics card.

    fast   a small, quick hosted model. Classification, extraction, filling a
           learned tool's arguments, the critic's first pass.
    work   the biggest hosted model that answers. Drives the loop.
    hard   only when `work` has already failed twice. Claude Code's CLI when
           the user has opted in, otherwise `work` again.

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

from vb import config, llm, provider

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

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
def fast_model() -> str:
    return provider.chain("fast")[0]


def work_model() -> str:
    return provider.chain("work")[0]


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


# ------------------------------------------------------------------- the API
def _api_chat(messages: list[dict], tools: list[dict] | None, tier: str,
              timeout: int, temperature: float, max_tokens: int) -> Reply:
    try:
        msg, model = provider.chat(messages, tools, tier=tier, timeout=timeout,
                                   temperature=temperature, max_tokens=max_tokens)
    except provider.ProviderError as exc:
        return Reply(error=str(exc), backend="nvidia", model=work_model())
    calls = []
    for raw in msg.get("tool_calls") or []:
        fn = raw.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                args = {}
        calls.append(ToolCall(name=str(fn.get("name", "")),
                              args=dict(args or {}), id=str(raw.get("id", ""))))
    content = llm.strip_thinking(msg.get("content") or "")
    if not content and not calls:
        content = llm.strip_thinking(msg.get("reasoning_content")
                                     or msg.get("reasoning") or "")
    if not calls:
        # Some models still describe the call in prose instead of emitting one.
        calls = parse_text_tool_calls(content)
        if calls:
            content = strip_json_blocks(content)
    return Reply(content=content, tool_calls=calls[:1], backend="nvidia",
                 model=model)


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
        # reason a task dies when the API is there.
    return _api_chat(messages, tools, "fast" if tier == "fast" else "work",
                     timeout, temperature, max_tokens)


def ask_text(prompt: str, system: str = "", *, tier: str = "fast",
             timeout: int = 60, max_tokens: int = 400) -> str | None:
    """A single question with no tools. Used by the critic and by summarising."""
    messages = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
    reply = chat(messages, tier=tier, timeout=timeout, max_tokens=max_tokens)
    return reply.content or None if reply else None
