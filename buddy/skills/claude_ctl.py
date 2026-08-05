"""Control Claude. Also the fallback brain for anything the small skills miss.

Uses the Claude CLI in print mode: `claude -p "..."`.
"""
import subprocess

def ask_claude(text, ctx):
    cli = ctx["cfg"]["claude_cli"]
    prompt = text
    for w in ("ask claude", "claude", "hey claude"):
        prompt = prompt.replace(w, "").strip()
    prompt = prompt or text
    try:
        r = subprocess.run([cli, "-p", prompt], capture_output=True, text=True, timeout=180)
        out = (r.stdout or r.stderr or "").strip()
        return out[:1500] if out else "Claude gave no reply."
    except FileNotFoundError:
        return f"Claude CLI '{cli}' not found. Check config.yaml."
    except Exception as e:
        return f"Claude error: {e}"

SKILLS = [
    {"name": "ask_claude",
     "phrases": ["ask claude", "tell claude to", "have claude write", "get claude to fix",
                 "run a claude agent", "tell the ai to write code", "refactor my code",
                 "write a program that", "answer this question"],
     "run": ask_claude},
]
