"""Where buddy can send a command — the other machines it knows.

A peer has a name, a URL, and optional nicknames (aliases). Buddy figures out
which machine you mean from the words you use ("on the laptop ...", "tell gaming-pc
..."), and if you don't name one it uses your default peer.

config.yaml shape (both forms accepted, so old configs keep working):
  default_peer: laptop
  peers:
    laptop: "http://192.168.1.55:8770"                       # short form
    gaming-pc:                                                # full form (with nicknames)
      url: "http://192.168.1.42:8770"
      aliases: ["big pc", "the rig"]
"""

def normalize(cfg):
    """Return {name: {"url": str, "aliases": [str, ...]}} from either config form."""
    out = {}
    for name, val in (cfg.get("peers") or {}).items():
        if isinstance(val, dict):
            url = val.get("url", "")
            aliases = [str(a).strip().lower() for a in (val.get("aliases") or []) if str(a).strip()]
        else:
            url, aliases = str(val), []
        out[name] = {"url": url, "aliases": aliases}
    return out


def names(cfg):
    """Every handle buddy answers to per peer: {matchable_name: peer_name}."""
    idx = {}
    for name, p in normalize(cfg).items():
        idx[name.lower()] = name
        for a in p["aliases"]:
            idx[a] = name
    return idx


def default_peer(cfg):
    """The peer used when a remote command names no machine. Falls back to the
    only peer if there's exactly one, else None."""
    peers = normalize(cfg)
    d = cfg.get("default_peer")
    if d and d in peers:
        return d
    if len(peers) == 1:
        return next(iter(peers))
    return None


def resolve(cfg, text):
    """(peer_name, url) for the machine this text targets, else (None, None).
    Prefers an explicitly named peer/alias; otherwise the default peer."""
    peers = normalize(cfg)
    low = (text or "").lower()
    # longest handle first so "gaming pc" beats "pc"
    for handle in sorted(names(cfg), key=len, reverse=True):
        if handle in low:
            name = names(cfg)[handle]
            return name, peers[name]["url"]
    d = default_peer(cfg)
    if d:
        return d, peers[d]["url"]
    return None, None


def mentions_peer(cfg, text):
    """True if the text explicitly names a known peer or alias."""
    low = (text or "").lower()
    return any(handle in low for handle in names(cfg))
