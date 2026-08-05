"""Buddy talks back. Uses pyttsx3 (offline). Prints if unavailable."""

_engine = None

def _get():
    global _engine
    if _engine is None:
        try:
            import pyttsx3
            _engine = pyttsx3.init()
        except Exception:
            _engine = False  # mark as unavailable
    return _engine

def _safe_print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:  # windows console can't do some chars
        import sys
        enc = sys.stdout.encoding or "ascii"
        print(msg.encode(enc, "replace").decode(enc))

def say(text, speak=True):
    _safe_print(f"[buddy] {text}")
    if not speak:
        return
    eng = _get()
    if eng:
        try:
            eng.say(text)
            eng.runAndWait()
        except Exception:
            pass
