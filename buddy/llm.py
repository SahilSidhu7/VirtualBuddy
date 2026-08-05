"""Buddy's local brain via Ollama. Answers, reasons, and calls skills - offline, no tokens.

Uses only built-in urllib. If Ollama isn't running, is_up() returns False and
the agent falls back to web / Claude.
"""
import json, urllib.request

SYSTEM = ("You are Buddy, a concise PC assistant. If the user asks you to DO something "
          "on the PC (open apps, files, screenshots, lock, system status, web search), "
          "call the matching tool. For general questions, just answer in 1-3 short sentences.")

def _post(cfg, path, payload, timeout=120):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(cfg["ollama_url"] + path, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def is_up(cfg):
    try:
        urllib.request.urlopen(cfg["ollama_url"] + "/api/tags", timeout=2).read()
        return True
    except Exception:
        return False

def unload(cfg):
    """Free the model from RAM (power-saving)."""
    try:
        _post(cfg, "/api/generate", {"model": cfg["llm_model"], "keep_alive": 0}, timeout=10)
        return True
    except Exception:
        return False

def chat(messages, cfg, tools=None):
    """Raw chat. Returns the assistant message dict (may hold tool_calls)."""
    payload = {"model": cfg["llm_model"], "messages": messages, "stream": False,
               "keep_alive": "10m", "options": {"temperature": 0.3, "num_predict": 256}}
    if tools:
        payload["tools"] = tools
    return _post(cfg, "/api/chat", payload).get("message", {})

def ask(text, cfg):
    """Plain answer, no tools."""
    msg = chat([{"role": "system", "content": SYSTEM},
                {"role": "user", "content": text}], cfg)
    return msg.get("content", "").strip()
