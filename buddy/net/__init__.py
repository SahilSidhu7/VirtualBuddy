"""Brain channel — how the laptop and phone share ONE brain + ONE memory.

  brain_server.py : run on the 1050ti (role: server). Exposes recall/route/act/learn over HTTP.
  brain_client.py : run on laptop/phone (role: client). Sends commands to that brain.

Distinct from buddy/server.py, which relays *peer* commands between PCs. This channel
is specifically about a shared brain so every device learns from the same memory.
Token-gated over the LAN (reuses server_token).
"""
