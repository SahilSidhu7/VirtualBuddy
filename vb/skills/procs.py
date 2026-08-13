"""Task manager: what is running, what it costs, and stopping it.

psutil's cpu_percent is a delta since its own previous call, so a single pass
over process_iter reports 0% for everything. Every reading here primes first,
waits, then measures.
"""
from __future__ import annotations

from vb import slots
from vb.pc.graph import human_size
from vb.registry import Result, skill

SAMPLE = 0.6          # seconds between the priming pass and the real one
KILL_VERBS = ("kill", "close", "stop", "quit", "end", "terminate")

# The idle process is the CPU doing nothing; reporting it as the top consumer
# is worse than useless when the question is "what's slowing my PC down".
IGNORE = {"system idle process", "idle"}


def _psutil():
    try:
        import psutil
        return psutil
    except ImportError:
        return None


def _missing() -> Result:
    return Result.fail("Task manager needs psutil.", "pip install psutil")


def _sample(limit: int = 60) -> list[dict]:
    """One measured pass over every process, grouped by executable name."""
    import time
    psutil = _psutil()
    for proc in psutil.process_iter(["name"]):
        try:
            proc.cpu_percent(None)                 # prime; result discarded
        except psutil.Error:
            continue
    time.sleep(SAMPLE)

    cores = psutil.cpu_count() or 1
    grouped: dict[str, dict] = {}
    for proc in psutil.process_iter(["name", "memory_info", "pid"]):
        try:
            name = proc.info["name"] or f"pid {proc.info['pid']}"
            cpu = proc.cpu_percent(None) / cores
            rss = proc.info["memory_info"].rss if proc.info["memory_info"] else 0
        except psutil.Error:
            continue
        if name.lower() in IGNORE:
            continue
        row = grouped.setdefault(name, {"name": name, "cpu": 0.0, "rss": 0, "count": 0,
                                        "pids": []})
        row["cpu"] += cpu
        row["rss"] += rss
        row["count"] += 1
        row["pids"].append(proc.info["pid"])
    return sorted(grouped.values(), key=lambda r: r["cpu"], reverse=True)[:limit]


@skill(
    "running_apps",
    "Show what is running and what it is costing",
    ["what's running on my pc", "show me the task manager",
     "what's using my cpu", "what's eating my memory", "list running processes",
     "why is my pc slow", "what's hogging the cpu right now",
     "open task manager", "which apps are open"],
    slow=True, tags=["pc"],
    triggers=[r"\b(cpu|ram|memory|task manager|processes?)\b",
              r"\b(running|open)\b.{0,16}\b(apps?|programs?|processes?)\b",
              r"\bwhy is\b.{0,16}\bslow\b"],
)
def running_apps(**_) -> Result:
    psutil = _psutil()
    if not psutil:
        return _missing()
    rows = _sample()
    mem = psutil.virtual_memory()
    by_cpu = rows[:8]
    by_mem = sorted(rows, key=lambda r: r["rss"], reverse=True)[:8]

    head = (f"CPU {psutil.cpu_percent(None):.0f}%  ·  "
            f"RAM {mem.percent:.0f}% of {human_size(mem.total)}  ·  "
            f"{len(psutil.pids())} processes")
    cpu_list = "\n".join(
        f"  {r['cpu']:>5.1f}%  {r['name']}" + (f"  ×{r['count']}" if r["count"] > 1 else "")
        for r in by_cpu)
    mem_list = "\n".join(
        f"  {human_size(r['rss']):>8}  {r['name']}" for r in by_mem)
    return Result(text=f"{head}\n\nTop CPU:\n{cpu_list}\n\nTop memory:\n{mem_list}",
                  data=rows)


@skill(
    "kill_app",
    "Close a running program",
    ["kill chrome", "close spotify", "stop the discord process",
     "terminate notepad", "force quit steam", "shut down chrome please",
     "end the zoom process"],
    slots=lambda t: {"target": slots.after(t, KILL_VERBS)}, danger=True, tags=["pc"],
    triggers=[r"\b(kill|terminate|force quit|shut down|shutdown)\b",
              r"\b(close|stop|end|quit)\b.{0,24}\b(app|process|program|chrome|"
              r"spotify|discord|steam|notepad|zoom|edge|firefox)\b"],
)
def kill_app(target: str = "", **_) -> Result:
    psutil = _psutil()
    if not psutil:
        return _missing()
    wanted = (target or "").strip().lower().removesuffix(".exe")
    if not wanted:
        return Result.fail("Close what?", "Try: kill chrome")

    matched = []
    for proc in psutil.process_iter(["name", "pid"]):
        name = (proc.info["name"] or "").lower()
        if wanted in name.removesuffix(".exe"):
            matched.append(proc)
    if not matched:
        return Result.fail(f"Nothing running called “{target}”.",
                           "Ask what's running to see the list.")

    closed, failed = 0, 0
    for proc in matched:
        try:
            proc.terminate()
            closed += 1
        except psutil.Error:
            failed += 1
    gone, alive = psutil.wait_procs(matched, timeout=3)
    for proc in alive:                       # ignored the polite request
        try:
            proc.kill()
        except psutil.Error:
            failed += 1
    note = f"{failed} refused to close." if failed else ""
    return Result(text=f"Closed {closed} {matched[0].info['name']} process"
                       f"{'es' if closed != 1 else ''}.", detail=note)


@skill(
    "pc_health",
    "Report battery, disk space and uptime",
    ["how's my pc doing", "check my battery", "how much disk space is left",
     "how long has this pc been on", "system status",
     "how much room is left on my drive", "is my battery ok"],
    tags=["pc"],
    triggers=[r"\bbattery\b", r"\buptime\b",
              r"\b(how much|space|room)\b.{0,20}\b(left|free|remaining)\b",
              r"\bdisk space\b"],
)
def pc_health(**_) -> Result:
    import time
    psutil = _psutil()
    if not psutil:
        return _missing()
    lines = []

    mem = psutil.virtual_memory()
    lines.append(f"RAM    {mem.percent:.0f}% used of {human_size(mem.total)}"
                 f"  ({human_size(mem.available)} free)")

    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        lines.append(f"Disk   {part.mountpoint:<4} {usage.percent:.0f}% used, "
                     f"{human_size(usage.free)} free of {human_size(usage.total)}")

    battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    if battery:
        state = "charging" if battery.power_plugged else "on battery"
        left = ""
        if not battery.power_plugged and battery.secsleft > 0:
            left = f", {battery.secsleft // 3600}h {(battery.secsleft % 3600) // 60}m left"
        lines.append(f"Power  {battery.percent:.0f}% ({state}{left})")

    up = time.time() - psutil.boot_time()
    lines.append(f"Uptime {int(up // 86400)}d {int(up % 86400 // 3600)}h "
                 f"{int(up % 3600 // 60)}m")
    return Result(text="\n".join(lines))
