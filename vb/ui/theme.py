"""One palette per avatar, one theme for the whole app.

Each avatar owns an accent and a base tuned to its temperature; everything else
(surface steps, text ramp, radius, type) is shared, so switching avatar re-skins
the app without any section of it disagreeing with another.
"""
from __future__ import annotations

from dataclasses import dataclass

RADIUS = 14          # one corner scale, everywhere
RADIUS_SM = 8


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    accent: str          # the single accent; used for focus, confidence, primary action
    accent_dim: str
    base: str            # window background
    surface: str         # card background
    surface_hi: str      # raised row / input well
    line: str            # hairline
    text: str
    text_dim: str
    text_faint: str
    good: str
    bad: str

    @property
    def font(self) -> str:
        return "Segoe UI Variable Text"

    @property
    def font_fallback(self) -> str:
        return "Segoe UI"

    @property
    def mono(self) -> str:
        return "Cascadia Mono"


DUCK = Theme(
    key="duck", label="Duck",
    accent="#F0B429", accent_dim="#8A6714",
    base="#151310", surface="#1D1A15", surface_hi="#262118",
    line="#332C21", text="#F3EDE2", text_dim="#B4AA98", text_faint="#78705F",
    good="#7FB069", bad="#E06C5A",
)

ELF = Theme(
    key="elf", label="Elf",
    accent="#3FBF87", accent_dim="#1E6448",
    base="#101613", surface="#161F1B", surface_hi="#1D2924",
    line="#24332C", text="#E6F0EA", text_dim="#9DB0A6", text_faint="#66786E",
    good="#3FBF87", bad="#E06C5A",
)

CRAB = Theme(
    key="crab", label="Crab",
    accent="#FF6B4A", accent_dim="#8C3320",
    base="#17110F", surface="#211815", surface_hi="#2B201B",
    line="#382823", text="#F5E9E4", text_dim="#BCA79F", text_faint="#7E6A63",
    good="#7FB069", bad="#FF6B4A",
)

THEMES = {t.key: t for t in (DUCK, ELF, CRAB)}
ORDER = ["duck", "elf", "crab"]


def get(key: str) -> Theme:
    return THEMES.get(key, DUCK)


def next_after(key: str) -> str:
    return ORDER[(ORDER.index(key) + 1) % len(ORDER)] if key in ORDER else ORDER[0]
