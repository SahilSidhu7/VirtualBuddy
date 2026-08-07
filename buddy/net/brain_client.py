"""Brain client — laptop/phone side. Talks to the server's brain over the LAN.

Drop-in shaped like the local Agent: `.handle(text)` returns a reply string, so the
UI/listener/character don't care whether the brain is local or remote. Falls back to
a clear error string if the server is unreachable (caller can then run locally).
"""
import json, urllib.request

from buddy import settings


class BrainClient:
    def __init__(self, cfg=None):
        self.cfg = cfg or settings.load()
        self.base = self.cfg.get("brain_host", "").rstrip("/")
        self.token = self.cfg.get("server_token", "changeme")

    def _post(self, path, obj, timeout=120):
        req = urllib.request.Request(
            self.base + path, data=json.dumps(obj).encode(),
            headers={"Content-Type": "application/json", "X-Token": self.token})
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read())

    def available(self):
        if not self.base:
            return False
        try:
            urllib.request.urlopen(self.base + "/health", timeout=3)
            return True
        except Exception:
            return False

    # ---- Agent-shaped surface ----
    def handle(self, text):
        try:
            return self._post("/handle", {"text": text}).get("reply", "")
        except Exception as e:
            return f"(brain server unreachable: {e})"

    def remember(self, text, kind="semantic"):
        return self._post("/remember", {"text": text, "kind": kind}).get("id")

    def recall(self, query):
        return self._post("/recall", {"query": query}).get("hits", [])
