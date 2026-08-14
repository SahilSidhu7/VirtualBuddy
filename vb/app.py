"""Desktop entry point: `python -m vb.app` (or run.py).

A hidden root Tk window owns two frameless toplevels — the sprite and the
panel — so closing the panel never kills the buddy.
"""
from __future__ import annotations

import threading
import tkinter as tk

from vb import config, llm, startup
from vb.agent import Agent
from vb.registry import load_all
from vb.ui import theme as themes
from vb.ui.panel import Panel
from vb.ui.pet import Pet


def _note(text: str, detail: str = ""):
    from vb.registry import Result
    return Result(text=text, detail=detail)


class App:
    def __init__(self, root: tk.Tk | None = None):
        self.root = root or tk.Tk()
        self.root.withdraw()
        self.root.title("VirtualBuddy")

        load_all()
        self.agent = Agent()

        self.pet = Pet(self.root, on_click=self.toggle_panel, on_menu=self.menu)
        self.panel = Panel(self.root, self.agent, on_state=self.pet.set_state,
                           on_avatar=self.change_avatar, on_close=self.hide_panel)
        self.panel.withdraw()
        self.visible = False

    # -- panel -----------------------------------------------------------
    def toggle_panel(self):
        if self.visible:
            self.hide_panel()
        else:
            self.panel.show_at(*self.pet.anchor())
            self.panel.refresh_footer()
            self.visible = True

    def hide_panel(self):
        self.panel.hide()
        self.visible = False

    def change_avatar(self, avatar: str):
        self.pet.set_avatar(avatar)

    # -- menu ------------------------------------------------------------
    def menu(self, event):
        t = themes.get(config.get("avatar"))
        m = tk.Menu(self.root, tearoff=0, bg=t.surface, fg=t.text,
                    activebackground=t.accent, activeforeground=t.base,
                    bd=0, font=(t.font, 9))
        m.add_command(label="Open panel", command=self.toggle_panel)
        mode = config.get("mode")
        m.add_command(label=f"Mode: {mode}  (switch)",
                      command=self.panel._toggle_mode)
        m.add_separator()
        for key in themes.ORDER:
            label = ("● " if key == config.get("avatar") else "   ") + themes.get(key).label
            m.add_command(label=label, command=lambda k=key: self.pick_avatar(k))
        m.add_separator()
        if startup.supported():
            on = startup.enabled()
            m.add_command(label=("● " if on else "   ") + "Start with Windows",
                          command=self.toggle_startup)
        state = llm.status()
        if state["state"] == "no_model":
            m.add_command(label=f"Download {config.get('llm_model')} for smart mode",
                          command=self.pull_model)
        else:
            m.add_command(label=state["message"], state="disabled")
        m.add_separator()
        m.add_command(label="Quit", command=self.quit)
        m.tk_popup(event.x_root, event.y_root)

    def pick_avatar(self, key: str):
        config.set("avatar", key)
        self.pet.set_avatar(key)
        self.panel.restyle(themes.get(key))

    def toggle_startup(self):
        ok, message = startup.toggle()
        self.panel.show_at(*self.pet.anchor())
        self.visible = True
        self.panel.show_result(_note(message if ok else "Couldn't change that.",
                                     "" if ok else message))

    def pull_model(self):
        """Download the model in the background; the sprite shows it's busy."""
        self.pet.set_state("working")

        def done(ok: bool):
            self.pet.set_state("idle")
            self.panel.refresh_footer()
            if not ok:
                self.panel.show_at(*self.pet.anchor())
                self.visible = True

        threading.Thread(
            target=lambda: self.root.after(0, done, llm.pull()), daemon=True).start()

    # -- lifecycle -------------------------------------------------------
    def quit(self):
        self.root.quit()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main() -> int:
    """Get the model ready behind a progress bar, then bring the buddy out."""
    from vb.ui.splash import Splash

    root = tk.Tk()
    root.withdraw()
    holder: dict[str, App] = {}

    def start(model_ready: bool = True):
        app = App(root)
        holder["app"] = app
        if not model_ready:
            app.panel.show_at(*app.pet.anchor())
            app.visible = True
            app.panel.show_result(_note(
                "Running without a model.",
                "Web answers will be raw page text until one is set up. "
                "Right click me to try again."))

    if llm.enabled() and config.get("skip_splash"):
        start()
    else:
        Splash(root, on_done=start, on_skip=lambda: start(False))

    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
