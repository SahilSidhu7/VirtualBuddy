"""Turns buddy's skills into tools the local LLM can call itself.

The LLM picks which skill(s) to run and passes the relevant phrasing; our
slots then extract exact details. This handles novel + compound commands
("screenshot then lock in 5 min") the classifier alone would miss.
"""
from buddy.skills import all_skills

_SKIP = {"ask_claude"}   # never let the local LLM spend Claude tokens

def _desc(s):
    return s.get("desc") or f"{s['name'].replace('_', ' ')} (e.g. '{s['phrases'][0]}')"

def build_tools():
    """OpenAI/Ollama-style tool schemas, one per skill."""
    tools = []
    for s in all_skills():
        if s["name"] in _SKIP:
            continue
        tools.append({
            "type": "function",
            "function": {
                "name": s["name"],
                "description": _desc(s),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "the user's request for this action, in plain words",
                        }
                    },
                    "required": ["command"],
                },
            },
        })
    return tools

def dispatch(name, args, ctx, original):
    """Run the skill the LLM chose. Falls back to the original text if no command arg."""
    skill = next((s for s in all_skills() if s["name"] == name), None)
    if not skill:
        return f"(unknown tool {name})"
    text = (args or {}).get("command") or original
    return skill["run"](text, ctx)
