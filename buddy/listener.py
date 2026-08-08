"""Voice input (optional). Offline speech-to-text via Vosk.

Only imported when you run with --voice. If deps missing, tells you what to install.
Two ways to command:
  - one shot:  say  "buddy what time is it"   (wake + command together)
  - two step:  say  "buddy"  ... then         "what time is it"
"""
import json, os, queue

def _find_model():
    """Look in models/vosk, or the first vosk-model-* folder under models/."""
    base = "models"
    p = os.path.join(base, "vosk")
    if os.path.isdir(p):
        return p
    if os.path.isdir(base):
        for name in os.listdir(base):
            if name.startswith("vosk-model") and os.path.isdir(os.path.join(base, name)):
                return os.path.join(base, name)
    return None

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
    rec = KaldiRecognizer(Model(model_path), 16000)
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
            elif wake in text:
                cmd = text.split(wake, 1)[1].strip()
                if cmd:                     # one-shot: command came with wake word
                    on_command(cmd)
                else:                       # just the wake word -> wait for next
                    awake = True
                    _state("listening")
                    print("(listening for your command...)")
