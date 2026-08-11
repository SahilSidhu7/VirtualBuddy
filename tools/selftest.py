"""Check buddy still understands the everyday commands.

Route-only on purpose: this asks the brain "which skill would you run?" and never
runs it. An automated test that actually executed skills would lock the screen or
shut the machine down — that happened once, hence this rule.

    python -m tools.selftest
"""
import sys

from buddy import brain
from buddy.settings import load

# (command, expected skill) — phrased the way people really talk, not the way
# the training phrases are written.
CASES = [
    # launching things
    ("open chrome for me", "open_app"),
    ("can you launch notepad", "open_app"),
    ("start spotify please", "open_app"),
    ("fire up vs code", "open_app"),
    # browser
    ("search youtube for lofi hip hop", "browser_search"),
    ("google the best pizza in town", "browser_search"),
    ("play some jazz on youtube", "browser_search"),
    ("look up mechanical keyboards on amazon", "browser_search"),
    ("open youtube", "open_shortcut"),
    ("take me to gmail", "open_shortcut"),
    ("go to github.com", "open_site"),
    ("summarise this page for me", "read_page"),
    # looking things up
    ("who is the prime minister of india", "web_search"),
    ("what's the weather in delhi", "weather"),
    # what's happening on my pc
    ("what is happening on my pc", "pc_activity"),
    ("whats going on with my computer right now", "pc_activity"),
    ("what is using all my cpu", "top_processes"),
    ("what's eating my ram", "top_processes"),
    ("what apps do i have open", "whats_open"),
    ("how much space is left on my drive", "disk_space"),
    ("am i online", "network_status"),
    ("how long has my pc been running", "uptime"),
    ("check my battery", "status"),
    # windows
    ("close chrome", "close_app"),
    ("switch to my browser", "focus_app"),
    ("show me the desktop", "minimize_all"),
    # sound
    ("turn the volume up", "volume"),
    ("mute it", "volume"),
    ("pause the music", "media"),
    ("skip this track", "media"),
    # files
    ("open my downloads folder", "open_folder"),
    ("where is my resume pdf", "find_files"),
    ("what did i just download", "recent_downloads"),
    # timers
    ("set a timer for 5 minutes", "set_timer"),
    ("remind me in 20 minutes to stretch", "set_timer"),
    ("cancel the timer", "cancel_timer"),
    # clipboard
    ("what's on my clipboard", "read_clipboard"),
    # power + basics
    ("shut down my pc", "power"),
    ("put my pc to sleep", "power"),
    ("lock my screen", "lock"),
    ("take a screenshot", "screenshot"),
    ("what time is it", "time"),
]


def main():
    cfg = load()
    brain.build(cfg)
    threshold = cfg["match_threshold"]
    misses = []
    for text, want in CASES:
        skill, score = brain.route(text, threshold)
        got = skill["name"] if skill else None
        if got != want:
            misses.append((text, want, got, score))
    passed = len(CASES) - len(misses)
    print(f"{passed}/{len(CASES)} commands routed correctly "
          f"({100 * passed / len(CASES):.0f}%)")
    for text, want, got, score in misses:
        print(f"  MISS {text!r}: wanted {want}, got {got} ({score:.2f})")
    if misses:
        print("\nRetrain with:  python -m tools.loop")
    return 1 if misses else 0


if __name__ == "__main__":
    sys.exit(main())
