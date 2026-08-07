"""Executor — the single place skills/tools actually run.

Why funnel through here instead of calling skill['run'] directly? So there's ONE
seam to (a) log every action to episodic memory, and (b) later gate risky actions
behind confirmation. The agent can migrate to these helpers incrementally; nothing
forces it yet.
"""
from buddy.memory import memory as mem


def run_skill(skill, text, ctx):
    """Run a matched skill, recording the episode."""
    cfg = ctx.get("cfg", {})
    try:
        reply = skill["run"](text, ctx)
    except Exception as e:
        mem.get(cfg).note_episode(f"'{text}' -> {skill.get('name')} FAILED: {e}")
        raise
    mem.get(cfg).note_episode(f"'{text}' -> {skill.get('name')}")
    return reply


def run_tool(name, args, ctx, text=""):
    """Run an LLM-selected tool by name, recording the episode."""
    cfg = ctx.get("cfg", {})
    from buddy import tools_llm
    reply = tools_llm.dispatch(name, args, ctx, text)
    mem.get(cfg).note_episode(f"'{text or name}' -> tool:{name}")
    return reply
