"""Seeing the screen and images, as tools.

Two of them, and the split matters. `look_at_screen` is for questions about
what is happening now — a dialog, an error, a window the agent just opened.
`look_at_image` is for a file, which is the case where the user hands over a
screenshot or a photo and asks what it says.

Both refuse clearly when no vision model is installed rather than answering
from imagination, which is the failure mode that makes a blind assistant worse
than none.
"""
from __future__ import annotations

from pathlib import Path

from vb import sandbox, vision
from vb.registry import Result, skill


@skill(
    "look_at_screen",
    "Look at what is currently on the screen and answer a question about it",
    ["what is on my screen", "what does this window say", "read the error on screen",
     "look at my screen", "what am i looking at", "what does the dialog say",
     "can you see this"],
    slow=True, tags=["vision"],
    triggers=[r"\bon (my |the )?screen\b", r"\blook at\b", r"\bwhat do you see\b"],
)
def look_at_screen(question: str = "") -> Result:
    """Take a screenshot and answer a question about what is in it."""
    ready, detail = vision.available()
    if not ready:
        return Result.fail("I cannot see yet.", detail)

    shot = vision.screenshot()
    if not shot:
        return Result.fail("The screen could not be captured.",
                           "Pillow's ImageGrab is what does this; on a locked "
                           "or remote session it returns nothing.")
    ok, answer = vision.look(shot, question)
    if not ok:
        return Result.fail("I could not make sense of the screen.", answer)
    return Result(text=answer, detail=f"from {shot.name}", data={"image": str(shot)})


@skill(
    "look_at_image",
    "Look at an image file and answer a question about it",
    ["what is in this picture", "describe this image", "read the text in this screenshot",
     "what does this photo show", "look at this file and tell me"],
    slow=True, tags=["vision"],
)
def look_at_image(path: str, question: str = "") -> Result:
    """Answer a question about an image on disk."""
    ready, detail = vision.available()
    if not ready:
        return Result.fail("I cannot see yet.", detail)

    target = Path(path).expanduser()
    if not target.is_absolute():
        target = sandbox.workspace() / target
    ok, answer = vision.look(target, question)
    if not ok:
        return Result.fail("I could not read that image.", answer)
    return Result(text=answer, data={"image": str(target)})
