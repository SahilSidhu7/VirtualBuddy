"""Skill entry for teaching buddy facts. Real logic lives in buddy/learning/learn.py.

This thin file is what the skill loader scans; it just re-exports the contract.
"""
from buddy.learning.learn import SKILLS  # noqa: F401
