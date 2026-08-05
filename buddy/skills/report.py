"""Report back: system status the user asks about."""
import shutil, os

def _status(text, ctx):
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.3)
        mem = psutil.virtual_memory().percent
        batt = psutil.sensors_battery()
        b = f", battery {batt.percent}%" if batt else ""
        return f"CPU {cpu}%, memory {mem}%{b}."
    except Exception:
        total, used, free = shutil.disk_usage(os.path.expanduser("~"))
        return f"Disk free {free // (1024**3)} GB of {total // (1024**3)} GB. (pip install psutil for cpu/battery)"

SKILLS = [
    {"name": "status", "phrases": ["how is my pc", "system status", "cpu usage", "battery level",
                                   "report status", "how much memory am i using", "is my pc slow",
                                   "resource usage"], "run": _status},
]
