"""Looking at things: the screen, and images on disk.

An agent that can act on a machine but cannot see it is working blind. It can
open a window and then has no idea what the window says; it can be told "fix
the error in that dialog" and have nothing to go on. This is the eye.

It runs on a separate local model, because vision models are their own weights
and holding two 5GB models in an 8GB card at once does not work. Ollama unloads
one to load the other, which costs a few seconds per switch — acceptable for
something asked occasionally, which is why nothing here happens automatically.
The vision model is also optional: with none installed, the tools say so
plainly instead of guessing at what is on screen.

Screenshots never leave the machine. They go to the model over localhost and
are deleted after, and the file the model reads is written to the workspace so
it is somewhere the user can look.
"""
from __future__ import annotations

import base64
import io
import time
from pathlib import Path

from vb import config, llm, progress, sandbox

# Vision models, best first. Sizes are the download.
MODELS = [
    ("qwen2.5vl:7b", 6.0, "Reads text on screen well. Best if it fits."),
    ("llava:7b", 4.7, "Solid general description, weaker at small text."),
    ("moondream", 1.7, "Tiny. Rough descriptions only."),
]
TIMEOUT = 180
MAX_EDGE = 1600            # screenshots are downscaled to this before sending


def _capabilities(model: str) -> list[str]:
    """What Ollama says a model can do. Cached; the answer never changes for a
    given tag."""
    cache = llm._state.setdefault("caps", {})
    if model not in cache:
        import json
        import urllib.request
        try:
            req = urllib.request.Request(
                llm.HOST + "/api/show",
                data=json.dumps({"model": model}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                cache[model] = list(json.loads(r.read()).get("capabilities") or [])
        except Exception:
            cache[model] = []
    return cache[model]


def sees(model: str) -> bool:
    return "vision" in _capabilities(model)


def installed_model() -> str | None:
    """The best vision model actually present, or None.

    The work model is tried **first**, before any of the dedicated ones. Modern
    general models increasingly ship with an image encoder — hermes-agent and
    qwen3.5:9b both do — and a work model that can see costs nothing extra: it
    is already resident, so there is no 6GB eviction and no second download.
    Preferring a dedicated VLM here would trade a free capability for a
    multi-gigabyte pull and a ten-second model swap per glance.
    """
    chosen = config.get("vision_model")
    if chosen and llm.installed(chosen):
        return chosen
    from vb import backends
    work = backends.work_model()
    if llm.installed(work) and sees(work):
        return work
    for name, _size, _blurb in MODELS:
        if llm.installed(name):
            return name
    # Anything else installed that can see, rather than declaring blindness
    # while a capable model sits on disk.
    for name in llm.models():
        if sees(name):
            return name
    return None


def options() -> list[dict]:
    """What could be installed, with how it would run on this card."""
    vram = llm.vram_mb()
    out = []
    for name, size, blurb in MODELS:
        need = size * 1024 * 1.2
        out.append({
            "name": name, "size_gb": size, "blurb": blurb,
            "installed": llm.installed(name),
            "fit": "good" if vram >= need else
                   ("tight" if vram >= need * 0.65 else "slow"),
        })
    return out


def available() -> tuple[bool, str]:
    if not llm.running():
        return False, llm.status()["message"]
    model = installed_model()
    if not model:
        best = MODELS[0][0]
        return False, (f"No vision model installed. `ollama pull {best}` "
                       f"({MODELS[0][1]:.0f}GB) gives me eyes.")
    return True, model


# ------------------------------------------------------------------ capture
def screenshot(region: tuple[int, int, int, int] | None = None) -> Path | None:
    """Grab the screen to a PNG in the workspace. None if it cannot.

    Written to disk rather than held in memory so the user can open the exact
    image the model was shown — "what did it actually see" is the first
    question when a visual answer looks wrong.
    """
    try:
        from PIL import ImageGrab
    except ImportError:
        return None
    try:
        image = ImageGrab.grab(bbox=region, all_screens=region is None)
    except Exception:
        return None

    # Downscaled before it is sent. A 4K screenshot is several megabytes of
    # base64 and the model reads it no better than a 1600px one.
    if max(image.size) > MAX_EDGE:
        scale = MAX_EDGE / max(image.size)
        image = image.resize((int(image.width * scale), int(image.height * scale)))

    path = sandbox.workspace() / f"screen_{int(time.time())}.png"
    try:
        image.save(path, "PNG")
    except OSError:
        return None
    return path


def _encode(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) > 12_000_000:          # a model will not take an enormous file
        try:
            from PIL import Image
            with Image.open(path) as image:
                image.thumbnail((MAX_EDGE, MAX_EDGE))
                buffer = io.BytesIO()
                image.save(buffer, "PNG")
                raw = buffer.getvalue()
        except Exception:
            return None
    return base64.b64encode(raw).decode("ascii")


# --------------------------------------------------------------------- ask
def look(path: Path | str, question: str = "") -> tuple[bool, str]:
    """Ask the vision model about an image. Returns (ok, answer)."""
    ready, detail = available()
    if not ready:
        return False, detail
    model = detail

    image = Path(path)
    if not image.exists():
        return False, f"There is no image at {image}."
    encoded = _encode(image)
    if not encoded:
        return False, f"{image.name} could not be read as an image."

    progress.say(f"Looking at {image.name}…")
    payload = {
        "model": model,
        "prompt": question.strip() or "Describe what is in this image.",
        "images": [encoded],
        "stream": False,
        "keep_alive": "5m",           # short: it competes with the work model
        # A model that reasons puts its reasoning in `thinking` and leaves
        # `response` empty, and the answer here was "the vision model said
        # nothing" while the model was in fact describing the screen. Now that
        # the work model doubles as the eye — see `installed_model` — this path
        # meets a reasoning model as a matter of course.
        "think": False,
        # num_ctx is pinned for the same reason it is in `llm.ask`: left alone,
        # a model that declares a 262144-token context tries to allocate a KV
        # cache for all of it, and on an 8GB card Ollama answers 500
        # "llama-server startup failed ... cudaMalloc failed: out of memory".
        # A vision model needs the room more than most — the image projector
        # is loaded on top of the weights.
        "options": {"temperature": 0.1, "num_predict": 700,
                    "num_ctx": llm.num_ctx()},
    }
    out = llm._post("/api/generate", payload, TIMEOUT)
    if not out:
        return False, llm.last_error() or "The vision model did not answer."
    text = llm.strip_thinking(out.get("response")
                              or out.get("thinking") or "").strip()
    return (True, text) if text else (False, "The vision model said nothing.")
