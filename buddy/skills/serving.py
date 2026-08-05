"""What is this PC serving to the web, and is it working?
Lists listening ports + which app owns them, then HTTP-checks the web ones.
No tokens - just reads sockets + does local GETs.
"""
import urllib.request

# ports that are OS/infra noise, not "web serving"
_SKIP = {135, 139, 445, 5040, 7680, 49664, 49665, 49666, 49667, 49668, 49669}

def _health(port):
    for scheme in ("http", "https"):
        try:
            req = urllib.request.Request(f"{scheme}://127.0.0.1:{port}/")
            code = urllib.request.urlopen(req, timeout=3).status
            return f"{scheme} {code} OK"
        except urllib.error.HTTPError as e:
            return f"http {e.code}"     # responding, just non-200
        except Exception:
            continue
    return "no http response"

def _serving(text, ctx):
    try:
        import psutil
    except ImportError:
        return "Need psutil (pip install psutil)."
    owners = {}
    for c in psutil.net_connections("inet"):
        if c.status != "LISTEN" or not c.laddr:
            continue
        port = c.laddr.port
        if port in _SKIP:
            continue
        if port not in owners:
            try:
                owners[port] = psutil.Process(c.pid).name() if c.pid else "?"
            except Exception:
                owners[port] = "?"
    if not owners:
        return "Nothing serving."
    rows = []
    for port in sorted(owners):
        rows.append(f"  :{port:<6} {owners[port]:<18} {_health(port)}")
    return "Serving / listening:\n" + "\n".join(rows[:15])

SKILLS = [
    {"name": "serving", "desc": "list what this PC serves to the web and check if each is working",
     "phrases": ["what is my pc serving", "what ports are open", "is my server working",
                 "what am i serving to the web", "check my web servers", "is my site up"],
     "run": _serving},
]
