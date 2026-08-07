"""Brain server — runs on the 1050ti. The one brain + one memory the fleet shares.

Stdlib only (no FastAPI dep) so it stays light to stand up. Token-gated: every request
must carry the shared server_token. Endpoints:

  POST /handle   {text}         -> {reply}     full agent turn on the server
  POST /remember {text, kind}   -> {id}        write a memory
  POST /recall   {query}        -> {hits:[..]} read memories
  GET  /health                  -> {ok, model, role}

Start it:  python -c "from buddy.net.brain_server import serve; serve()"
or wire a --brain flag in run.py/vb.py (phase 2).
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from buddy import settings


def _make_handler(cfg, agent, memory):
    token = cfg.get("server_token", "changeme")

    class H(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _auth_ok(self):
            return self.headers.get("X-Token") == token

        def _read(self):
            n = int(self.headers.get("Content-Length", 0) or 0)
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                return {}

        def do_GET(self):
            if self.path == "/health":
                return self._send(200, {"ok": True, "model": cfg.get("llm_model"),
                                        "role": cfg.get("role")})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._auth_ok():
                return self._send(401, {"error": "bad token"})
            data = self._read()
            if self.path == "/handle":
                return self._send(200, {"reply": agent.handle(data.get("text", ""))})
            if self.path == "/remember":
                _id = memory.remember(data.get("text", ""),
                                      kind=data.get("kind", "semantic"))
                return self._send(200, {"id": _id})
            if self.path == "/recall":
                return self._send(200, {"hits": memory.recall(data.get("query", ""))})
            self._send(404, {"error": "not found"})

        def log_message(self, *a):
            pass

    return H


def serve(cfg=None):
    cfg = cfg or settings.load()
    from buddy.agent import Agent
    from buddy.memory.memory import Memory
    agent = Agent(cfg)
    memory = Memory(cfg)
    port = cfg.get("brain_port", 8771)
    srv = ThreadingHTTPServer(("0.0.0.0", port), _make_handler(cfg, agent, memory))
    print(f"[brain-server] listening on :{port} (role={cfg.get('role')}, model={cfg.get('llm_model')})")
    srv.serve_forever()
