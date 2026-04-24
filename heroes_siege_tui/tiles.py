"""Adventure-map tile rendering + per-terrain palette.

The adventure map is a 1-cell tile grid (not hex). We draw each tile as
one character with a 2-glyph pattern keyed on `(x + y) & 1` so grass
doesn't read as a wall of dots.
"""

from __future__ import annotations


TERRAIN_VISUAL: dict[str, dict] = {
    "grass":    {"glyphs": (".", ","), "fg": "80,140,70",  "bg": "14,20,14"},
    "dirt":     {"glyphs": (":", "."), "fg": "150,110,80", "bg": "24,20,14"},
    "sand":     {"glyphs": (".", ":"), "fg": "200,180,120","bg": "36,30,18"},
    "road":     {"glyphs": ("-", "="), "fg": "210,200,170","bg": "24,22,18"},
    "water":    {"glyphs": ("~", "≈"), "fg": "100,150,220","bg": "14,22,44"},
    "tree":     {"glyphs": ("♣", "^"), "fg": "70,140,70",  "bg": "10,24,12"},
    "mountain": {"glyphs": ("▲", "^"), "fg": "150,140,120","bg": "22,20,16"},
    "rock":     {"glyphs": ("#", "%"), "fg": "130,130,130","bg": "18,18,20"},
    "snow":     {"glyphs": (".", "*"), "fg": "220,220,240","bg": "40,40,50"},
    "unknown":  {"glyphs": ("?", "?"), "fg": "255,0,255",  "bg": "0,0,0"},
}


OBJECT_GLYPH: dict[str, tuple[str, str]] = {
    "mine_ore":  ("⛏", "200,150,90"),
    "mine_wood": ("♠", "170,130,80"),
    "gold_pile": ("$", "240,220,100"),
    "chest":     ("◘", "220,200,90"),
    "monster":   ("☠", "240,100,100"),
    "town":      ("⌂", "240,230,120"),
    "hero":      ("@", "240,240,240"),
}


# Faction hero/town marker colour — keyed by player index.
FACTION_COLOR: dict[int, str] = {
    0: "240,90,90",
    1: "120,140,240",
    -1: "180,180,180",
}


def terrain_style(terrain: str) -> dict:
    return TERRAIN_VISUAL.get(terrain, TERRAIN_VISUAL["unknown"])


def terrain_glyph(terrain: str, x: int, y: int) -> str:
    v = terrain_style(terrain)
    pair = v["glyphs"]
    return pair[(x + y) & 1]


def obj_glyph(kind: str) -> tuple[str, str]:
    return OBJECT_GLYPH.get(kind, ("?", "255,0,255"))
