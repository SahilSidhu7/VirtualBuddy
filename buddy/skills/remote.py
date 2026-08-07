"""Send a command to another PC running buddy. PC1 <-> PC2 control over WiFi.

Peers (with optional nicknames) live in config.yaml — see buddy/peers.py.
Say e.g. "on gaming-pc lock the screen" or "tell laptop to take a screenshot".
If you don't name a machine, buddy uses your default_peer.
"""
import json, re, urllib.request

from buddy import peers as peer_book


def _relay(peer_url, text, token):
    body = json.dumps({"token": token, "text": text}).encode()
    req = urllib.request.Request(peer_url.rstrip("/") + "/api/command", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read()).get("reply", "(no reply)")

def remote(text, ctx):
    cfg = ctx["cfg"]
    known = peer_book.normalize(cfg)
    if not known:
        return ("No other machines set up yet. Add one in the dashboard's Sync tab "
                "(or under 'peers' in config.yaml), then say e.g. 'on laptop lock the screen'.")
    target, url = peer_book.resolve(cfg, text)
    if not target:
        return (f"Which machine? Known: {', '.join(known)}. "
                f"Tip: set a default in the Sync tab so you can skip the name.")
    low = text.lower()
    # strip "on <peer>/alias", "tell <peer> to" -> the sub-command for the other PC
    handles = [h for h in peer_book.names(cfg) if h in low]
    strip = "|".join(re.escape(h) for h in handles + ["on", "tell", "to", "the"])
    sub = re.sub(rf"\b({strip})\b", " ", low) if strip else low
    sub = re.sub(r"\s+", " ", sub).strip()
    try:
        reply = _relay(url, sub, cfg.get("server_token", "changeme"))
        return f"[{target}] {reply}"
    except Exception as e:
        return f"Could not reach {target}: {e}"

SKILLS = [
    {"name": "remote", "desc": "run a command on another PC (peer) over WiFi",
     "phrases": ["on pc2 lock the screen", "tell my other pc", "on the laptop take a screenshot",
                 "send this to pc2", "run on my other computer"],
     "run": remote},
]
