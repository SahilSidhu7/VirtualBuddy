"""The command panel: ask, see what matched, run it, read the answer.

Three states, all real: empty (before anything is asked), proposed (a match
waiting for a yes), and answered. Work happens on a worker thread so the sprite
keeps animating while a page is being scraped.
"""
from __future__ import annotations

import threading
import tkinter as tk

from vb import config, llm
from vb.agent import Agent, Turn
from vb.ui import theme as themes
from vb.ui.theme import Theme
from vb.ui.widgets import Button, Meter, drag_by, font

W, H = 420, 460
PAD = 14
PROP_TEXT_W = 178      # panel width minus the meter and the two buttons


def _ellipsis(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _note(text: str, detail: str = ""):
    from vb.registry import Result
    return Result(text=text, detail=detail)


class Panel(tk.Toplevel):
    def __init__(self, master: tk.Tk, agent: Agent, *, on_state=None,
                 on_avatar=None, on_close=None):
        super().__init__(master)
        self.agent = agent
        self.on_state = on_state or (lambda _s: None)
        self.on_avatar = on_avatar or (lambda _a: None)
        self.on_close = on_close or self.hide
        self.theme: Theme = themes.get(config.get("avatar"))
        self.turn: Turn | None = None
        self._busy = False

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=self.theme.base, highlightthickness=1,
                       highlightbackground=self.theme.line)
        self.geometry(f"{W}x{H}")
        # Without this the toplevel grows to whatever its widest child asks for,
        # and the right-hand buttons end up outside the visible window.
        self.pack_propagate(False)

        self._build()
        self.bind("<Escape>", lambda _e: self.on_close())

    # -- construction ----------------------------------------------------
    def _build(self):
        t = self.theme
        self.header = tk.Frame(self, bg=t.base, height=44)
        self.header.pack(fill="x", padx=PAD, pady=(PAD, 6))
        self.header.pack_propagate(False)
        drag_by(self.header, self)

        self.title_lbl = tk.Label(self.header, text="VirtualBuddy", bg=t.base,
                                  fg=t.text, font=font(t, 12, "bold"))
        self.title_lbl.pack(side="left")
        drag_by(self.title_lbl, self)

        self.mode_btn = Button(self.header, self._mode_label(), self._toggle_mode,
                               t, width=86, height=26, size=9)
        self.mode_btn.pack(side="right")
        self.avatar_btn = Button(self.header, t.label, self._cycle_avatar, t,
                                 width=64, height=26, size=9)
        self.avatar_btn.pack(side="right", padx=(0, 8))

        # input well
        self.well = tk.Frame(self, bg=t.surface_hi, highlightthickness=1,
                             highlightbackground=t.line, highlightcolor=t.accent)
        self.well.pack(fill="x", padx=PAD)
        self.prompt_mark = tk.Label(self.well, text="›", bg=t.surface_hi,
                                    fg=t.accent, font=(t.mono, 13))
        self.prompt_mark.pack(side="left", padx=(10, 4))
        self.entry = tk.Entry(self.well, bg=t.surface_hi, fg=t.text, bd=0,
                              insertbackground=t.accent, font=font(t, 11),
                              highlightthickness=0)
        self.entry.pack(side="left", fill="x", expand=True, ipady=9)
        # Enter asks; Enter again on a waiting proposal runs it, so the whole
        # manual-mode loop is keyboard-only.
        self.entry.bind("<Return>", self._on_return)
        self.send_btn = Button(self.well, "Ask", self.submit, t, primary=True,
                               width=58, height=26, size=9)
        self.send_btn.pack(side="right", padx=6, pady=6)
        self.mic_btn = Button(self.well, "Talk", self.listen, t,
                              width=52, height=26, size=9)
        self.mic_btn.pack(side="right", padx=(0, 2), pady=6)

        # proposal strip — only visible when a match is waiting on a yes
        # Buttons are packed before the label so a long skill signature can
        # never squeeze them out of the row.
        self.proposal = tk.Frame(self, bg=t.surface, highlightthickness=1,
                                 highlightbackground=t.line)
        self.run_btn = Button(self.proposal, "Run", self.run_pending, t,
                              primary=True, width=52, height=26, size=9)
        self.run_btn.pack(side="right", padx=(4, 8), pady=8)
        self.alt_btn = Button(self.proposal, "Other", self.next_match, t,
                              width=56, height=26, size=9)
        self.alt_btn.pack(side="right", padx=2, pady=8)
        self.meter = Meter(self.proposal, t, width=66)
        self.meter.pack(side="right", padx=(4, 6))

        # Fixed width with propagation off: a Tk label never shrinks below its
        # natural size, so without this a long skill signature widens the row
        # past the panel edge and shoves the buttons off-screen.
        text_col = tk.Frame(self.proposal, bg=t.surface, width=PROP_TEXT_W, height=36)
        text_col.pack_propagate(False)
        text_col.pack(side="left", fill="x", expand=True, padx=(10, 4), pady=6)
        self.prop_name = tk.Label(text_col, text="", bg=t.surface, fg=t.text,
                                  font=font(t, 10, "bold"), anchor="w")
        self.prop_name.pack(fill="x")
        self.prop_args = tk.Label(text_col, text="", bg=t.surface, fg=t.text_faint,
                                  font=(t.mono, 8), anchor="w")
        self.prop_args.pack(fill="x")
        self._prop_col = text_col

        # output
        body = tk.Frame(self, bg=t.base)
        body.pack(fill="both", expand=True, padx=PAD, pady=(10, 4))
        self.out = tk.Text(body, bg=t.base, fg=t.text_dim, bd=0, wrap="word",
                           font=font(t, 10), highlightthickness=0, padx=2, pady=2,
                           spacing1=2, spacing3=4, cursor="arrow")
        self.scroll = tk.Scrollbar(body, command=self.out.yview, width=8,
                                   troughcolor=t.base, bg=t.line, bd=0,
                                   highlightthickness=0, relief="flat")
        self.out.configure(yscrollcommand=self.scroll.set)
        self.out.pack(side="left", fill="both", expand=True)
        self.scroll.pack(side="right", fill="y")
        self._tags()
        self.show_empty()

        self.foot = tk.Label(self, text="", bg=t.base, fg=t.text_faint,
                             font=font(t, 9), anchor="w")
        self.foot.pack(fill="x", padx=PAD, pady=(0, 10))
        self.refresh_footer()

    def _tags(self):
        t = self.theme
        self.out.tag_configure("head", foreground=t.text, font=font(t, 11, "bold"),
                               spacing3=6)
        self.out.tag_configure("dim", foreground=t.text_faint)
        self.out.tag_configure("bad", foreground=t.bad)
        self.out.tag_configure("mono", font=(t.mono, 9), foreground=t.text_dim)
        self.out.tag_configure("path", font=(t.mono, 8), foreground=t.text_faint,
                               spacing3=6)

    # -- states ----------------------------------------------------------
    def show_empty(self):
        self.out.configure(state="normal")
        self.out.delete("1.0", "end")
        self.out.insert("end", "Ask for anything I have a skill for.\n\n", "head")
        for line in ("research the best budget monitors",
                     "search the web for tide times in goa",
                     "read that link and give me the gist",
                     "open chrome"):
            self.out.insert("end", f"  {line}\n", "mono")
        self.out.insert("end",
                        "\nManual mode shows the match first. Auto runs it.\n", "dim")
        self.out.configure(state="disabled")

    def show_working(self, what: str):
        self.out.configure(state="normal")
        self.out.delete("1.0", "end")
        self.out.insert("end", f"{what}\n", "head")
        self.out.insert("end", "Working. This can take a moment on slow pages.\n", "dim")
        self.out.configure(state="disabled")

    def show_result(self, res):
        self.out.configure(state="normal")
        self.out.delete("1.0", "end")
        head, _, rest = res.text.partition("\n")
        self.out.insert("end", head + "\n", "bad" if not res.ok else "head")
        if rest.strip():
            # Skills indent their tabular rows by two spaces; those columns only
            # line up in a monospaced font.
            for line in rest.strip("\n").splitlines():
                if line.startswith("    "):        # the path under an entry
                    tag = "path"
                elif line.startswith("  "):        # a data row
                    tag = "mono"
                else:
                    tag = ()
                self.out.insert("end", line + "\n", tag)
        if res.detail:
            self.out.insert("end", "\n" + res.detail + "\n", "dim")
        self.out.configure(state="disabled")
        self.out.see("1.0")

    def _show_proposal(self, turn: Turn):
        top = turn.matches[0]
        args = ", ".join(f"{k}={v}" for k, v in top.slots.items() if v)
        self.prop_name.configure(text=_ellipsis(top.skill.name.replace("_", " "), 22))
        self.prop_args.configure(text=_ellipsis(args or top.skill.description, 28))
        self.meter.set(top.score)
        self.alt_btn.set_text(f"Other ({len(turn.matches) - 1})"
                              if len(turn.matches) > 1 else "Other")
        self.proposal.pack(fill="x", padx=PAD, pady=(10, 0),
                           before=self.out.master)

    def _hide_proposal(self):
        self.proposal.pack_forget()

    # -- actions ---------------------------------------------------------
    def _on_return(self, _event):
        if not self.entry.get().strip() and self.turn and self.turn.matches \
                and self.proposal.winfo_ismapped():
            self.run_pending()
        else:
            self.submit()

    def submit(self):
        prompt = self.entry.get().strip()
        if not prompt or self._busy:
            return
        self.entry.delete(0, "end")
        self._hide_proposal()
        self.on_state("thinking")
        turn = self.agent.handle(prompt)
        self.turn = turn
        if turn.needs_confirm:
            self._show_proposal(turn)
            self.out.configure(state="normal")
            self.out.delete("1.0", "end")
            self.out.insert("end", f"“{prompt}”\n", "head")
            self.out.insert("end", "Run it, or pick another match.\n", "dim")
            self.out.configure(state="disabled")
            self.on_state("idle")
        elif turn.result:
            self.show_result(turn.result)
            self.on_state("talk")
            self.after(1600, lambda: self.on_state("idle"))

    def listen(self):
        """Push to talk: record one utterance, drop it in the box, ask."""
        from vb import voice
        if self._busy:
            return
        state = voice.status()
        if state["state"] != "ready":
            self._offer_voice_setup(state)
            return
        self._busy = True
        self.mic_btn.set_text("…")
        self.on_state("listening")

        def work():
            heard = voice.listen_once()
            self.after(0, done, heard)

        def done(heard: str):
            self._busy = False
            self.mic_btn.set_text("Talk")
            self.on_state("idle")
            if not heard:
                self.show_result(_note("Didn't catch that.",
                                       "Press Talk and speak after the sprite blinks."))
                return
            self.entry.delete(0, "end")
            self.entry.insert(0, heard)
            self.submit()

        threading.Thread(target=work, daemon=True).start()

    def _offer_voice_setup(self, state: dict):
        """Voice isn't ready — say what's missing and set it up on one click."""
        from vb import voice
        self.out.configure(state="normal")
        self.out.delete("1.0", "end")
        self.out.insert("end", "Voice needs a one-time setup\n", "head")
        self.out.insert("end", state["message"] + "\n", "dim")
        self.out.insert("end", "Setting it up now. This runs once.\n", "dim")
        self.out.configure(state="disabled")
        self._busy = True
        self.on_state("working")

        def work():
            if state["fix"] == "pip":
                voice.install_packages()
            ok = voice.download_model() is not None if voice.find_model() is None else True
            self.after(0, done, ok and voice.packages_present())

        def done(ok: bool):
            self._busy = False
            self.on_state("idle")
            self.show_result(_note(
                "Voice is ready. Press Talk." if ok else "Voice setup failed.",
                "" if ok else "Install manually: pip install vosk sounddevice"))

        threading.Thread(target=work, daemon=True).start()

    def run_pending(self, choice: int = 0):
        if not self.turn or self._busy:
            return
        self._hide_proposal()
        skill = self.turn.matches[min(choice, len(self.turn.matches) - 1)].skill
        self.show_working(skill.name.replace("_", " "))
        self.on_state("working")
        self._busy = True
        turn = self.turn

        def work():
            res = self.agent.confirm(turn, choice=choice)
            self.after(0, done, res)

        def done(res):
            self._busy = False
            self.show_result(res)
            self.on_state("talk")
            self.after(1800, lambda: self.on_state("idle"))

        threading.Thread(target=work, daemon=True).start()

    def next_match(self):
        """Cycle the proposal through the alternatives the router offered."""
        if not self.turn or len(self.turn.matches) < 2:
            return
        self.turn.matches = self.turn.matches[1:] + self.turn.matches[:1]
        self._show_proposal(self.turn)

    def _mode_label(self) -> str:
        return "Auto" if config.get("mode") == "auto" else "Manual"

    def _toggle_mode(self):
        config.set("mode", "manual" if config.get("mode") == "auto" else "auto")
        self.mode_btn.set_text(self._mode_label())
        self.refresh_footer()

    def _cycle_avatar(self):
        nxt = themes.next_after(config.get("avatar"))
        config.set("avatar", nxt)
        self.restyle(themes.get(nxt))
        self.on_avatar(nxt)

    def refresh_footer(self):
        state = llm.status()
        mode = "runs matches straight away" if config.get("mode") == "auto" \
            else "asks before running"
        self.foot.configure(text=f"{mode}  ·  {state['message']}")

    # -- theming ---------------------------------------------------------
    def restyle(self, t: Theme):
        self.theme = t
        self.configure(bg=t.base, highlightbackground=t.line)
        for frame in (self.header, self.out.master):
            frame.configure(bg=t.base)
        self.title_lbl.configure(bg=t.base, fg=t.text)
        self.well.configure(bg=t.surface_hi, highlightbackground=t.line,
                            highlightcolor=t.accent)
        self.prompt_mark.configure(bg=t.surface_hi, fg=t.accent)
        self.entry.configure(bg=t.surface_hi, fg=t.text, insertbackground=t.accent)
        self.proposal.configure(bg=t.surface, highlightbackground=t.line)
        self._prop_col.configure(bg=t.surface)
        self.prop_name.configure(bg=t.surface, fg=t.text)
        self.prop_args.configure(bg=t.surface, fg=t.text_faint)
        self.out.configure(bg=t.base, fg=t.text_dim)
        self.scroll.configure(troughcolor=t.base, bg=t.line)
        self.foot.configure(bg=t.base, fg=t.text_faint)
        self.avatar_btn.set_text(t.label)
        for w in (self.mode_btn, self.avatar_btn, self.send_btn, self.mic_btn,
                  self.run_btn, self.alt_btn):
            w.restyle(t)
        self.meter.restyle(t)
        self._tags()

    # -- window ----------------------------------------------------------
    def show_at(self, x: int, y: int):
        self.geometry(f"{W}x{H}+{x}+{y}")
        self.deiconify()
        self.lift()
        self.entry.focus_force()

    def hide(self):
        self.withdraw()
