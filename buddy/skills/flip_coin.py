"""Flip a coin â€” simple stdlib random choice."""
import random

def flip_coin(text, ctx):
    try:
        result = random.choice(["Heads", "Tails"])
        return f"{result}!"
    except Exception as e:
        return f"Couldn't flip coin: {e}"

SKILLS = [
    {"name": "flip_coin", "desc": "flip a coin, heads or tails",
     "phrases": ["flip a coin", "flip coin", "toss a coin", "heads or tails",
                 "coin flip", "flip a coin for me", "can you flip a coin"],
     "run": flip_coin},
]