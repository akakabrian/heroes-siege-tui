"""Creature catalogue + building costs + faction palette.

Clean-room — values inspired by HoMM2's shape (tier progression, ranged
for upper tiers, weekly growth) but chosen afresh, not copied. See
DECISIONS.md §2.

Creature tiers 1-4 per faction:
- Knight:     Peasant, Archer, Pikeman, Cavalry
- Necromancer: Skeleton, Zombie, Mummy, Vampire

Stats follow the traditional HoMM2 shape: low-tier lots-of-cheap, high-
tier few-expensive, one ranged unit per faction, one flying/fast unit.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------- creatures ---------------------------------------------------

@dataclass(frozen=True)
class Creature:
    """Data for one creature *type*. Stacks in the game reference this by
    name; counts live on the stack."""
    name: str
    faction: str        # "knight" | "necromancer"
    tier: int           # 1..4
    glyph: str          # single char for combat hex + army list
    attack: int
    defense: int
    damage_min: int
    damage_max: int
    hp: int             # per creature
    speed: int          # hex/round on combat grid
    shots: int = 0      # 0 = melee only, >0 = ranged
    flies: bool = False
    cost_gold: int = 0
    cost_ore: int = 0
    cost_wood: int = 0
    weekly_growth: int = 0   # how many appear in dwelling per week


KNIGHT: list[Creature] = [
    Creature("Peasant",  "knight", 1, "p", 1, 1, 1, 1, 1, 3, cost_gold=20,  weekly_growth=12),
    Creature("Archer",   "knight", 2, "a", 5, 3, 2, 3, 10, 4, shots=12,     cost_gold=150, cost_wood=1, weekly_growth=8),
    Creature("Pikeman",  "knight", 3, "P", 5, 9, 3, 4, 15, 4,               cost_gold=200, weekly_growth=5),
    Creature("Cavalry",  "knight", 4, "C", 10, 9, 5, 10, 30, 7, flies=False, cost_gold=300, cost_ore=1, weekly_growth=3),
]

NECROMANCER: list[Creature] = [
    Creature("Skeleton", "necromancer", 1, "s", 2, 2, 1, 2, 4, 4, cost_gold=30, weekly_growth=10),
    Creature("Zombie",   "necromancer", 2, "z", 5, 2, 2, 3, 15, 3, cost_gold=150, weekly_growth=6),
    Creature("Mummy",    "necromancer", 3, "m", 6, 6, 3, 4, 25, 4, cost_gold=200, cost_ore=1, weekly_growth=4),
    Creature("Vampire",  "necromancer", 4, "V", 8, 6, 5, 8, 30, 6, flies=True,  cost_gold=300, cost_ore=1, weekly_growth=3),
]


CREATURES: dict[str, Creature] = {c.name: c for c in KNIGHT + NECROMANCER}


def creatures_for(faction: str) -> list[Creature]:
    if faction == "knight":
        return KNIGHT
    if faction == "necromancer":
        return NECROMANCER
    return []


# ---------- buildings ----------------------------------------------------

@dataclass(frozen=True)
class Building:
    key: str
    name: str
    cost_gold: int
    cost_wood: int = 0
    cost_ore: int = 0
    requires: tuple[str, ...] = ()
    dwelling_tier: int = 0   # 0 = not a creature dwelling


BUILDINGS: dict[str, Building] = {
    "town_hall":    Building("town_hall",    "Town Hall",     0,    0,  0),
    "tavern":       Building("tavern",       "Tavern",        500,  5,  0),
    "castle_walls": Building("castle_walls", "Castle Walls",  5000, 20, 20, requires=("town_hall",)),
    "magic_guild":  Building("magic_guild",  "Magic Guild I", 2000, 5,  5),
    "dwelling_t1":  Building("dwelling_t1",  "Dwelling T1",   400,  5,  0, dwelling_tier=1),
    "dwelling_t2":  Building("dwelling_t2",  "Dwelling T2",   1000, 5,  5, dwelling_tier=2, requires=("dwelling_t1",)),
    "dwelling_t3":  Building("dwelling_t3",  "Dwelling T3",   2000, 5, 10, dwelling_tier=3, requires=("dwelling_t2",)),
    "dwelling_t4":  Building("dwelling_t4",  "Dwelling T4",   5000, 10, 20, dwelling_tier=4, requires=("dwelling_t3","castle_walls")),
}


BUILD_ORDER: list[str] = [
    "town_hall", "tavern", "castle_walls", "magic_guild",
    "dwelling_t1", "dwelling_t2", "dwelling_t3", "dwelling_t4",
]


# ---------- factions -----------------------------------------------------

@dataclass(frozen=True)
class Faction:
    key: str
    name: str
    color: str          # "r,g,b" for Textual styles
    marker: str         # single glyph for hero/town ownership
    creatures: list[Creature] = field(default_factory=list)


FACTIONS: dict[str, Faction] = {
    "knight":      Faction("knight",      "Knight",      "230,80,80",   "K", creatures=KNIGHT),
    "necromancer": Faction("necromancer", "Necromancer", "140,120,200", "N", creatures=NECROMANCER),
}


PLAYER_FACTION: list[str] = ["knight", "necromancer"]  # p0 = knight, p1 = necromancer


# ---------- hero types ---------------------------------------------------

@dataclass(frozen=True)
class HeroClass:
    key: str
    name: str
    faction: str
    attack: int
    defense: int
    spell_power: int
    knowledge: int
    # Starting army — list of (creature_name, count).
    starting_army: list[tuple[str, int]]


HEROES: dict[str, HeroClass] = {
    "lord_kilburn": HeroClass("lord_kilburn", "Lord Kilburn", "knight",
                              attack=2, defense=2, spell_power=1, knowledge=1,
                              starting_army=[("Peasant", 20), ("Archer", 5), ("Pikeman", 3)]),
    "sandro":       HeroClass("sandro",       "Sandro",       "necromancer",
                              attack=1, defense=1, spell_power=3, knowledge=3,
                              starting_army=[("Skeleton", 15), ("Zombie", 6), ("Mummy", 3)]),
    # Tavern-recruitable generics.
    "errand_knight":  HeroClass("errand_knight",  "Sir Cedric",   "knight",
                                 attack=1, defense=2, spell_power=1, knowledge=1,
                                 starting_army=[("Peasant", 10)]),
    "apprentice_lich": HeroClass("apprentice_lich","Apprentice Lich","necromancer",
                                 attack=1, defense=1, spell_power=2, knowledge=2,
                                 starting_army=[("Skeleton", 10)]),
}


def tavern_pool_for(faction: str) -> list[HeroClass]:
    """Heroes available to recruit at a tavern of `faction`."""
    return [h for h in HEROES.values() if h.faction == faction]
