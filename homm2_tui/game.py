"""Adventure map + turn engine.

World state, hero movement, resource collection, fog of war, turn
rotation, weekly growth in towns, victory check. No combat here —
see `combat.py` for the hex tactical layer. The adventure map calls
`begin_combat(...)` to hand off when a hero encounters monsters or
an enemy-held town.

Grid is orthogonal (NOT hex) — each tile is one screen cell. Hero
moves in 8 directions (including diagonals), cost per step drawn from
TERRAIN_COST (grass=100, road=75, etc.).
"""

from __future__ import annotations

import json
import random
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Optional

from .content import (
    CREATURES, FACTIONS, HEROES, PLAYER_FACTION, BUILDINGS, BUILD_ORDER,
    creatures_for, tavern_pool_for,
)


# ------- tile + object types ---------------------------------------------

TERRAIN_COST: dict[str, int] = {
    "grass":    100,
    "dirt":     125,
    "sand":     150,
    "road":      75,
    "water":   9999,
    "tree":    9999,
    "mountain":9999,
    "rock":    9999,
    "snow":    175,
}


# Objects encountered on a tile, keyed to "kind" in Mapobject.
# Movement passes through zero-cost empty tiles; blocked tiles
# need specific interaction.
OBJ_BLOCKING = {
    "mine_ore", "mine_wood", "gold_pile", "chest", "monster",
    "town", "hero",
}


@dataclass
class MapObject:
    kind: str                       # "mine_ore" | "mine_wood" | "gold_pile" | "chest" |
                                    #   "monster" | "town" | "hero"
    owner: int = -1                 # -1 = neutral; else player index
    x: int = 0
    y: int = 0
    # Generic payload:
    data: dict = field(default_factory=dict)


# ------- army + hero -----------------------------------------------------

@dataclass
class ArmyStack:
    creature: str                   # key into CREATURES
    count: int


@dataclass
class Hero:
    hid: int
    owner: int
    class_key: str
    name: str
    x: int
    y: int
    army: list[ArmyStack] = field(default_factory=list)
    attack: int = 0
    defense: int = 0
    spell_power: int = 1
    knowledge: int = 1
    mp: int = 1500
    max_mp: int = 1500
    sight: int = 4

    def alive(self) -> bool:
        return any(s.count > 0 for s in self.army)


# ------- town ------------------------------------------------------------

@dataclass
class Town:
    tid: int
    owner: int
    faction: str
    name: str
    x: int
    y: int
    buildings: set[str] = field(default_factory=lambda: {"town_hall"})
    built_today: bool = False
    # Garrison: army that defends the town when no hero is visiting.
    garrison: list[ArmyStack] = field(default_factory=list)
    # Visiting hero id (-1 = none). A visiting hero's army defends the
    # town siege before the garrison's stacks get to swing.
    visiting_hid: int = -1
    # Creatures produced by dwellings that haven't been bought yet.
    pool: dict[int, int] = field(default_factory=dict)   # tier -> count


# ------- resources -------------------------------------------------------

@dataclass
class Resources:
    gold: int = 0
    wood: int = 0
    ore: int = 0

    def can_afford(self, g: int = 0, w: int = 0, o: int = 0) -> bool:
        return self.gold >= g and self.wood >= w and self.ore >= o

    def spend(self, g: int = 0, w: int = 0, o: int = 0) -> bool:
        if not self.can_afford(g, w, o):
            return False
        self.gold -= g; self.wood -= w; self.ore -= o
        return True

    def add(self, g: int = 0, w: int = 0, o: int = 0) -> None:
        self.gold += g; self.wood += w; self.ore += o


# ------- visibility / fog of war ----------------------------------------

HIDDEN, SEEN, VISIBLE = 0, 1, 2


# ------- mission + world state ------------------------------------------

@dataclass
class Mission:
    name: str
    width: int
    height: int
    tiles: list[list[str]]                          # tiles[y][x] = terrain class
    objects: list[MapObject] = field(default_factory=list)
    heroes: list[Hero] = field(default_factory=list)
    towns: list[Town] = field(default_factory=list)
    num_players: int = 2


