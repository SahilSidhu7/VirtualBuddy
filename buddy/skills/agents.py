"""Find running Claude / AI agents on this PC. No tokens - just reads processes."""
import time

def _list(text, ctx):
    try:
        import psutil
    except ImportError:
        return "Need psutil (pip install psutil)."
    seen, rows = set(), []
    for p in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
        try:
            cl = " ".join(p.info["cmdline"] or [])
            if "claude" not in cl.lower():
                continue
            cwd = p.cwd()
            key = cwd or p.info["pid"]
            if key in seen:
                continue
            seen.add(key)
            age = int((time.time() - p.info["create_time"]) / 60)
            rows.append(f"pid {p.info['pid']:>6}  {age:>4}m  {cwd or '?'}")
        except Exception:
            continue
    if not rows:
        return "No Claude agents running."
    return f"{len(rows)} Claude agent(s):\n" + "\n".join(rows[:12])

SKILLS = [
    {"name": "list_agents", "desc": "list running Claude/AI agents and their project folders",
     "phrases": ["list running claude agents", "what agents are running", "show my claude agents",
                 "any claude running", "running ai agents"],
     "run": _list},
]
