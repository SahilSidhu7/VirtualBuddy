"""Send a command to another PC running buddy. PC1 <-> PC2 control over WiFi.

Peers live in config.yaml:
  peers:
    pc2: "http://192.168.1.42:8770"
    laptop: "http://192.168.1.55:8770"
Say e.g. "on pc2 lock the screen" or "tell laptop to take a screenshot".
"""
import json, re, urllib.request

def _relay(peer_url, text, token):
    body = json.dumps({"token": token, "text": text}).encode()
    req = urllib.request.Request(peer_url.rstrip("/") + "/api/command", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read()).get("reply", "(no reply)")

def remote(text, ctx):
    peers = ctx["cfg"].get("peers") or {}
    if not peers:
        return "No peers set. Add them under 'peers' in config.yaml."
    low = text.lower()
    target = next((name for name in peers if name.lower() in low), None)
    if not target:
        return f"Which PC? Known: {', '.join(peers)}."
    # strip "on <peer>", "tell <peer> to" -> the sub-command for the other PC
    sub = re.sub(rf"\b(on|tell|to|the)\b|\b{re.escape(target)}\b", " ", low)
    sub = re.sub(r"\s+", " ", sub).strip()
    try:
        reply = _relay(peers[target], sub, ctx["cfg"].get("server_token", "changeme"))
        return f"[{target}] {reply}"
    except Exception as e:
        return f"Could not reach {target}: {e}"

SKILLS = [
    {"name": "remote", "desc": "run a command on another PC (peer) over WiFi",
     "phrases": ["on pc2 lock the screen", "tell my other pc", "on the laptop take a screenshot",
                 "send this to pc2", "run on my other computer"],
     "run": remote},
]
