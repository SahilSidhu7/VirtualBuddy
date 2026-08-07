"""The hands — one guarded seam for acting on the machine.

Every action buddy takes on the world (run a skill, call a tool) goes through
executor.run(). That gives one place to log what happened (episodic memory) and,
later, one place to enforce guardrails/confirmation for risky actions.
"""
from buddy.actions.executor import run_skill, run_tool  # noqa: F401
