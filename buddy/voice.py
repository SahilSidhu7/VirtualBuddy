"""Buddy talks back. Uses pyttsx3 (offline). Prints if unavailable.

Speaking happens on a worker thread: pyttsx3's runAndWait() blocks for the whole
utterance, so saying a two-line status answer used to freeze buddy for ~7 seconds
before the reply even came back. say() now queues the text and returns at once.

The engine is created on (and only touched by) that worker — SAPI voices do not
appreciate being driven from several threads.
"""
import queue, threading

_q = None
_worker = None
_lock = threading.Lock()


def _safe_print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:  # windows console can't do some chars
        import sys
        enc = sys.stdout.encoding or "ascii"
        print(msg.encode(enc, "replace").decode(enc))


def _run():
    try:
        import pyttsx3
        engine = pyttsx3.init()
    except Exception:
        # no speech on this machine: drain the queue so callers never block
        while True:
            if _q.get() is None:
                return
    while True:
        text = _q.get()
        if text is None:
            return
        try:
            engine.say(text)
            engine.runAndWait()
        except Exception:
            pass


def _ensure_worker():
    global _q, _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _q = queue.Queue()
            _worker = threading.Thread(target=_run, daemon=True)
            _worker.start()
    return _q


def say(text, speak=True):
    """Print the reply, and speak it in the background if speech is on."""
    _safe_print(f"[buddy] {text}")
    if not speak or not str(text).strip():
        return
    try:
        _ensure_worker().put(str(text))
    except Exception:
        pass


def wait(timeout=20):
    """Block until the queue drains (for callers that exit right after speaking)."""
    import time
    deadline = time.time() + timeout
    while _q is not None and not _q.empty() and time.time() < deadline:
        time.sleep(0.1)


def is_speaking():
    return _q is not None and not _q.empty()
