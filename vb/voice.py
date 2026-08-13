"""Push-to-talk speech input, fully offline via Vosk.

Optional in every sense: the packages are optional, the ~40MB model downloads
on demand into the user's data folder, and nothing else in the app imports this
until the microphone button is pressed.
"""
from __future__ import annotations

import json
import queue
import sys
import urllib.request
import zipfile
from pathlib import Path

from vb import config

MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
SAMPLE_RATE = 16000


def _roots() -> list[Path]:
    here = Path(__file__).resolve().parent.parent
    roots = [config.HOME / "models", here / "models"]
    if getattr(sys, "_MEIPASS", None):
        roots.append(Path(sys._MEIPASS) / "models")
    return roots


def find_model() -> Path | None:
    for base in _roots():
        direct = base / "vosk"
        if direct.is_dir() and any(direct.glob("*")):
            return direct
        if base.is_dir():
            for child in sorted(base.glob("vosk-model*")):
                if child.is_dir():
                    return child
    return None


def packages_present() -> bool:
    try:
        import sounddevice, vosk  # noqa: F401
        return True
    except Exception:
        return False


def available() -> bool:
    return packages_present() and find_model() is not None


def status() -> dict:
    if not packages_present():
        return {"state": "no_packages",
                "message": "Voice needs vosk and sounddevice.", "fix": "pip"}
    if find_model() is None:
        return {"state": "no_model",
                "message": "Speech model not downloaded (40MB).", "fix": "download"}
    return {"state": "ready", "message": "Voice ready."}


def install_packages(on_progress=None) -> bool:
    import subprocess
    if on_progress:
        on_progress("Installing vosk and sounddevice…")
    ok = subprocess.run([sys.executable, "-m", "pip", "install", "vosk", "sounddevice"],
                        capture_output=True).returncode == 0
    return ok


def download_model(on_progress=None) -> Path | None:
    """Fetch the small English model into the user's data folder."""
    target = config.data_dir("models")
    archive = target / "vosk.zip"
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=60) as r:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            with open(archive, "wb") as f:
                while chunk := r.read(1 << 16):
                    f.write(chunk)
                    done += len(chunk)
                    if on_progress and total:
                        on_progress(int(100 * done / total))
        with zipfile.ZipFile(archive) as z:
            z.extractall(target)
    except Exception:
        return None
    finally:
        archive.unlink(missing_ok=True)
    return find_model()


def listen_once(seconds: float = 6.0, silence_after: float = 1.2) -> str:
    """Record until the speaker stops, then return the transcript.

    Returns "" when nothing was said or voice isn't set up — callers treat an
    empty string as "user changed their mind", which is the honest reading.
    """
    model_path = find_model()
    if not model_path:
        return ""
    try:
        import sounddevice as sd
        from vosk import KaldiRecognizer, Model, SetLogLevel
    except Exception:
        return ""

    SetLogLevel(-1)
    rec = KaldiRecognizer(Model(str(model_path)), SAMPLE_RATE)
    audio: queue.Queue = queue.Queue()

    def feed(indata, _frames, _time, _status):
        audio.put(bytes(indata))

    said, quiet = [], 0.0
    block = 4000
    step = block / SAMPLE_RATE
    with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=block, dtype="int16",
                           channels=1, callback=feed):
        elapsed = 0.0
        while elapsed < seconds:
            try:
                data = audio.get(timeout=1.0)
            except queue.Empty:
                break
            elapsed += step
            if rec.AcceptWaveform(data):
                text = json.loads(rec.Result()).get("text", "").strip()
                if text:
                    said.append(text)
                    quiet = 0.0
            else:
                partial = json.loads(rec.PartialResult()).get("partial", "").strip()
                quiet = 0.0 if partial else quiet + step
                if said and quiet >= silence_after:
                    break

    tail = json.loads(rec.FinalResult()).get("text", "").strip()
    if tail:
        said.append(tail)
    return " ".join(said).strip()
