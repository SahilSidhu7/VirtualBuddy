"""Tools that live in someone else's process.

MCP is how the rest of the world ships agent tools now, and not speaking it
means every capability has to be written here by hand. A server is a program
that talks JSON-RPC over its own stdin and stdout; it advertises a list of
tools with JSON schemas, and those schemas are the same shape `vb.tools`
already uses. So an MCP tool becomes a `Tool` with no translation layer worth
the name.

Servers are configured in `config.json`:

    "mcp_servers": {
      "files": {"command": ["npx", "-y", "@modelcontextprotocol/server-filesystem",
                            "C:/Projects"]}
    }

Servers start the first time the tool list is built, not at boot — but be clear
that building the tool list *is* starting them, since a server has to be asked
what it offers. With none configured, which is the default, nothing launches at
all.

A server that fails is marked dead and not retried, and every read is bounded
by a queue fed from a reader thread rather than a bare `readline()`. That
matters more than it sounds: the usual way an stdio server fails is to sit
waiting on stdin having never written a byte, and a blocking read against that
never returns. One bad line in a config file would otherwise freeze the first
request the user makes, for good.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field

from vb import config

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
START_TIMEOUT = 25
CALL_TIMEOUT = 60
PROTOCOL = "2024-11-05"


def _resolve(program: str) -> str:
    """The full path to an executable, for `Popen` without a shell.

    Windows-specific and not optional. Almost every published MCP server is
    launched with `npx`, and on Windows `npx` is `npx.cmd` — a batch file.
    `CreateProcess` does not consult PATHEXT, so `Popen(["npx", ...])` fails
    with `[WinError 2] The system cannot find the file specified` even though
    the command works perfectly in a terminal. Every Node-based server was
    unreachable because of it. `shutil.which` does apply PATHEXT, so resolving
    the name first is the whole fix — and `shell=True` is not used, because
    these arguments include user-supplied paths.
    """
    return shutil.which(program) or program


@dataclass
class Server:
    name: str
    command: list[str]
    env: dict = field(default_factory=dict)
    proc: subprocess.Popen | None = None
    tools: list[dict] = field(default_factory=list)
    error: str = ""
    _next_id: int = 1
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _lines: "queue.Queue" = field(default_factory=queue.Queue)
    _reader: threading.Thread | None = None
    _dead: bool = False           # start failed once; do not keep retrying

    # -- plumbing --------------------------------------------------------
    def _send(self, method: str, params: dict | None = None,
              notify: bool = False, timeout: float = CALL_TIMEOUT) -> dict | None:
        if not self.proc or not self.proc.stdin:
            return None
        message = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            message["id"] = self._next_id
            self._next_id += 1
        try:
            self.proc.stdin.write(json.dumps(message) + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError) as exc:
            self.error = f"could not write to {self.name}: {exc}"
            return None
        return None if notify else self._read(message["id"], timeout)

    def _pump(self) -> None:
        """Read the server's output forever, onto a queue.

        A dedicated thread, because `readline()` blocks and cannot be given a
        timeout. Checking a deadline around a blocking read only works if the
        read returns, and the most common way an stdio server fails is by
        waiting silently on stdin — wrong arguments, missing config — at which
        point it never writes a byte and the caller waits for good.
        """
        stream = self.proc.stdout if self.proc else None
        if not stream:
            return
        try:
            for line in stream:
                self._lines.put(line)
        except (OSError, ValueError):
            pass
        finally:
            self._lines.put(None)             # end of stream

    def _read(self, want_id: int, timeout: float = CALL_TIMEOUT) -> dict | None:
        """Wait for the reply with this id, and give up when the clock runs out.

        Servers interleave notifications (logging, progress) with replies, so
        anything without our id is skipped rather than treated as the answer.
        """
        deadline = time.time() + timeout
        while True:
            left = deadline - time.time()
            if left <= 0:
                self.error = f"{self.name} did not reply in {timeout}s"
                return None
            try:
                line = self._lines.get(timeout=left)
            except queue.Empty:
                self.error = f"{self.name} did not reply in {timeout}s"
                return None
            if line is None:
                self.error = f"{self.name} closed its output"
                return None
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue                      # servers print to stdout too
            if message.get("id") == want_id:
                if "error" in message:
                    self.error = str(message["error"])[:200]
                    return None
                return message.get("result") or {}

    # -- lifecycle -------------------------------------------------------
    def start(self) -> bool:
        if self.proc and self.proc.poll() is None:
            return True
        if self._dead:
            # It failed once. Retrying on every tool listing turns one bad
            # config line into a stall on every request the user makes.
            return False
        try:
            self.proc = subprocess.Popen(
                [_resolve(self.command[0]), *self.command[1:]],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, bufsize=1,
                encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
                env={**os.environ, **{k: str(v) for k, v in self.env.items()}})
        except (OSError, ValueError) as exc:
            self.error = f"{self.name} would not start: {exc}"
            self._dead = True
            return False

        self._lines = queue.Queue()
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

        hello = self._send("initialize", {
            "protocolVersion": PROTOCOL,
            "capabilities": {},
            "clientInfo": {"name": "VirtualBuddy", "version": "0.8"},
        }, timeout=START_TIMEOUT)
        if hello is None:
            self.stop()
            self._dead = True
            return False
        self._send("notifications/initialized", notify=True)

        listed = self._send("tools/list", timeout=START_TIMEOUT)
        if listed is None:
            self.stop()
            self._dead = True
            return False
        self.tools = [t for t in listed.get("tools", []) if t.get("name")]
        self.error = ""
        return True

    def stop(self) -> None:
        if not self.proc:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except (OSError, subprocess.SubprocessError):
            try:
                self.proc.kill()
            except OSError:
                pass
        self.proc = None

    def call(self, tool: str, args: dict) -> tuple[bool, str]:
        with self._lock:
            if not self.start():
                return False, self.error or f"{self.name} is not available."
            result = self._send("tools/call", {"name": tool, "arguments": args})
        if result is None:
            return False, self.error or f"{self.name} did not answer."
        return True, _flatten(result)


def _flatten(result: dict) -> str:
    """MCP returns a list of content blocks. The loop wants text."""
    parts = []
    for block in result.get("content") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif block.get("type") == "resource":
            resource = block.get("resource") or {}
            parts.append(resource.get("text") or str(resource.get("uri", "")))
        else:
            parts.append(f"[{block.get('type', 'content')}]")
    text = "\n".join(p for p in parts if p).strip()
    if result.get("isError"):
        return f"The tool reported an error: {text or 'no detail given.'}"
    return text or "(the tool returned nothing)"


# ------------------------------------------------------------------ registry
_servers: dict[str, Server] = {}


def configured() -> dict[str, Server]:
    """Servers named in the config. Built lazily, never started here."""
    raw = config.get("mcp_servers") or {}
    if not isinstance(raw, dict):
        return {}
    for name, spec in raw.items():
        if name in _servers or not isinstance(spec, dict):
            continue
        command = spec.get("command")
        if isinstance(command, str):
            command = command.split()
        if not command:
            continue
        # `args` is a separate key in every MCP config in the wild — Claude
        # Desktop, Cursor and the servers' own READMEs all publish
        # {"command": "npx", "args": [...]}. It was being dropped here, so a
        # config copied from a server's documentation launched a bare `npx`,
        # which prints its help to stderr and then waits on stdin forever. The
        # symptom was "did not reply in 25s" — a hang, not a bad-config error,
        # which is why it read as a protocol problem.
        args = spec.get("args") or []
        if isinstance(args, str):
            args = args.split()
        _servers[name] = Server(name=name,
                                command=[*command, *(str(a) for a in args)],
                                env=dict(spec.get("env") or {}))
    return _servers


def discover() -> list[tuple[Server, dict]]:
    """Every tool every configured server offers. Starts them to ask."""
    found = []
    for server in configured().values():
        if not server.start():
            continue
        for schema in server.tools:
            found.append((server, schema))
    return found


def shutdown() -> None:
    for server in _servers.values():
        server.stop()


def status() -> str:
    servers = configured()
    if not servers:
        return ("No MCP servers configured. Add them under \"mcp_servers\" in "
                f"{config.CONFIG_PATH}.")
    lines = []
    for server in servers.values():
        if server.proc and server.proc.poll() is None:
            lines.append(f"  {server.name}: {len(server.tools)} tools, running")
        elif server.error:
            lines.append(f"  {server.name}: {server.error}")
        else:
            lines.append(f"  {server.name}: configured, not started")
    return "\n".join(lines)
