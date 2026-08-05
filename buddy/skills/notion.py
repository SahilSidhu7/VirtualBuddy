"""Save an idea/note to Notion. No tokens (Notion's own API, not Claude).

One-time setup (free):
  1. notion.so/my-integrations -> New integration -> copy the secret.
  2. Make a Notion database (e.g. "Ideas") with a Title property.
  3. Share that database with your integration (••• -> Connections).
  4. Put in config.yaml:
        notion_token: "secret_xxx"
        notion_db: "<database id from its URL>"
"""
import json, re, urllib.request

def _save_idea(text, ctx):
    cfg = ctx["cfg"]
    token, db = cfg.get("notion_token"), cfg.get("notion_db")
    if not token or not db:
        return ("Notion not set up. Add notion_token + notion_db to config.yaml "
                "(see buddy/skills/notion.py for steps).")
    # strip the command part, keep the idea
    idea = re.sub(r"^.*?(idea|note|remember|save)\b[:\-]?", "", text, flags=re.I).strip()
    idea = idea or text
    body = json.dumps({
        "parent": {"database_id": db},
        "properties": {"Name": {"title": [{"text": {"content": idea[:200]}}]}},
    }).encode()
    req = urllib.request.Request("https://api.notion.com/v1/pages", data=body, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    })
    try:
        urllib.request.urlopen(req, timeout=15).read()
        return f"Saved to Notion: {idea[:80]}"
    except urllib.error.HTTPError as e:
        return f"Notion error {e.code}: {e.read().decode()[:150]}"
    except Exception as e:
        return f"Notion failed: {e}"

SKILLS = [
    {"name": "notion_idea", "desc": "save an idea or note to Notion",
     "phrases": ["save this idea to notion", "note this in notion", "remember this idea",
                 "add to my notion", "store this note", "jot down an idea"],
     "run": _save_idea},
]
