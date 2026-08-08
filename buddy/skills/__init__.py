"""Collects every skill. To add a skill: drop a new file here that
defines SKILLS = [ {name, phrases, run} , ... ].
"""
import importlib, pkgutil

_cache = None

def all_skills():
    global _cache
    if _cache is not None:
        return _cache
    skills = []
    for mod in pkgutil.iter_modules(__path__):
        if mod.name.startswith("_"):
            continue
        m = importlib.import_module(f"{__name__}.{mod.name}")
        skills.extend(getattr(m, "SKILLS", []))
    _cache = skills
    return skills

def reload():
    """Forget the cache so a newly-installed skill file is picked up."""
    global _cache
    _cache = None
    return all_skills()
