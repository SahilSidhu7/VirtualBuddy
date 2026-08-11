"""What's happening on my PC — activity, open apps, disk, network, busy processes.

The plain "status" skill (report.py) is a one-liner. These answer the questions
people actually ask when something feels off: what's running, what's eating the
CPU, how much room is left, am I online.
"""
import os, shutil, time, datetime

_BYTES = ("B", "KB", "MB", "GB", "TB")


def _human(n):
    n = float(n or 0)
    for unit in _BYTES:
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB", "MB") else f"{n:.1f} {unit}"
        n /= 1024


def _psutil():
    try:
        import psutil
        return psutil
    except Exception:
        return None


def _uptime(ps):
    secs = time.time() - ps.boot_time()
    h, m = divmod(int(secs // 60), 60)
    d, h = divmod(h, 24)
    if d:
        return f"{d}d {h}h"
    return f"{h}h {m}m" if h else f"{m}m"


# kernel bookkeeping the user never means when they ask "what's using my PC"
_NOISE_PROCS = {"system idle process", "system", "registry", "memory compression",
                "idle", "", "?"}


# A full scan opens a handle per process (~360 here) and costs ~1.3s per pass on an
# idle machine — but 10s+ when the box is genuinely busy, which is exactly when
# someone asks what's slowing it down. So: cache briefly, skip the priming pass when
# the counters are already warm, and bail out with a partial answer rather than hang.
import threading

_SCAN_CACHE = {"ts": 0.0, "agg": {}}
_SCAN_TTL = 8.0             # a fresh-enough answer to the same question
_PRIME_TTL = 60.0           # psutil keeps its Process objects, so counters stay primed
_scan_lock = threading.Lock()
_refreshing = [False]


def _full_scan(ps):
    """One accurate pass. Never truncated — a partial scan ranks whichever
    processes happened to come first, which is worse than being slow."""
    if time.time() - _SCAN_CACHE["ts"] > _PRIME_TTL:
        # cpu_percent() is a delta since its own last call — without a priming pass
        # every process reports 0%. Recent scans leave the counters already primed.
        list(ps.process_iter(["cpu_percent"]))
        time.sleep(0.05)
    agg = {}
    for p in ps.process_iter(["name", "cpu_percent", "memory_info"]):
        try:
            info = p.info
            name = (info["name"] or "?").replace(".exe", "")
            if name.strip().lower() in _NOISE_PROCS:
                continue
            cpu = info["cpu_percent"] or 0.0
            rss = getattr(info["memory_info"], "rss", 0) or 0
        except Exception:
            continue                           # process died mid-scan; fine
        cur = agg.setdefault(name, [0.0, 0])
        cur[0] += cpu
        cur[1] += rss
    _SCAN_CACHE.update({"ts": time.time(), "agg": agg})
    return agg


def _scan(ps):
    """{name: [cpu, rss]}. Instant once warm; refreshes behind the answer.

    A full pass opens a handle per process (~360 here): ~1.3s idle, but 10s+ when
    the machine is genuinely busy — which is exactly when someone asks what's
    slowing it down. So only the very first ask waits.
    """
    age = time.time() - _SCAN_CACHE["ts"]
    if age < _SCAN_TTL and _SCAN_CACHE["agg"]:
        return _SCAN_CACHE["agg"]
    with _scan_lock:
        start = not _refreshing[0]
        if start:
            _refreshing[0] = True
    if start:
        if not _SCAN_CACHE["agg"]:
            try:                               # nothing cached yet: this one has to wait
                return _full_scan(ps)
            finally:
                _refreshing[0] = False

        def work():
            try:
                _full_scan(ps)
            finally:
                _refreshing[0] = False
        threading.Thread(target=work, daemon=True).start()
    elif not _SCAN_CACHE["agg"]:
        # a scan (usually the startup warm-up) is already running — wait for it
        # instead of kicking off a second one and doubling the work
        for _ in range(200):
            time.sleep(0.1)
            if _SCAN_CACHE["agg"]:
                break
    return _SCAN_CACHE["agg"]


def warm():
    """Prime the process scan in the background so the first question is instant.

    Called at startup. Without it the first "what's using my CPU" pays the whole
    scan — 14s on a machine that's already struggling.
    """
    ps = _psutil()
    if not ps or _SCAN_CACHE["agg"]:
        return
    threading.Thread(target=lambda: _full_scan(ps), daemon=True).start()


def _top(ps, n=5, by="cpu"):
    """Busiest processes, merged by name so 40 chrome tabs read as one line."""
    agg = _scan(ps)
    cores = ps.cpu_count() or 1
    key = 0 if by == "cpu" else 1
    ranked = sorted(agg.items(), key=lambda kv: kv[1][key], reverse=True)
    out = []
    for name, (cpu, rss) in ranked[:n]:
        if cpu < 0.5 and by == "cpu" and out:  # don't pad the list with idle apps
            break
        out.append(f"{name} ({cpu / cores:.0f}% cpu, {_human(rss)})")
    return out


def _active_window():
    try:
        import pygetwindow as gw
        w = gw.getActiveWindow()
        title = getattr(w, "title", None) or (w if isinstance(w, str) else None)
        return title.strip() if title else None
    except Exception:
        return None


def _open_windows(limit=12):
    try:
        import pygetwindow as gw
        titles = [t.strip() for t in gw.getAllTitles() if t and t.strip()]
    except Exception:
        return []
    seen, out = set(), []
    for t in titles:
        short = t if len(t) <= 60 else t[:57] + "..."
        if short.lower() in seen:
            continue
        seen.add(short.lower())
        out.append(short)
        if len(out) >= limit:
            break
    return out


# ---- skills ----

def pc_activity(text, ctx):
    """The big picture: load, memory, disk, uptime, what's busy, what's in front."""
    ps = _psutil()
    if not ps:
        return "Need psutil for this (pip install psutil)."
    # scanning processes takes a second or two — do it alongside the cheap readings
    import threading
    busy = []
    scan = threading.Thread(target=lambda: busy.extend(_top(ps, 4)), daemon=True)
    scan.start()
    cpu = ps.cpu_percent(interval=0.4)
    vm = ps.virtual_memory()
    parts = [f"CPU {cpu:.0f}%", f"memory {vm.percent:.0f}% ({_human(vm.used)} of {_human(vm.total)})"]
    try:
        du = shutil.disk_usage(os.path.expanduser("~"))
        parts.append(f"disk {_human(du.free)} free")
    except Exception:
        pass
    batt = ps.sensors_battery()
    if batt:
        plug = "charging" if batt.power_plugged else "on battery"
        parts.append(f"battery {batt.percent:.0f}% ({plug})")
    parts.append(f"up {_uptime(ps)}")
    lines = [", ".join(parts) + "."]
    scan.join(timeout=6)
    if busy:
        lines.append("Busiest: " + ", ".join(busy) + ".")
    else:
        # a very busy machine can take longer to scan than we're willing to wait —
        # say so instead of quietly dropping the line
        lines.append("(Still working out which apps are busiest — ask again in a moment.)")
    front = _active_window()
    if front:
        lines.append(f"In front: {front}")
    return "\n".join(lines)


def top_processes(text, ctx):
    ps = _psutil()
    if not ps:
        return "Need psutil for this (pip install psutil)."
    by = "memory" if any(w in text.lower() for w in ("memory", "ram", "mem")) else "cpu"
    rows = _top(ps, 6, by=by)
    if not rows:
        return "Couldn't read the process list."
    return f"Top by {by}:\n" + "\n".join(f"  {i+1}. {r}" for i, r in enumerate(rows))


def whats_open(text, ctx):
    wins = _open_windows()
    if not wins:
        return "I can't see any open windows (needs pygetwindow on Windows)."
    front = _active_window()
    head = f"{len(wins)} windows open. In front: {front}\n" if front else f"{len(wins)} windows open.\n"
    return head + "\n".join(f"  - {w}" for w in wins)


def disk_space(text, ctx):
    ps = _psutil()
    rows = []
    if ps:
        for part in ps.disk_partitions(all=False):
            try:
                u = shutil.disk_usage(part.mountpoint)
            except Exception:
                continue                       # empty CD drive / unreadable mount
            rows.append(f"{part.mountpoint} {_human(u.free)} free of {_human(u.total)} "
                        f"({u.used * 100 // u.total}% used)")
    if not rows:
        u = shutil.disk_usage(os.path.expanduser("~"))
        rows.append(f"{_human(u.free)} free of {_human(u.total)}")
    return "Disk:\n" + "\n".join(f"  {r}" for r in rows)


def network_status(text, ctx):
    ps = _psutil()
    online = _ping_ok()
    lines = ["Internet: " + ("connected" if online else "no reply from the internet")]
    if ps:
        try:
            a = ps.net_io_counters()
            time.sleep(0.8)
            b = ps.net_io_counters()
            down = (b.bytes_recv - a.bytes_recv) / 0.8
            up = (b.bytes_sent - a.bytes_sent) / 0.8
            lines.append(f"Right now: {_human(down)}/s down, {_human(up)}/s up")
            lines.append(f"Since boot: {_human(b.bytes_recv)} down, {_human(b.bytes_sent)} up")
        except Exception:
            pass
    ip = _lan_ip()
    if ip:
        lines.append(f"This PC on the network: {ip}")
    return "\n".join(lines)


def _ping_ok():
    import socket
    for host in ("1.1.1.1", "8.8.8.8"):
        try:
            socket.create_connection((host, 53), timeout=2).close()
            return True
        except Exception:
            continue
    return False


def _lan_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def uptime(text, ctx):
    ps = _psutil()
    if not ps:
        return "Need psutil for this (pip install psutil)."
    since = datetime.datetime.fromtimestamp(ps.boot_time())
    return f"Up {_uptime(ps)} — booted {since.strftime('%a %d %b, %I:%M %p')}."


SKILLS = [
    {"name": "pc_activity", "desc": "overall picture of what the PC is doing",
     "phrases": ["what is happening on my pc", "whats going on with my computer",
                 "how is my pc doing", "give me a system overview", "what is my pc up to",
                 "is anything slowing my computer down", "check on my machine",
                 "whats my computer doing right now"],
     "run": pc_activity},
    {"name": "top_processes", "desc": "which programs are using the most CPU or memory",
     "phrases": ["what is using my cpu", "which app is eating my memory",
                 "show me the top processes", "whats hogging my ram",
                 "what is slowing down my pc", "biggest memory users"],
     "run": top_processes},
    {"name": "whats_open", "desc": "list the open windows and apps",
     "phrases": ["what apps are open", "list my open windows", "what programs are running",
                 "what do i have open right now", "which window is in front"],
     "run": whats_open},
    {"name": "disk_space", "desc": "free space on each drive",
     "phrases": ["how much disk space do i have", "am i running out of storage",
                 "free space on my drives", "check my hard drive space", "disk usage"],
     "run": disk_space},
    {"name": "network_status", "desc": "internet connection and network speed",
     "phrases": ["am i online", "is my internet working", "check my network",
                 "how fast is my connection right now", "whats my ip address",
                 "is the wifi connected"],
     "run": network_status},
    {"name": "uptime", "desc": "how long the PC has been on",
     "phrases": ["how long has my pc been on", "when did i last reboot",
                 "system uptime", "how long since the last restart"],
     "run": uptime},
]
