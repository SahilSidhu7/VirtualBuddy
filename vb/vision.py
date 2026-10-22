"""Looking at things: the screen, and images on disk.

An agent that can act on a machine but cannot see it is working blind. It can
open a window and then has no idea what the window says; it can be told "fix
the error in that dialog" and have nothing to go on. This is the eye.

It is a hosted vision model on NVIDIA's API (`provider.VISION_MODEL`). That
means **an image looked at here is sent to NVIDIA**, which is why nothing in
this module happens automatically: the user asks, the screenshot is taken, it
is sent once. The file is written to the workspace so the user can open the
exact image the model was shown.
"""
from __future__ import annotations

import base64
import io
import time
from pathlib import Path

from vb import config, progress, provider, sandbox

MAX_EDGE = 1280            # screenshots are downscaled to this before sending
# Inline images on the API are capped; past roughly this many base64
# characters the request is refused rather than truncated.
MAX_B64 = 180_000


def installed_model() -> str | None:
    return (config.get("vision_model") or provider.VISION_MODEL)         if provider.api_key() else None


def available() -> tuple[bool, str]:
    model = installed_model()
    if not model:
        return False, "No NVIDIA API key, so I cannot look at images."
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
    """The image as base64 JPEG, shrunk until it fits the inline limit."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            edge, quality = MAX_EDGE, 85
            for _ in range(6):
                copy = image.copy()
                copy.thumbnail((edge, edge))
                buffer = io.BytesIO()
                copy.save(buffer, "JPEG", quality=quality)
                encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
                if len(encoded) <= MAX_B64:
                    return encoded
                edge, quality = int(edge * 0.75), max(50, quality - 10)
    except Exception:
        return None
    return None


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
    text = provider.vision(
        question.strip() or "Describe what is in this image.", encoded,
        mime="image/jpeg")
    if text is None:
        return False, provider.last_error() or "The vision model did not answer."
    text = text.strip()
    return (True, text) if text else (False, "The vision model said nothing.")
