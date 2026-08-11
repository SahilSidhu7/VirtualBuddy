"""Volume and media keys — the things people reach for without looking.

Windows: sends the same virtual key codes the keyboard's media keys send, so it
works with whatever is playing (Spotify, YouTube in a browser, a game).
Linux/macOS get the usual CLI equivalents where they exist.
"""
import os, re, sys, subprocess

from buddy import slots

# Windows virtual key codes
_VK = {"mute": 0xAD, "down": 0xAE, "up": 0xAF,
       "next": 0xB0, "prev": 0xB1, "stop": 0xB2, "play": 0xB3}

_STEP = 2                # each key press moves Windows volume ~2%


def _tap(key, times=1):
    if os.name == "nt":
        import ctypes
        code = _VK[key]
        for _ in range(times):
            ctypes.windll.user32.keybd_event(code, 0, 0, 0)
            ctypes.windll.user32.keybd_event(code, 0, 2, 0)
        return True
    return False


def _mac_volume(delta=None, absolute=None, mute=None):
    if absolute is not None:
        script = f"set volume output volume {absolute}"
    elif mute is not None:
        script = f"set volume output muted {'true' if mute else 'false'}"
    else:
        script = f"set volume output volume (output volume of (get volume settings) + {delta})"
    subprocess.run(["osascript", "-e", script], capture_output=True)


def _linux_volume(arg):
    for cmd in (["pactl", "set-sink-volume", "@DEFAULT_SINK@", arg],
                ["amixer", "-q", "sset", "Master", arg]):
        try:
            if subprocess.run(cmd, capture_output=True).returncode == 0:
                return True
        except FileNotFoundError:
            continue
    return False


def _current_volume():
    """Windows only — read the master volume so buddy can report a number."""
    if os.name != "nt":
        return None
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        dev = AudioUtilities.GetSpeakers()
        iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        vol = cast(iface, POINTER(IAudioEndpointVolume))
        return round(vol.GetMasterVolumeLevelScalar() * 100)
    except Exception:
        return None                 # pycaw is optional; the key presses still work


def _set_volume(pct):
    pct = max(0, min(100, int(pct)))
    if os.name == "nt":
        cur = _current_volume()
        if cur is None:             # no pycaw: go to zero, then step up
            _tap("down", 50)
            _tap("up", pct // _STEP)
            return f"Volume set to about {pct}%."
        delta = pct - cur
        _tap("up" if delta > 0 else "down", abs(delta) // _STEP + 1)
        return f"Volume set to about {pct}%."
    if sys.platform == "darwin":
        _mac_volume(absolute=pct)
    else:
        _linux_volume(f"{pct}%")
    return f"Volume set to {pct}%."


def _wants_percent(text):
    m = re.search(r"(\d{1,3})\s*(?:%|percent)", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(?:to|at)\s+(\d{1,3})\b", text, re.I)
    return int(m.group(1)) if m else None


def volume(text, ctx):
    t = slots.clean(text)
    pct = _wants_percent(text)
    if pct is not None:
        return _set_volume(pct)
    if "unmute" in t or "sound back" in t:          # check before "mute" — it contains it
        _tap("mute")                                # the mute key toggles
        return "Unmuted."
    if any(w in t for w in ("mute", "silence", "shut up", "be quiet")):
        if _tap("mute"):
            return "Muted."
        if sys.platform == "darwin":
            _mac_volume(mute=True); return "Muted."
        _linux_volume("0%"); return "Muted."
    if any(w in t for w in ("max", "full", "loudest")):
        return _set_volume(100)
    steps = 5                                      # a noticeable but not jarring nudge
    n = slots.number(text)
    if n and n <= 20:
        steps = n
    if any(w in t for w in ("down", "lower", "quieter", "decrease", "reduce", "softer")):
        if _tap("down", steps):
            return "Turned it down."
        if sys.platform == "darwin":
            _mac_volume(delta=-10)
        else:
            _linux_volume("-10%")
        return "Turned it down."
    if _tap("up", steps):
        return "Turned it up."
    if sys.platform == "darwin":
        _mac_volume(delta=10)
    else:
        _linux_volume("+10%")
    return "Turned it up."


def media(text, ctx):
    t = slots.clean(text)
    if any(w in t for w in ("next", "skip", "forward")):
        _tap("next"); return "Next track."
    if any(w in t for w in ("previous", "prev", "back", "last track", "go back")):
        _tap("prev"); return "Previous track."
    if "stop" in t:
        _tap("stop"); return "Stopped."
    _tap("play")
    return "Play/pause."


SKILLS = [
    {"name": "volume", "desc": "change or mute the system volume",
     "phrases": ["turn the volume up", "turn it down", "make it louder", "make it quieter",
                 "mute the sound", "unmute", "set volume to 30 percent", "volume max",
                 "too loud", "i cant hear it"],
     "run": volume},
    {"name": "media", "desc": "play, pause or skip whatever is playing",
     "phrases": ["pause the music", "play music", "resume playback", "skip this song",
                 "next track", "previous song", "stop the music", "play pause"],
     "run": media},
]
