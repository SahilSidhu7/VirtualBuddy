"""Clipboard: read it back, put something in it, save it to a note.

Handy by voice — "what's on my clipboard" while your hands are somewhere else.
"""
import os, re, datetime

from buddy import slots


def _clip():
    try:
        import pyperclip
        return pyperclip
    except Exception:
        return None


def read_clipboard(text, ctx):
    pc = _clip()
    if not pc:
        return "Need pyperclip for clipboard access (pip install pyperclip)."
    try:
        data = pc.paste() or ""
    except Exception as e:
        return f"Couldn't read the clipboard: {e}"
    data = data.strip()
    if not data:
        return "The clipboard is empty."
    if len(data) > 500:
        return f"Clipboard ({len(data)} characters):\n{data[:500]}..."
    return f"Clipboard: {data}"


def _value(text):
    """The text the user wants copied, with the instruction words stripped off."""
    val = slots.quoted(text)
    if val:
        return val
    m = re.search(r"\b(?:copy|put|set)\s+(.+)$", text, re.I)
    if not m:
        return None
    val = m.group(1)
    # "...to my clipboard" / "on the clipboard" / "my clipboard to" all trail the value
    val = re.sub(r"\b(?:in|on|to)\s+(?:the|my|your)?\s*clipboard\b.*$", "", val, flags=re.I)
    val = re.sub(r"^\s*(?:my|the)?\s*clipboard\s+to\s+", "", val, flags=re.I)
    val = re.sub(r"^\s*(?:this|that|it)\s+", "", val, flags=re.I)
    return re.sub(r"\s+", " ", val).strip(" .,") or None


def set_clipboard(text, ctx):
    pc = _clip()
    if not pc:
        return "Need pyperclip for clipboard access (pip install pyperclip)."
    val = _value(text)
    if not val:
        return "Copy what? Try: copy \"some text\" to the clipboard."
    try:
        pc.copy(val)
    except Exception as e:
        return f"Couldn't set the clipboard: {e}"
    return f"Copied: {val[:120]}"


def save_clipboard(text, ctx):
    pc = _clip()
    if not pc:
        return "Need pyperclip for clipboard access (pip install pyperclip)."
    data = (pc.paste() or "").strip()
    if not data:
        return "Nothing on the clipboard to save."
    ws = ctx["cfg"].get("workspace", ".")
    os.makedirs(ws, exist_ok=True)
    name = slots.filename(text) or f"clip_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt"
    path = os.path.abspath(os.path.join(ws, name))
    with open(path, "w", encoding="utf-8") as f:
        f.write(data)
    return f"Saved the clipboard to {path}."


SKILLS = [
    {"name": "read_clipboard", "desc": "read what's on the clipboard",
     "phrases": ["what's on my clipboard", "read my clipboard", "what did i copy",
                 "show me the clipboard", "what's in the copy buffer",
                 "read what i copied", "tell me what i just copied",
                 "paste my clipboard back to me"],
     "run": read_clipboard},
    {"name": "set_clipboard", "desc": "put text on the clipboard",
     "phrases": ["copy this to my clipboard", "put \"hello\" on the clipboard",
                 "copy that text for me", "set my clipboard to something"],
     "run": set_clipboard},
    {"name": "save_clipboard", "desc": "save the clipboard to a file",
     "phrases": ["save my clipboard to a file", "write the clipboard to a note",
                 "dump the clipboard somewhere", "keep what i copied"],
     "run": save_clipboard},
]
