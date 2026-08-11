"""Voice input (optional). Offline speech-to-text via Vosk.

Only imported when you run with --voice. If deps missing, tells you what to install.
Two ways to command:
  - one shot:  say  "buddy what time is it"   (wake + command together)
  - two step:  say  "buddy"  ... then         "what time is it"
"""
import json, os, queue, sys

from buddy import settings


def _model_roots():
    """Everywhere a Vosk model could reasonably live, best first.

    Relying on a relative "models" path only worked when buddy was launched from
    the project folder — not from the Start menu, and not when frozen.
    """
    roots = [os.path.join(settings.HOME, "models")]              # user folder (survives updates)
    pkg = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    roots.append(os.path.join(pkg, "models"))                    # source checkout
    if getattr(sys, "_MEIPASS", None):
        roots.append(os.path.join(sys._MEIPASS, "models"))       # bundled in the .exe
    roots.append(os.path.join(os.getcwd(), "models"))            # legacy behaviour
    return roots


def _find_model():
    """models/vosk, or the first vosk-model-* folder under any known models dir."""
    for base in _model_roots():
        p = os.path.join(base, "vosk")
        if os.path.isdir(p):
            return p
        if os.path.isdir(base):
            for name in sorted(os.listdir(base)):
                if name.startswith("vosk-model") and os.path.isdir(os.path.join(base, name)):
                    return os.path.join(base, name)
    return None


def available():
    """True when voice input can actually run right now."""
    try:
        import sounddevice, vosk           # noqa: F401
    except Exception:
        return False
    return _find_model() is not None


def why_unavailable():
    try:
        import sounddevice, vosk           # noqa: F401
    except Exception:
        return "Voice needs: pip install vosk sounddevice"
    if not _find_model():
        return ("No speech model found. Put vosk-model-small-en-us-0.15 in "
                + os.path.join(settings.HOME, "models", "vosk"))
    return None


# What the small speech model actually returns when someone says these wake words.
# Measured, not guessed — "buddy" comes back as "but he" often enough to matter.
_WAKE_VARIANTS = {
    "buddy": ["buddy", "buddie", "buddi", "budy", "body", "but he", "bud he",
              "buddha", "bunny", "birdie"],
    "jarvis": ["jarvis", "jervis", "harvest", "java's"],
    "computer": ["computer", "compute", "commuter"],
}


def wake_variants(wake, extra=None):
    wake = (wake or "buddy").strip().lower()
    out = [wake] + list(_WAKE_VARIANTS.get(wake, []))
    out += [str(v).strip().lower() for v in (extra or []) if str(v).strip()]
    return sorted(set(out), key=len, reverse=True)      # longest first: "bud he" before "bud"


def wake_split(text, wake, extra=None):
    """Command after the wake word, "" if only the wake word, None if not addressed.

    Speech recognition mangles short names constantly. An exact `wake in text`
    check silently dropped those commands, so match known mishearings too, then
    fall back to a fuzzy comparison of the opening word.
    """
    import difflib
    text = (text or "").strip().lower()
    if not text:
        return None
    for variant in wake_variants(wake, extra):
        if text.startswith(variant + " ") or text == variant:
            return text[len(variant):].strip()
        # mid-sentence ("hey buddy, open chrome") counts, but only on word
        # boundaries — otherwise "nobody" and "somebody" wake buddy up
        import re
        m = re.search(rf"\b{re.escape(variant)}\b", text)
        if m:
            return text[m.end():].strip()
    head = text.split()[0]
    if difflib.SequenceMatcher(None, head, (wake or "buddy").lower()).ratio() >= 0.75:
        return text[len(head):].strip()
    return None


_model = None


def _model_once():
    """Load the speech model once — it takes ~1.5s, and the mic button is clicked often."""
    global _model
    if _model is None:
        from vosk import Model, SetLogLevel
        SetLogLevel(-1)
        _model = Model(_find_model())
    return _model


def listen_once(cfg, seconds=6):
    """Record one utterance and return the text. Used by the dashboard's mic button.

    No wake word — the user already said "listen" by clicking.
    Returns "" if nothing was heard.
    """
    problem = why_unavailable()
    if problem:
        return problem
    import sounddevice as sd
    from vosk import KaldiRecognizer
    q = queue.Queue()
    rec = KaldiRecognizer(_model_once(), 16000)
    heard = []
    import time
    deadline = time.time() + max(2, seconds)
    with sd.RawInputStream(samplerate=16000, blocksize=8000, dtype="int16",
                           channels=1, callback=lambda d, f, t, s: q.put(bytes(d))):
        while time.time() < deadline:
            try:
                data = q.get(timeout=0.5)
            except queue.Empty:
                continue
            if rec.AcceptWaveform(data):
                said = json.loads(rec.Result()).get("text", "").strip()
                if said:
                    heard.append(said)
                    break                    # a complete utterance — stop listening
    if not heard:
        said = json.loads(rec.FinalResult()).get("text", "").strip()
        if said:
            heard.append(said)
    return " ".join(heard)

def listen_loop(cfg, on_command, on_state=None):
    def _state(s):
        if on_state:
            try: on_state(s)
            except Exception: pass
    try:
        import sounddevice as sd
        from vosk import Model, KaldiRecognizer, SetLogLevel
    except Exception:
        print("Voice needs: pip install vosk sounddevice")
        return
    SetLogLevel(-1)  # quiet

    model_path = _find_model()
    if not model_path:
        print("Vosk model missing. Put one in ./models/vosk "
              "(download from alphacephei.com/vosk/models)")
        return

    wake = cfg["wake_word"].lower()
    q = queue.Queue()
    rec = KaldiRecognizer(_model_once(), 16000)
    awake = False  # true after wake word, waiting for next utterance

    def cb(indata, frames, t, status):
        q.put(bytes(indata))

    print(f"Listening. Say '{wake}' then your command.")
    with sd.RawInputStream(samplerate=16000, blocksize=8000, dtype="int16",
                           channels=1, callback=cb):
        while True:
            data = q.get()
            if not rec.AcceptWaveform(data):
                continue
            text = json.loads(rec.Result()).get("text", "").strip().lower()
            if not text:
                continue
            if awake:                       # two-step: this utterance is the command
                awake = False
                on_command(text)
                continue
            cmd = wake_split(text, wake, cfg.get("wake_variants"))
            if cmd is None:                 # not talking to buddy
                continue
            if cmd:                         # one-shot: command came with the wake word
                on_command(cmd)
            else:                           # just the wake word -> wait for the next line
                awake = True
                _state("listening")
                print("(listening for your command...)")
