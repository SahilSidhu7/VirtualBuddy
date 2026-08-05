"""Ties it together: text in -> pick skill -> run -> reply out.

Fallback order (cheapest first, saves Claude tokens):
  1. matched skill                 (classifier is confident - instant, no LLM)
  2. local LLM with tools          (buddy picks + runs skills itself, or answers)
  3. looks like a question -> web   (free)
  4. Claude CLI                    (last resort)

Power-saving mode skips the LLM entirely and frees its RAM.
"""
from buddy import brain, voice, llm, tools_llm
from buddy.skills.web import search as web_search
from buddy.skills.claude_ctl import ask_claude
from buddy.skills.remote import remote as remote_relay

_RELAY_WORDS = ("on ", "tell ", "send ", "run on ", "@")

_Q_STARTS = ("who", "what", "when", "where", "why", "how", "which",
             "is", "are", "does", "do", "can", "tell me")

def _looks_like_question(t):
    t = t.lower().strip()
    return t.endswith("?") or t.startswith(_Q_STARTS)

class Agent:
    def __init__(self, cfg):
        self.cfg = cfg
        self.ctx = {"cfg": cfg}
        self.last = None
        brain.build(cfg)
        from buddy import settings, trainer
        if settings.is_first_run():                       # auto-train once, in background
            print("[agent] first run: training brain in background...")
            trainer.train_async(on_done=self.reload_brain)
        self.power_save = bool(cfg.get("power_save"))
        self._tools = tools_llm.build_tools()
        self._llm_up = (not self.power_save) and cfg.get("llm_enabled") and llm.is_up(cfg)
        if self._llm_up:
            print(f"[agent] local brain ready ({cfg['llm_model']}), tool-calling on.")
        elif self.power_save:
            print("[agent] power-saving mode - LLM off.")

    # ---- power saving ----
    def set_power_save(self, on):
        self.power_save = on
        if on:
            llm.unload(self.cfg)                 # free RAM
            self._llm_up = False
            return "Power-saving on - LLM off, memory freed."
        self._llm_up = self.cfg.get("llm_enabled") and llm.is_up(self.cfg)
        return "Power-saving off - LLM back on." if self._llm_up else "LLM not reachable."

    def reload_brain(self):
        brain.reload(self.cfg)

    # ---- main ----
    def handle(self, text):
        text = (text or "").strip()
        if not text:
            return ""
        if self._is_remote(text):                       # peer command -> relay, don't run locally
            self.last = (text, "remote")
            reply = remote_relay(text, self.ctx)
            voice.say(reply, self.cfg["speak_replies"])
            return reply
        skill, score = brain.route(text, self.cfg["match_threshold"])
        if skill is not None:
            self.last = (text, skill["name"])
            reply = skill["run"](text, self.ctx)
        else:
            self.last = (text, None)
            reply = self._fallback(text)
        voice.say(reply, self.cfg["speak_replies"])
        return reply

    def _is_remote(self, text):
        peers = self.cfg.get("peers") or {}
        low = text.lower()
        return (any(p.lower() in low for p in peers)
                and any(w in low for w in _RELAY_WORDS))

    def _fallback(self, text):
        if self._llm_up:
            try:
                return self._llm_tools(text)
            except Exception:
                pass
        if _looks_like_question(text):
            return web_search(text, self.ctx)
        return ask_claude(text, self.ctx)

    def _llm_tools(self, text):
        """Let the LLM answer or call one/many skills itself."""
        msg = llm.chat([{"role": "system", "content": llm.SYSTEM},
                        {"role": "user", "content": text}], self.cfg, tools=self._tools)
        calls = msg.get("tool_calls") or []
        if not calls:
            return msg.get("content", "").strip() or "..."
        results = []
        for c in calls:
            fn = c.get("function", {})
            args = fn.get("arguments")
            if isinstance(args, str):
                import json
                try: args = json.loads(args)
                except Exception: args = {}
            results.append(tools_llm.dispatch(fn.get("name"), args, self.ctx, text))
        return " ".join(r for r in results if r)
