"""A generic yes/no gate any skill can use before doing something irreversible.

A skill that wants approval returns `confirm.ask("Shut down the PC?", do_it)`.
Buddy replies with the question; the user's next "yes"/"no" is intercepted in
Agent.handle and routed back here instead of being treated as a new command.

Only one request can be pending at a time — a second `ask()` replaces the first,
so a stale gate can never fire against a later "yes".
"""
import threading

_YES = ("yes", "y", "yeah", "yep", "yup", "sure", "ok", "okay", "do it", "go ahead",
        "confirm", "please do", "affirmative")
_NO = ("no", "n", "nope", "nah", "cancel", "stop", "don't", "dont", "never mind",
       "nevermind", "abort")


class Pending:
    _lock = threading.Lock()
    _action = None            # callable -> reply string
    _question = None

    @classmethod
    def set(cls, question, action):
        with cls._lock:
            cls._question, cls._action = question, action

    @classmethod
    def active(cls):
        return cls._action is not None

    @classmethod
    def take(cls):
        with cls._lock:
            action, cls._action, cls._question = cls._action, None, None
            return action

    @classmethod
    def clear(cls):
        cls.take()


def is_verdict(text):
    t = (text or "").strip().lower().strip(" .!?")
    return t in _YES or t in _NO


def _said_yes(text):
    return (text or "").strip().lower().strip(" .!?") in _YES


def ask(question, action):
    """Hold `action` until the user approves. Returns the line buddy should say."""
    Pending.set(question, action)
    return f"{question} (yes / no)"


def resolve(text):
    """Run or drop the pending action. Returns buddy's reply, or None if nothing pending."""
    if not Pending.active():
        return None
    action = Pending.take()
    if action is None:
        return None
    if not _said_yes(text):
        return "Cancelled."
    try:
        return action()
    except Exception as e:
        return f"That failed: {e}"