class GameState:
    """Top-level world state."""

    def __init__(self, mission: Mission, seed: int = 0) -> None:
        self.mission = mission
        self.w = mission.width
        self.h = mission.height
        self.turn = 1                       # day number; week = (turn-1)//7 + 1
        self.current_player = 0
        self.num_players = mission.num_players
        self.winner: Optional[int] = None
        self.rng = random.Random(seed)

        # Resources per player.
        self.resources: list[Resources] = [
            Resources(gold=7500, wood=10, ore=10) for _ in range(self.num_players)
        ]

        # Per-player fog of war grid.
        self.visibility: list[list[list[int]]] = [
            [[HIDDEN for _ in range(self.w)] for _ in range(self.h)]
            for _ in range(self.num_players)
        ]

        # O(1) "what's on this tile" lookups.
        self._obj_at: dict[tuple[int, int], MapObject] = {}
        for o in mission.objects:
            self._obj_at[(o.x, o.y)] = o

        # Start-of-game visibility around each hero + town.
        for hero in mission.heroes:
            self._reveal_around(hero.owner, hero.x, hero.y, hero.sight)
        for town in mission.towns:
            if town.owner >= 0:
                self._reveal_around(town.owner, town.x, town.y, 5)

        # Flags a combat encounter pending for the TUI to open modally.
        # When set, the TUI should pop a CombatScreen; when combat
        # completes the TUI calls `resolve_combat(...)`.
        self.pending_combat: Optional["PendingCombat"] = None

        self.log: list[str] = []

    # ------- queries --------------------------------------------------

    def tile_class(self, x: int, y: int) -> str:
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.mission.tiles[y][x]
        return "rock"

    def obj_at(self, x: int, y: int) -> Optional[MapObject]:
        return self._obj_at.get((x, y))

    def hero_at(self, x: int, y: int) -> Optional[Hero]:
        for h in self.mission.heroes:
            if h.x == x and h.y == y and h.alive():
                return h
        return None

    def town_at(self, x: int, y: int) -> Optional[Town]:
        for t in self.mission.towns:
            if t.x == x and t.y == y:
                return t
        return None

    def heroes_for(self, player: int) -> list[Hero]:
        return [h for h in self.mission.heroes if h.owner == player and h.alive()]

    def towns_for(self, player: int) -> list[Town]:
        return [t for t in self.mission.towns if t.owner == player]

    # ------- movement -------------------------------------------------

    def step_cost(self, hero: Hero, tx: int, ty: int) -> int:
        """Cost in MP to step from hero.pos → (tx, ty). Assumes adjacency."""
        if abs(tx - hero.x) > 1 or abs(ty - hero.y) > 1:
            return 9999
        terrain = self.tile_class(tx, ty)
        base = TERRAIN_COST.get(terrain, 100)
        # Diagonal = ~1.4x. Keep it integer-ish.
        if tx != hero.x and ty != hero.y:
            base = int(base * 1.414)
        return base

    def can_step(self, hero: Hero, tx: int, ty: int) -> bool:
        if not (0 <= tx < self.w and 0 <= ty < self.h):
            return False
        cost = self.step_cost(hero, tx, ty)
        if cost > hero.mp:
            return False
        if TERRAIN_COST.get(self.tile_class(tx, ty), 100) >= 9999:
            return False
        # Own hero / own town? Blocked unless it's an object we can "visit".
        obj = self.obj_at(tx, ty)
        if obj is not None:
            if obj.kind == "hero" and obj.owner == hero.owner:
                return False
        # Can always step on any object (triggers interaction), except
        # enemy-owned mine that the hero is already on.
        return True

    def step_hero(self, hero: Hero, tx: int, ty: int) -> str:
        """Move the hero one tile and handle tile interaction.

        Returns a log-string describing what happened.
        """
        if not self.can_step(hero, tx, ty):
            return f"{hero.name}: cannot move to ({tx},{ty})."
        cost = self.step_cost(hero, tx, ty)
        obj = self.obj_at(tx, ty)

        # Mine / gold / chest / monster / enemy-town / enemy-hero
        # interaction happens _before_ we physically move onto the tile
        # in cases of combat, so the attacker doesn't end up on an
        # occupied square. Same-player town: hero visits.

        # --- monster → combat ---
        if obj is not None and obj.kind == "monster":
            self.pending_combat = PendingCombat(
                attacker_hid=hero.hid,
                defender=CombatDefender(
                    kind="monster",
                    army=list(obj.data.get("army", [])),
                    owner=-1,
                    tile=(tx, ty),
                ),
            )
            hero.mp = max(0, hero.mp - cost)
            return f"{hero.name} engages the {obj.data.get('label', 'monsters')}!"

        # --- enemy-held town → siege ---
        if obj is not None and obj.kind == "town" and obj.owner >= 0 and obj.owner != hero.owner:
            town = self.town_at(tx, ty)
            if town is not None:
                defender_army: list[ArmyStack] = []
                if town.visiting_hid >= 0:
                    vhero = next((h for h in self.mission.heroes
                                  if h.hid == town.visiting_hid), None)
                    if vhero is not None:
                        defender_army = list(vhero.army)
                defender_army += list(town.garrison)
                self.pending_combat = PendingCombat(
                    attacker_hid=hero.hid,
                    defender=CombatDefender(
                        kind="town",
                        army=defender_army,
                        owner=town.owner,
                        tile=(tx, ty),
                        town_tid=town.tid,
                    ),
                )
                hero.mp = max(0, hero.mp - cost)
                return f"{hero.name} lays siege to {town.name}!"

        # --- enemy hero on tile → combat ---
        if obj is not None and obj.kind == "hero" and obj.owner != hero.owner and obj.owner >= 0:
            other = next((h for h in self.mission.heroes
                          if h.x == tx and h.y == ty and h.owner == obj.owner), None)
            if other is not None:
                self.pending_combat = PendingCombat(
                    attacker_hid=hero.hid,
                    defender=CombatDefender(
                        kind="hero",
                        army=list(other.army),
                        owner=other.owner,
                        tile=(tx, ty),
                        hero_hid=other.hid,
                    ),
                )
                hero.mp = max(0, hero.mp - cost)
                return f"{hero.name} intercepts {other.name}!"

        # --- safe interactions: move then handle ---
        # Remove hero-object shadow at old tile.
        self._remove_hero_shadow(hero)
        hero.x, hero.y = tx, ty
        hero.mp = max(0, hero.mp - cost)
        self._place_hero_shadow(hero)
        self._reveal_around(hero.owner, tx, ty, hero.sight)

        if obj is not None:
            return self._visit_object(hero, obj)
        return f"{hero.name} moves to ({tx},{ty}). MP left: {hero.mp}."

    def _visit_object(self, hero: Hero, obj: MapObject) -> str:
        if obj.kind == "gold_pile":
            amt = int(obj.data.get("amount", 1000))
            self.resources[hero.owner].add(g=amt)
            self._remove_obj(obj)
            return f"{hero.name} finds {amt} gold!"
        if obj.kind == "chest":
            amt = int(obj.data.get("amount", 1500))
            self.resources[hero.owner].add(g=amt)
            self._remove_obj(obj)
            return f"{hero.name} opens a chest: {amt} gold."
        if obj.kind == "mine_ore":
            obj.owner = hero.owner
            return f"{hero.name} captures the ore mine."
        if obj.kind == "mine_wood":
            obj.owner = hero.owner
            return f"{hero.name} captures the sawmill."
        if obj.kind == "town":
            # Own-faction town: visit.
            if obj.owner == hero.owner:
                town = self.town_at(obj.x, obj.y)
                if town is not None:
                    town.visiting_hid = hero.hid
                return f"{hero.name} visits {obj.data.get('town_name','the town')}."
            # Neutral? capture it with no fight (deliberate simplification).
            if obj.owner < 0:
                obj.owner = hero.owner
                town = self.town_at(obj.x, obj.y)
                if town is not None:
                    town.owner = hero.owner
                    town.visiting_hid = hero.hid
                self._check_victory()
                return f"{hero.name} claims {obj.data.get('town_name','the town')}!"
        return f"{hero.name} visits {obj.kind}."

    def _remove_obj(self, obj: MapObject) -> None:
        self._obj_at.pop((obj.x, obj.y), None)
        if obj in self.mission.objects:
            self.mission.objects.remove(obj)

    # Hero-on-map shadow objects. These exist so the map lookup sees a
    # hero there without searching the hero list each time.
    def _place_hero_shadow(self, hero: Hero) -> None:
        # Don't overwrite a town/mine tile.
        existing = self._obj_at.get((hero.x, hero.y))
        if existing is not None and existing.kind not in ("hero",):
            # Town visit: leave the town shadow; hero is "inside" it.
            return
        obj = MapObject(kind="hero", owner=hero.owner, x=hero.x, y=hero.y,
                        data={"hid": hero.hid})
        self._obj_at[(hero.x, hero.y)] = obj
        if obj not in self.mission.objects:
            self.mission.objects.append(obj)

    def _remove_hero_shadow(self, hero: Hero) -> None:
        o = self._obj_at.get((hero.x, hero.y))
        if o is not None and o.kind == "hero" and o.data.get("hid") == hero.hid:
            self._remove_obj(o)

    # ------- fog of war -----------------------------------------------

    def _reveal_around(self, player: int, cx: int, cy: int, radius: int) -> None:
        for y in range(max(0, cy - radius), min(self.h, cy + radius + 1)):
            for x in range(max(0, cx - radius), min(self.w, cx + radius + 1)):
                if (x - cx) * (x - cx) + (y - cy) * (y - cy) <= radius * radius:
                    self.visibility[player][y][x] = VISIBLE

    def vis_of(self, player: int, x: int, y: int) -> int:
        if not (0 <= x < self.w and 0 <= y < self.h):
            return HIDDEN
        return self.visibility[player][y][x]

    # ------- turn + weekly logic --------------------------------------

    def end_turn(self) -> None:
        """Pass baton to next player; if wraparound, advance day + accrue
        weekly growth on week boundary."""
        # Clear "built_today" for this player's towns (it's their turn
        # that matters for build-once-per-day).
        for t in self.towns_for(self.current_player):
            t.built_today = False

        # Hand off.
        self.current_player = (self.current_player + 1) % self.num_players
        if self.current_player == 0:
            self.turn += 1
            # New day for every player: refill MP, apply mine income.
            for player in range(self.num_players):
                for h in self.heroes_for(player):
                    h.mp = h.max_mp
                # Mines -> daily income (base from town halls).
                self.resources[player].add(g=500 * len(self.towns_for(player)))
                for obj in self.mission.objects:
                    if obj.kind == "mine_ore" and obj.owner == player:
                        self.resources[player].add(o=2)
                    elif obj.kind == "mine_wood" and obj.owner == player:
                        self.resources[player].add(w=2)
            # Week boundary — accrue creature growth.
            if (self.turn - 1) % 7 == 0 and self.turn > 1:
                self._weekly_growth()

        # Even sub-turns (i.e. not wrap) still reset the incoming
        # player's built_today flag: done above via `towns_for`.

    def _weekly_growth(self) -> None:
        for t in self.mission.towns:
            if t.owner < 0:
                continue
            for tier in range(1, 5):
                if f"dwelling_t{tier}" in t.buildings:
                    # Find creature for this tier+faction.
                    c = next((c for c in creatures_for(t.faction) if c.tier == tier), None)
                    if c is None:
                        continue
                    t.pool[tier] = t.pool.get(tier, 0) + c.weekly_growth

    # ------- town management ------------------------------------------

    def can_build(self, town: Town, bkey: str) -> tuple[bool, str]:
        if town.built_today:
            return False, "already built this day"
        if bkey in town.buildings:
            return False, "already have it"
        b = BUILDINGS[bkey]
        for req in b.requires:
            if req not in town.buildings:
                return False, f"requires {BUILDINGS[req].name}"
        if not self.resources[town.owner].can_afford(b.cost_gold, b.cost_wood, b.cost_ore):
            return False, "not enough resources"
        return True, "ok"

    def build(self, town: Town, bkey: str) -> str:
        ok, why = self.can_build(town, bkey)
        if not ok:
            return f"Can't build {BUILDINGS[bkey].name}: {why}."
        b = BUILDINGS[bkey]
        self.resources[town.owner].spend(b.cost_gold, b.cost_wood, b.cost_ore)
        town.buildings.add(bkey)
        town.built_today = True
        # First-time dwelling gets one week of starting creatures.
        if b.dwelling_tier > 0:
            c = next((c for c in creatures_for(town.faction) if c.tier == b.dwelling_tier), None)
            if c is not None:
                town.pool[b.dwelling_tier] = town.pool.get(b.dwelling_tier, 0) + c.weekly_growth
        return f"Built {b.name}."

    def recruit(self, town: Town, tier: int, count: int, into_garrison: bool = True) -> str:
        """Purchase `count` creatures of `tier` from the town pool. If
        `into_garrison` is False and a hero is visiting, stacks go into
        the hero's army; otherwise into the garrison."""
        available = town.pool.get(tier, 0)
        if count <= 0 or available <= 0:
            return "No creatures available."
        count = min(count, available)
        c = next((c for c in creatures_for(town.faction) if c.tier == tier), None)
        if c is None:
            return "Unknown creature tier."
        total_g = c.cost_gold * count
        total_o = c.cost_ore * count
        total_w = c.cost_wood * count
        if not self.resources[town.owner].can_afford(total_g, total_w, total_o):
            return f"Not enough resources for {count} {c.name}."
        self.resources[town.owner].spend(total_g, total_w, total_o)
        town.pool[tier] -= count

        target_army: list[ArmyStack]
        if not into_garrison and town.visiting_hid >= 0:
            vh = next((h for h in self.mission.heroes if h.hid == town.visiting_hid), None)
            target_army = vh.army if vh is not None else town.garrison
        else:
            target_army = town.garrison

        for s in target_army:
            if s.creature == c.name:
                s.count += count
                break
        else:
            if len(target_army) < 5:
                target_army.append(ArmyStack(c.name, count))
            else:
                # No slot — refund.
                self.resources[town.owner].add(total_g, total_w, total_o)
                town.pool[tier] += count
                return "Army full (5 stacks)."
        return f"Recruited {count} {c.name}."

    def recruit_hero(self, town: Town, class_key: str) -> str:
        """Recruit a hero from the tavern. HoMM2 canonical price is 2500g.
        In v0 we allow a second hero (not enforced 1/player) so tests can
        exercise multi-hero scenarios, but the UI will nudge toward the
        MVP expectation."""
        if "tavern" not in town.buildings:
            return "Build a tavern first."
        if not self.resources[town.owner].can_afford(2500):
            return "Need 2500 gold."
        if class_key not in HEROES:
            return "Unknown hero."
        hc = HEROES[class_key]
        # Place hero on the town tile as visiting.
        hid = max((h.hid for h in self.mission.heroes), default=-1) + 1
        hero = Hero(
            hid=hid, owner=town.owner, class_key=class_key, name=hc.name,
            x=town.x, y=town.y,
            army=[ArmyStack(cn, cc) for cn, cc in hc.starting_army],
            attack=hc.attack, defense=hc.defense,
            spell_power=hc.spell_power, knowledge=hc.knowledge,
        )
        self.resources[town.owner].spend(2500)
        self.mission.heroes.append(hero)
        town.visiting_hid = hid
        self._reveal_around(town.owner, hero.x, hero.y, hero.sight)
        return f"Recruited {hero.name}!"

    # ------- combat handoff -------------------------------------------

    def resolve_combat(self, attacker_wins: bool,
                       attacker_survivors: list[ArmyStack],
                       defender_survivors: list[ArmyStack]) -> str:
        """Called by the TUI/combat engine when a PendingCombat finishes.

        `attacker_survivors` / `defender_survivors` are the stacks that
        walked off the battlefield alive. We patch the source hero and
        defender unit/town with the new army state."""
        pc = self.pending_combat
        self.pending_combat = None
        if pc is None:
            return ""
        atk = next((h for h in self.mission.heroes if h.hid == pc.attacker_hid), None)
        if atk is None:
            return "Attacker not found."

        if attacker_wins:
            atk.army = [s for s in attacker_survivors if s.count > 0]
            msg = ""
            # Monster: just remove.
            if pc.defender.kind == "monster":
                for o in list(self.mission.objects):
                    if o.kind == "monster" and (o.x, o.y) == pc.defender.tile:
                        self._remove_obj(o)
                        break
                msg = f"{atk.name} defeats the monsters."
                tx, ty = pc.defender.tile
                self._remove_hero_shadow(atk)
                atk.x, atk.y = tx, ty
                self._place_hero_shadow(atk)
                self._reveal_around(atk.owner, tx, ty, atk.sight)
            elif pc.defender.kind == "town":
                # Capture town.
                town = next((t for t in self.mission.towns
                             if t.tid == pc.defender.town_tid), None)
                if town is not None:
                    town.owner = atk.owner
                    town.garrison = [s for s in defender_survivors if s.count > 0]
                    # Remove visiting defender hero if any.
                    if town.visiting_hid >= 0:
                        vh = next((h for h in self.mission.heroes
                                   if h.hid == town.visiting_hid), None)
                        if vh is not None and vh.owner != atk.owner:
                            vh.army = []
                    town.visiting_hid = atk.hid
                    tx, ty = pc.defender.tile
                    # Update the map-object shadow owner.
                    tobj = self._obj_at.get((tx, ty))
                    if tobj is not None and tobj.kind == "town":
                        tobj.owner = atk.owner
                    # Move the attacker onto the town tile.
                    self._remove_hero_shadow(atk)
                    atk.x, atk.y = tx, ty
                    self._place_hero_shadow(atk)
                    self._reveal_around(atk.owner, tx, ty, atk.sight)
                    msg = f"{atk.name} captures {town.name}!"
                    self._check_victory()
            elif pc.defender.kind == "hero":
                # Defender hero slain.
                dh = next((h for h in self.mission.heroes
                           if h.hid == pc.defender.hero_hid), None)
                if dh is not None:
                    dh.army = []
                msg = f"{atk.name} slays {dh.name if dh else 'the enemy hero'}."
                tx, ty = pc.defender.tile
                self._remove_hero_shadow(atk)
                atk.x, atk.y = tx, ty
                self._place_hero_shadow(atk)
            return msg
        else:
            # Attacker loses. Attacker hero removed; defender army updated.
            self._remove_hero_shadow(atk)
            atk.army = []
            msg = f"{atk.name} is defeated!"
            if pc.defender.kind == "town":
                town = next((t for t in self.mission.towns
                             if t.tid == pc.defender.town_tid), None)
                if town is not None and town.visiting_hid >= 0:
                    vh = next((h for h in self.mission.heroes
                               if h.hid == town.visiting_hid), None)
                    if vh is not None:
                        vh.army = [s for s in defender_survivors if s.count > 0]
                    town.garrison = []   # simplification: all garrison used
            elif pc.defender.kind == "hero":
                dh = next((h for h in self.mission.heroes
                           if h.hid == pc.defender.hero_hid), None)
                if dh is not None:
                    dh.army = [s for s in defender_survivors if s.count > 0]
            self._check_victory()
            return msg

    # ------- victory -------------------------------------------------

    def _check_victory(self) -> None:
        """Capture-all-enemy-towns victory condition."""
        owners = {t.owner for t in self.mission.towns if t.owner >= 0}
        if len(owners) == 1 and self.turn >= 1 and len(self.mission.towns) >= 2:
            # Only check when there's something to capture.
            (only,) = owners
            self.winner = only

    # ------- save/load -----------------------------------------------

    def to_dict(self) -> dict:
        # Towns hold `buildings` as a set — convert to list for JSON.
        mission_dict = asdict(self.mission)
        for t in mission_dict.get("towns", []):
            if isinstance(t.get("buildings"), set):
                t["buildings"] = sorted(t["buildings"])
        return {
            "mission": mission_dict,
            "turn": self.turn,
            "current_player": self.current_player,
            "winner": self.winner,
            "resources": [asdict(r) for r in self.resources],
            "visibility": self.visibility,
        }

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, default=_json_default)


# ------- combat dispatch objects ----------------------------------------

def _json_default(obj):
    """JSON fallback for sets (Town.buildings). Lists everywhere else."""
    if isinstance(obj, set):
        return sorted(obj)
    raise TypeError(f"not JSON serializable: {type(obj).__name__}")


@dataclass
class CombatDefender:
    kind: str                           # "monster" | "town" | "hero"
    army: list[ArmyStack]
    owner: int                          # -1 = neutral
    tile: tuple[int, int]
    town_tid: int = -1
    hero_hid: int = -1


@dataclass
class PendingCombat:
    attacker_hid: int
    defender: CombatDefender
