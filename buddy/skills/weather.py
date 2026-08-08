"""Weather for a city using the free wttr.in service (no key)."""
import json, urllib.request, urllib.parse
from buddy import slots

_STOP = ("weather", "whats", "what's", "what is", "the", "in", "for",
         "is", "it", "raining", "today", "outside", "like", "how", "hot",
         "cold", "temperature")

def _city(text):
    t = slots.clean(text).lower()
    words = [w for w in t.split() if w not in _STOP]
    return " ".join(words) or "here"

def weather(text, ctx):
    city = _city(text)
    url = "https://wttr.in/" + urllib.parse.quote(city) + "?format=j1"
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.load(r)
        cur = data["current_condition"][0]
        desc = cur["weatherDesc"][0]["value"]
        return f"{city.title()}: {cur['temp_C']}Â°C, {desc}."
    except Exception as e:
        return f"Couldn't get weather for {city}: {e}"

SKILLS = [
    {"name": "weather", "desc": "current weather for a city",
     "phrases": ["what's the weather in delhi", "whats the weather in delhi",
                 "weather in London", "is it raining today",
                 "what's the temperature outside", "how hot is it in Delhi",
                 "weather forecast for Mumbai"],
     "run": weather},
]