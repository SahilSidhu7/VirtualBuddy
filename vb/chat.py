"""Talking to the buddy from a phone.

Hermes' reach is the thing that makes it feel like an agent rather than an app:
it is wherever you already are. This is the same idea at the smallest honest
size — a long-poll loop against Telegram or Discord, handing each message to
the same `loop.run` the desktop panel uses, and sending the answer back.

Long polling, not webhooks, on purpose. A webhook needs a public address, a
certificate and a port forwarded through a home router; long polling needs an
outbound connection and works from behind anything. It is what a desktop app
can actually rely on.

**Approval over chat.** The panel can open a dialog and wait. A chat cannot, so
the rule here is explicit and conservative: anything needing approval is
declined, and the reply says what was skipped and why. A message asking "reply
yes to delete these files" is a phishing lesson waiting to happen, and the
person on the other end cannot see what is really about to run.

Tokens live in `config.json`, never in code. With none set, nothing starts.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from vb import config, loop, progress

POLL_TIMEOUT = 50           # seconds the server holds an empty long poll
MAX_REPLY = 3500            # both platforms cut messages around 4000
BUSY = "Working on that…"


@dataclass
class Message:
    chat_id: str
    text: str
    author: str = ""


class Adapter:
    """What a platform has to provide. Two methods and a name."""
    name = "chat"

    def poll(self) -> list[Message]:
        raise NotImplementedError

    def send(self, chat_id: str, text: str) -> None:
        raise NotImplementedError


def _get_json(url: str, timeout: float = POLL_TIMEOUT + 15) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None


def _post_json(url: str, payload: dict, timeout: float = 20) -> dict | None:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None


# ------------------------------------------------------------------ telegram
class Telegram(Adapter):
    name = "telegram"

    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}"
        self.offset = 0

    def poll(self) -> list[Message]:
        url = (f"{self.base}/getUpdates?timeout={POLL_TIMEOUT}"
               f"&offset={self.offset}&allowed_updates=%5B%22message%22%5D")
        data = _get_json(url)
        if not data or not data.get("ok"):
            return []
        out = []
        for update in data.get("result") or []:
            self.offset = max(self.offset, int(update.get("update_id", 0)) + 1)
            message = update.get("message") or {}
            text = (message.get("text") or "").strip()
            chat = ((message.get("chat") or {}).get("id"))
            if text and chat is not None:
                who = (message.get("from") or {}).get("username", "")
                out.append(Message(chat_id=str(chat), text=text, author=who))
        return out

    def send(self, chat_id: str, text: str) -> None:
        _post_json(f"{self.base}/sendMessage",
                   {"chat_id": chat_id, "text": text[:MAX_REPLY]})


# ------------------------------------------------------------------- discord
class Discord(Adapter):
    """Discord over the REST API, polling one channel.

    A proper bot uses the gateway websocket. That needs a dependency and a
    reconnect state machine, and for "message the buddy from my phone" polling
    a channel every few seconds is indistinguishable and about forty lines.
    """
    name = "discord"

    def __init__(self, token: str, channel: str):
        self.token = token
        self.channel = str(channel)
        self.after: str | None = None
        self.me: str | None = None

    def _request(self, path: str, payload: dict | None = None):
        url = f"https://discord.com/api/v10{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(url, data=data, headers={
            "Authorization": f"Bot {self.token}",
            "Content-Type": "application/json",
            "User-Agent": "VirtualBuddy (local, 0.8)",
        })
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                body = response.read()
                return json.loads(body) if body else {}
        except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
            return None

    def poll(self) -> list[Message]:
        if self.me is None:
            who = self._request("/users/@me") or {}
            self.me = str(who.get("id", ""))
        query = f"?limit=10" + (f"&after={self.after}" if self.after else "")
        data = self._request(f"/channels/{self.channel}/messages{query}")
        if not isinstance(data, list):
            return []
        out = []
        for row in reversed(data):
            message_id = str(row.get("id", ""))
            self.after = message_id or self.after
            author = row.get("author") or {}
            if str(author.get("id")) == self.me or author.get("bot"):
                continue            # never answer itself
            text = (row.get("content") or "").strip()
            if text:
                out.append(Message(chat_id=self.channel, text=text,
                                   author=author.get("username", "")))
        return out

    def send(self, chat_id: str, text: str) -> None:
        self._request(f"/channels/{chat_id}/messages",
                      {"content": text[:MAX_REPLY]})


# -------------------------------------------------------------------- bridge
@dataclass
class Bridge:
    adapter: Adapter
    allow: list[str] = field(default_factory=list)   # usernames, empty = anyone
    stop: threading.Event = field(default_factory=threading.Event)

    def _permitted(self, message: Message) -> bool:
        if not self.allow:
            return True
        return message.author.lower() in {a.lower() for a in self.allow}

    def handle(self, message: Message) -> None:
        if not self._permitted(message):
            self.adapter.send(message.chat_id,
                              "I don't take requests from this account.")
            return

        self.adapter.send(message.chat_id, BUSY)
        skipped: list[str] = []

        def declined(tool: str, _args: dict, reason: str) -> bool:
            # Nothing irreversible over chat. Recorded so the reply can say
            # what was left undone rather than quietly doing less than asked.
            skipped.append(f"{tool} ({reason})")
            return False

        try:
            with progress.listening(lambda _m: None):
                outcome = loop.run(message.text, approve=declined)
            answer = outcome.answer or "I could not finish that."
        except Exception as exc:
            answer = f"That went wrong: {type(exc).__name__}: {exc}"
        if skipped:
            answer += ("\n\nSkipped, because I won't do anything irreversible "
                       "over chat: " + "; ".join(skipped[:3]))
        self.adapter.send(message.chat_id, answer)

    def serve(self) -> None:
        """Poll until stopped. Blocking; run it on its own thread."""
        while not self.stop.is_set():
            try:
                messages = self.adapter.poll()
            except Exception:
                time.sleep(5)          # a flaky network is not a crash
                continue
            for message in messages:
                if self.stop.is_set():
                    return
                self.handle(message)
            if not messages:
                time.sleep(2)


def build() -> Bridge | None:
    """The bridge described by config, or None when none is configured."""
    allow = list(config.get("chat_allow") or [])
    token = config.get("telegram_token")
    if token:
        return Bridge(adapter=Telegram(str(token)), allow=allow)
    token, channel = config.get("discord_token"), config.get("discord_channel")
    if token and channel:
        return Bridge(adapter=Discord(str(token), str(channel)), allow=allow)
    return None


def status() -> str:
    bridge = build()
    if not bridge:
        return ("No chat frontend configured. Set telegram_token, or "
                f"discord_token and discord_channel, in {config.CONFIG_PATH}. "
                "chat_allow limits who may ask; empty means anyone who can "
                "reach the bot.")
    who = ", ".join(bridge.allow) if bridge.allow else "anyone in the chat"
    return f"{bridge.adapter.name} configured, answering {who}."


def serve_forever() -> int:
    bridge = build()
    if not bridge:
        print(status())
        return 1
    from vb.registry import load_all

    load_all()
    ready, why = loop.available()
    if not ready:
        print(f"Cannot start: {why}")
        return 1
    print(f"{status()}  Ctrl-C to stop.")
    try:
        bridge.serve()
    except KeyboardInterrupt:
        bridge.stop.set()
    return 0
