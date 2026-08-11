"""Ties it together: text in -> pick skill -> run -> reply out.

Fallback order (cheapest first, saves Claude tokens):
  1. matched skill                 (classifier is confident - instant, no LLM)
  2. local LLM with tools          (buddy picks + runs skills itself, or answers)
  3. looks like a question -> web   (free)
  4. Claude CLI                    (last resort)

Power-saving mode skips the LLM entirely and frees its RAM.
"""
import threading

from buddy import brain, voice, llm, tools_llm, planner, skill_writer, confirm, peers as peer_book
from buddy.skills.web import search as web_search
from buddy.skills.claude_ctl import ask_claude
from buddy.skills.remote import remote as remote_relay
from buddy.memory.memory import Memory
from buddy.memory.graph import CommandGraph
from buddy.learning import feedback
from buddy.skills import all_skills as _all_skills

_RELAY_WORDS = ("on ", "tell ", "send ", "run on ", "@")

_Q_STARTS = ("who", "what", "when", "where", "why", "how", "which",
             "is", "are", "does", "do", "can", "tell me")

def _looks_like_question(t):
    t = t.lower().strip()
    return t.endswith("?") or t.startswith(_Q_STARTS)

class Agent:
    def __init__(self, cfg):
        self.cfg = cfg
        self.mem = Memory(cfg)
        self.cmdgraph = CommandGraph(cfg)          # learned command -> skill memory
        self.ctx = {"cfg": cfg, "mem": self.mem, "graph": self.cmdgraph}
        self.last = None
        self.on_state = None        # optional sink (e.g. the character) for animation states
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

    def _emit(self, state):
        if self.on_state:
            try:
                self.on_state(state)
            except Exception:
                pass

    # ---- main ----
    def handle(self, text):
        text = (text or "").strip()
        if not text:
            return ""
        # is this a yes/no answer to a Claude-drafted skill awaiting approval?
        if skill_writer.Pending.active() and skill_writer.is_verdict(text):
            reply = skill_writer.confirm(text, self.ctx, on_done=self.reload_brain)
            if reply is not None:
                voice.say(reply, self.cfg["speak_replies"])
                return reply
        # is this a yes/no answer to a risky action a skill is holding? (shutdown, etc.)
        if confirm.Pending.active() and confirm.is_verdict(text):
            reply = confirm.resolve(text)
            if reply is not None:
                voice.say(reply, self.cfg["speak_replies"])
                return reply
        # is this a yes/no answer to a pending plan buddy asked to confirm?
        if planner.Pending.active() and planner.is_verdict(text):
            reply = planner.confirm(text, self.ctx)
            if reply is not None:
                voice.say(reply, self.cfg["speak_replies"])
                return reply
        # is this a yes/no answer to buddy's "did I do that right?" question?
        if feedback.Pending.active() and feedback.is_verdict(text):
            reply = feedback.record_verdict(text, self.cfg, graph=self.cmdgraph)
            if reply:
                voice.say(reply, self.cfg["speak_replies"])
                return reply
        if self._is_remote(text):                       # peer command -> relay, don't run locally
            self.last = (text, "remote")
            reply = remote_relay(text, self.ctx)
            voice.say(reply, self.cfg["speak_replies"])
            return reply

        # 1) has buddy already made a similar command work? just do that skill again.
        skill = self._skill_from_memory(text)
        source = "memory"
        if skill is None:                               # 2) otherwise route with the classifier
            skill, _ = brain.route(text, self.cfg["match_threshold"])
            source = "classifier"
            skill = self._guard_remote(skill, text)     # never let a local command hit 'remote'

        if skill is not None:
            self.last = (text, skill["name"])
            self._emit("working")                       # a known task is running
            reply = skill["run"](text, self.ctx)
            # remembering is a write nobody waits on — keep it off the reply path
            self._remember_async(text, skill["name"])
            if source == "classifier":                  # only quiz on fresh (unlearned) routes
                reply = self._maybe_confirm(skill["name"], text, reply)
        else:
            self.last = (text, None)
            reply = self._fallback(text)
        voice.say(reply, self.cfg["speak_replies"])
        return reply

    def _remember_async(self, text, skill_name):
        """Log the episode and reinforce command -> skill in the background.

        These used to run inline; with an embedding-backed store that added
        seconds to every single reply.
        """
        def work():
            try:
                self.mem.note_episode(f"'{text}' -> {skill_name}")
            except Exception:
                pass
            try:
                self.cmdgraph.record(text, skill_name, ok=True)   # learn from doing
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _skill_from_memory(self, text):
        """If the command graph confidently knows this command, return its skill."""
        name, _score = self.cmdgraph.recall(text)
        if not name:
            return None
        return brain._skill_by_name.get(name) or next(
            (s for s in _all_skills() if s["name"] == name), None)

    def _guard_remote(self, skill, text):
        """The 'remote' skill only applies when the text actually targets a peer.
        Guards against a misroute turning 'open chrome' into 'No peers set'."""
        if skill is not None and skill["name"] == "remote" and not self._is_remote(text):
            return None
        return skill

    def _maybe_confirm(self, skill_name, text, reply):
        """First few times a skill runs, ask the user whether buddy got it right."""
        if feedback.should_confirm(skill_name, self.cfg):
            feedback.Pending.set(text, skill_name)
            return f"{reply}\n{feedback.ask_line(skill_name)}"
        return reply

    def _is_remote(self, text):
        low = text.lower()
        if not any(w in low for w in _RELAY_WORDS):     # "on/tell/send ..." required
            return False
        if peer_book.mentions_peer(self.cfg, text):     # named a peer or one of its nicknames
            return True
        generic = any(g in low for g in ("other pc", "other computer", "my server", "the server"))
        return generic and peer_book.default_peer(self.cfg) is not None

    def _fallback(self, text):
        self._emit("thinking")                        # working out what to do
        is_q = _looks_like_question(text)
        cfg = self.cfg
        # 1) local planner composes primitives for an action (free)
        if self._llm_up and not is_q:
            try:
                reply = planner.run(text, self.ctx)
                if reply is not None:
                    return reply
            except Exception:
                pass
        # 2) action buddy still can't do + user opted in -> Claude AUTHORS a new skill
        if not is_q and cfg.get("use_claude") and cfg.get("claude_writes_skills"):
            try:
                from buddy import skill_writer
                reply = skill_writer.try_author(text, self.ctx, on_done=self.reload_brain)
                if reply is not None:
                    return reply
            except Exception:
                pass
        # 3) local LLM answers or calls an existing skill (free)
        if self._llm_up:
            try:
                reply = self._llm_tools(text)
                if reply:
                    return reply
            except Exception:
                pass
        # 4) knowledge question -> free web search
        if is_q:
            return web_search(text, self.ctx)
        # 5) Claude as a plain answer, if the user opted in
        if cfg.get("use_claude"):
            return ask_claude(text, self.ctx)
        return ("I can't do that one yet. Turn on Claude in the dashboard "
                "and I can learn new skills for it.")

    def _llm_tools(self, text):
        """Let the LLM answer or call one/many skills itself, with relevant memories in context."""
        system = llm.SYSTEM
        recalled = self.mem.recall_block(text)          # human-like recall: top-k relevant memories
        if recalled:
            system = f"{system}\n\n{recalled}"
        msg = llm.chat([{"role": "system", "content": system},
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


def make_brain(cfg):
    """Return the right brain for this device's role:
      client   -> talk to the shared brain on the server (falls back to local if unreachable)
      server / standalone -> a local Agent.
    Both expose .handle(text), so callers (run.py, vb.py, UI) don't care which they got.
    """
    if cfg.get("role") == "client" and cfg.get("brain_host"):
        from buddy.net.brain_client import BrainClient
        client = BrainClient(cfg)
        if client.available():
            print(f"[agent] client role: using remote brain at {cfg['brain_host']}")
            return client
        print("[agent] client role: remote brain unreachable, running locally.")
    return Agent(cfg)
