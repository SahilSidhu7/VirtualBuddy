"""Continuous learning — what turns buddy from a tool into an employee.

  learn.py     - "learn X": look it up on the web, distil it, remember it.
  feedback.py  - after acting, ask "did I do that right?" the first few times; log lessons.
  teach.py     - once lessons pile up, fine-tune the brain (QLoRA) on the server GPU.

learn/feedback run anywhere (light). teach runs only on the server role (heavy stack).
"""
