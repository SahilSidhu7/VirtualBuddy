"""Local command server. Lets your phone or another PC on the same WiFi send
commands to buddy and get replies. Built-in http.server only - no installs.

Security: a shared token is required on every command. Only runs on your LAN.
Set server_token in config.yaml (change it from the default!).

Started by: python run.py --server   (or the control panel button)
"""
import json, socket, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

def lan_ip():
    """Best-guess LAN IP so you know the phone URL."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()

# minimal mobile web UI: type or talk, see reply
PAGE = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>Buddy</title><style>
body{font-family:system-ui;margin:0;background:#0f1220;color:#eef;padding:16px}
h2{color:#4aa3ff}input,button{font-size:18px;padding:10px;border-radius:8px;border:0}
#cmd{width:100%;box-sizing:border-box;margin:6px 0}
button{background:#4aa3ff;color:#fff;margin-right:6px}
#out{white-space:pre-wrap;background:#1a1f36;padding:12px;border-radius:8px;margin-top:10px;min-height:60px}
small{color:#89a}</style>
<h2>VirtualBuddy</h2>
<input id=tok placeholder="token" >
<input id=cmd placeholder="type a command..." >
<button onclick=send()>Send</button><button onclick=mic()>🎤 Talk</button>
<div id=out>ready.</div>
<small>same WiFi as your PC. token is set in config.yaml</small>
<script>
tok.value=localStorage.tok||'';
tok.onchange=()=>localStorage.tok=tok.value;
async function send(){
 out.textContent='...';
 let r=await fetch('/api/command',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({token:tok.value,text:cmd.value})});
 let d=await r.json(); out.textContent=d.reply||d.error||'no reply';
}
function mic(){
 let R=window.SpeechRecognition||window.webkitSpeechRecognition;
 if(!R){out.textContent='no speech support in this browser';return;}
 let r=new R();r.lang='en-US';r.onresult=e=>{cmd.value=e.results[0][0].transcript;send();};r.start();
}
cmd.addEventListener('keydown',e=>{if(e.key==='Enter')send();});
</script>"""

def make_handler(agent, token):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body if isinstance(body, bytes) else body.encode())

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, PAGE, "text/html; charset=utf-8")
            elif self.path == "/api/ping":
                self._send(200, json.dumps({"ok": True}))
            else:
                self._send(404, json.dumps({"error": "not found"}))

        def do_POST(self):
            if self.path != "/api/command":
                return self._send(404, json.dumps({"error": "not found"}))
            n = int(self.headers.get("Content-Length", 0))
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                return self._send(400, json.dumps({"error": "bad json"}))
            if data.get("token") != token:
                return self._send(401, json.dumps({"error": "bad token"}))
            text = (data.get("text") or "").strip()
            if not text:
                return self._send(400, json.dumps({"error": "empty"}))
            reply = agent.handle(text)
            self._send(200, json.dumps({"reply": reply}))

        def log_message(self, *a):
            pass  # quiet
    return H

def serve(agent, cfg, block=True):
    port = cfg.get("server_port", 8770)
    token = cfg.get("server_token", "changeme")
    httpd = ThreadingHTTPServer(("0.0.0.0", port), make_handler(agent, token))
    url = f"http://{lan_ip()}:{port}"
    print(f"[server] buddy on your WiFi at {url}  (token: {token})")
    if token == "changeme":
        print("[server] WARNING: change server_token in config.yaml")
    if block:
        httpd.serve_forever()
    else:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd
