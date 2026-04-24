"""Hand-authored scenarios for the HoMM2 TUI.

Only one in v0: "Dawn Assault" — 30×20 map, Knight P1 (red) vs.
Necromancer P2 (blue), one central neutral monster, an ore mine + gold
pile, each player starts with a town and a hero.
"""

from __future__ import annotations

from .content import HEROES, creatures_for, FACTIONS, PLAYER_FACTION
from .game import (
    ArmyStack, GameState, Hero, MapObject, Mission, Town, Resources,
)


def dawn_assault() -> GameState:
    w, h = 30, 20
    tiles = [["grass" for _ in range(w)] for _ in range(h)]

    # Scatter some terrain features.
    for (x, y) in [(7, 3), (8, 3), (9, 3), (10, 3),
                   (7, 4), (8, 4), (9, 4)]:
        tiles[y][x] = "tree"
    for (x, y) in [(15, 9), (16, 9), (17, 9), (15, 10), (16, 10), (17, 10)]:
        tiles[y][x] = "mountain"
    # A winding road between the two towns.
    road = [(3, 2), (4, 2), (5, 2), (5, 3), (5, 4),
            (6, 5), (7, 6), (8, 7), (9, 8), (10, 9), (11, 10),
            (12, 11), (13, 11), (14, 11), (15, 12), (16, 12),
            (17, 13), (18, 14), (19, 15), (20, 16), (21, 17),
            (22, 17), (23, 17), (24, 17), (25, 17), (26, 17)]
    for (x, y) in road:
        tiles[y][x] = "road"
    # Sand desert patch.
    for y in range(13, 16):
        for x in range(24, 28):
            tiles[y][x] = "sand"
    # Dirt patches.
    for y in range(6, 9):
        for x in range(20, 23):
            tiles[y][x] = "dirt"
    # A small lake.
    for (x, y) in [(12, 4), (13, 4), (14, 4), (12, 5), (13, 5)]:
        tiles[y][x] = "water"

    # Towns.
    town_greyspire = Town(tid=0, owner=0, faction="knight",
                          name="Greyspire", x=2, y=2,
                          buildings={"town_hall", "tavern", "dwelling_t1"})
    town_darkhold = Town(tid=1, owner=1, faction="necromancer",
                         name="Darkhold", x=27, y=17,
                         buildings={"town_hall", "tavern", "dwelling_t1"})

    # Map-object shadows for towns.
    obj_greyspire = MapObject(kind="town", owner=0, x=2, y=2,
                              data={"town_name": "Greyspire", "tid": 0})
    obj_darkhold = MapObject(kind="town", owner=1, x=27, y=17,
                             data={"town_name": "Darkhold", "tid": 1})

    # Resource piles + mines (centre of map).
    obj_gold = MapObject(kind="gold_pile", owner=-1, x=14, y=9,
                         data={"amount": 2000})
    obj_ore = MapObject(kind="mine_ore", owner=-1, x=10, y=12)
    obj_wood = MapObject(kind="mine_wood", owner=-1, x=20, y=6)
    obj_chest = MapObject(kind="chest", owner=-1, x=5, y=15,
                          data={"amount": 1500})

    # One neutral monster guarding the centre — a stack of skeletons.
    obj_monster = MapObject(kind="monster", owner=-1, x=15, y=13,
                            data={"label": "Wandering Skeletons",
                                  "army": [ArmyStack("Skeleton", 8)]})

    # Heroes.
    hc_kilburn = HEROES["lord_kilburn"]
    hero_kilburn = Hero(
        hid=0, owner=0, class_key="lord_kilburn", name="Lord Kilburn",
        x=3, y=2,
        army=[ArmyStack(cn, cc) for cn, cc in hc_kilburn.starting_army],
        attack=hc_kilburn.attack, defense=hc_kilburn.defense,
        spell_power=hc_kilburn.spell_power, knowledge=hc_kilburn.knowledge,
    )
    hc_sandro = HEROES["sandro"]
    hero_sandro = Hero(
        hid=1, owner=1, class_key="sandro", name="Sandro",
        x=26, y=17,
        army=[ArmyStack(cn, cc) for cn, cc in hc_sandro.starting_army],
        attack=hc_sandro.attack, defense=hc_sandro.defense,
        spell_power=hc_sandro.spell_power, knowledge=hc_sandro.knowledge,
    )

    mission = Mission(
        name="Dawn Assault", width=w, height=h, tiles=tiles,
        objects=[obj_greyspire, obj_darkhold, obj_gold, obj_ore, obj_wood,
                 obj_chest, obj_monster],
        heroes=[hero_kilburn, hero_sandro],
        towns=[town_greyspire, town_darkhold],
        num_players=2,
    )
    # Seed pool: starting dwelling has a week of tier-1 creatures.
    for t in mission.towns:
        c = creatures_for(t.faction)[0]
        t.pool[1] = c.weekly_growth

    g = GameState(mission, seed=0)

    # Place hero shadows on the map so lookups find them.
    for hero in mission.heroes:
        g._place_hero_shadow(hero)

    # Greyspire's hero is considered visiting.
    town_greyspire.visiting_hid = -1  # hero is one tile away
    town_darkhold.visiting_hid = -1

    return g


SCENARIOS = {
    "dawn_assault": dawn_assault,
}


def new_game(name: str = "dawn_assault") -> GameState:
    if name not in SCENARIOS:
        raise KeyError(f"unknown scenario {name!r}, known: {list(SCENARIOS)}")
    return SCENARIOS[name]()
