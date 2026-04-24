"""Hex tactical combat — 11×9 grid, stack-based, turn order by speed.

Combat has its own state machine separate from the adventure map. The
adventure map calls `Combat.begin(...)` and the TUI pops `CombatScreen`
which drives `Combat.act_*` until `combat.is_over` is True, then calls
`game.resolve_combat(...)` with the survivors.

Creatures act as **stacks** — a unit of (creature_type, count). Stacks
use each creature's `attack`, `defense`, `damage_min..damage_max`, `hp`,
`speed`, `shots`, `flies` to compute damage and movement.

Formula (classic HoMM2-ish, distilled):

    raw_damage = count * randint(damage_min, damage_max)
    if attack > defense:
        mult = 1 + 0.10 * (attack - defense)
    else:
        mult = 1 / (1 + 0.05 * (defense - attack))
    damage = raw_damage * mult * range_penalty * defend_mult
    total_hp = target.count * target.creature.hp - target.damage_taken
    total_hp -= damage
    target.count = max(0, ceil(total_hp / target.creature.hp))
    target.damage_taken = max(0, total_hp - new_count * creature.hp) ... etc

We keep damage bookkeeping per-stack so partial-HP lead creatures carry
over (no free health from killing 0.5 creatures).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional

from .content import CREATURES, Creature
from .game import ArmyStack, Hero
from .hex import Point
from .hex import distance as hex_distance_point
from .hex import neighbours, in_bounds


# Alias kept for readability in this module.
distance = hex_distance_point


COMBAT_W = 11
COMBAT_H = 9


@dataclass
class CombatStack:
    sid: int                     # within-combat stack id
    side: int                    # 0 attacker, 1 defender
    creature: Creature
    count: int
    max_count: int
    hp_top: int                  # HP of the top creature (0..creature.hp-1 damage)
    x: int
    y: int
    shots: int
    done: bool = False
    defending: bool = False
    waited: bool = False
    hero_attack_bonus: int = 0
    hero_defense_bonus: int = 0

    @property
    def alive(self) -> bool:
        return self.count > 0

    @property
    def name(self) -> str:
        return self.creature.name

    def total_hp(self) -> int:
        return (self.count - 1) * self.creature.hp + self.hp_top

    def take_damage(self, raw: int) -> int:
        """Apply `raw` damage, return number of creatures killed."""
        killed = 0
        remaining = raw
        # Burn down hp_top first.
        while remaining > 0 and self.count > 0:
            if remaining >= self.hp_top:
                remaining -= self.hp_top
                self.count -= 1
                killed += 1
                self.hp_top = self.creature.hp
            else:
                self.hp_top -= remaining
                remaining = 0
        if self.count <= 0:
            self.count = 0
            self.hp_top = 0
        return killed


class Combat:
    """One tactical battle.

    Drive via:
        combat = Combat.begin(attacker_army, defender_army, ...)
        while not combat.is_over:
            stack = combat.current_stack
            # Either:
            combat.act_move_attack(tx, ty)
            combat.act_wait()
            combat.act_defend()
        winner_is_attacker = combat.winner == 0
        survivors_attacker = combat.survivors(0)
        survivors_defender = combat.survivors(1)
    """

    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)
        self.stacks: list[CombatStack] = []
        self.current_idx = 0
        self.round = 1
        self.winner: Optional[int] = None
        self.log: list[str] = []
        self.attacker_hero: Optional[Hero] = None
        self.defender_hero: Optional[Hero] = None
        self._order: list[int] = []         # stack ids in speed order for this round
        self._waited_sids: set[int] = set()

    # ------- factory ---------------------------------------------------

    @classmethod
    def begin(cls,
              attacker_army: list[ArmyStack], defender_army: list[ArmyStack],
              attacker_hero: Optional[Hero] = None,
              defender_hero: Optional[Hero] = None,
              seed: int = 0) -> "Combat":
        c = cls(seed=seed)
        c.attacker_hero = attacker_hero
        c.defender_hero = defender_hero
        # Place stacks: attacker in col 0, defender in col COMBAT_W-1.
        next_sid = 0
        a_atk = attacker_hero.attack if attacker_hero else 0
        a_def = attacker_hero.defense if attacker_hero else 0
        d_atk = defender_hero.attack if defender_hero else 0
        d_def = defender_hero.defense if defender_hero else 0

        a_rows = _line_rows(len([s for s in attacker_army if s.count > 0]))
        for i, s in enumerate(attacker_army):
            if s.count <= 0:
                continue
            creature = CREATURES.get(s.creature)
            if creature is None:
                continue
            stack = CombatStack(
                sid=next_sid, side=0, creature=creature, count=s.count,
                max_count=s.count, hp_top=creature.hp,
                x=0, y=a_rows.pop(0),
                shots=creature.shots,
                hero_attack_bonus=a_atk, hero_defense_bonus=a_def,
            )
            c.stacks.append(stack)
            next_sid += 1

        d_rows = _line_rows(len([s for s in defender_army if s.count > 0]))
        for s in defender_army:
            if s.count <= 0:
                continue
            creature = CREATURES.get(s.creature)
            if creature is None:
                continue
            stack = CombatStack(
                sid=next_sid, side=1, creature=creature, count=s.count,
                max_count=s.count, hp_top=creature.hp,
                x=COMBAT_W - 1, y=d_rows.pop(0),
                shots=creature.shots,
                hero_attack_bonus=d_atk, hero_defense_bonus=d_def,
            )
            c.stacks.append(stack)
            next_sid += 1

        # Edge case: one side has zero stacks. Auto-win the other side.
        if not c._any_alive(0) or not c._any_alive(1):
            c._finalise()
            return c
        c._start_round()
        return c

    # ------- round / turn book-keeping -------------------------------

    def _start_round(self) -> None:
        # Build initiative list for this round: highest speed first.
        alive = [s for s in self.stacks if s.alive]
        alive.sort(key=lambda s: (-s.creature.speed, s.sid))
        self._order = [s.sid for s in alive]
        self.current_idx = 0
        for s in self.stacks:
            s.done = False
            s.defending = False
            s.waited = False
        self._waited_sids = set()
        self._skip_to_next_active()

    def _skip_to_next_active(self) -> None:
        # Skip over dead / done stacks.
        while self.current_idx < len(self._order):
            sid = self._order[self.current_idx]
            s = self._stack(sid)
            if s is not None and s.alive and not s.done:
                return
            self.current_idx += 1
        # Round end. Waited stacks act now, in reverse speed order.
        waited_stacks = [s for sid in self._waited_sids
                         if (s := self._stack(sid)) is not None
                         and s.alive and not s.done]
        if waited_stacks:
            # Sort by reverse speed (slowest first), tie-break on sid.
            waited_stacks.sort(key=lambda s: (s.creature.speed, s.sid))
            self._order += [s.sid for s in waited_stacks]
            # current_idx already past prior end — positioned at waited start.
            # Actually length just grew; current_idx now valid pointing at next waited.
            self._waited_sids = set()
            self._skip_to_next_active()
            return
        # Nothing more — new round.
        if self._any_alive(0) and self._any_alive(1):
            self.round += 1
            self._start_round()
        else:
            self._finalise()

    def _finalise(self) -> None:
        if not self._any_alive(0):
            self.winner = 1
        elif not self._any_alive(1):
            self.winner = 0

    def _any_alive(self, side: int) -> bool:
        return any(s.alive for s in self.stacks if s.side == side)

    def _stack(self, sid: int) -> Optional[CombatStack]:
        for s in self.stacks:
            if s.sid == sid:
                return s
        return None

    @property
    def is_over(self) -> bool:
        return self.winner is not None

    @property
    def current_stack(self) -> Optional[CombatStack]:
        if self.is_over or self.current_idx >= len(self._order):
            return None
        return self._stack(self._order[self.current_idx])

    # ------- queries --------------------------------------------------

    def stack_at(self, x: int, y: int) -> Optional[CombatStack]:
        for s in self.stacks:
            if s.alive and s.x == x and s.y == y:
                return s
        return None

    def move_range(self, stack: CombatStack) -> set[tuple[int, int]]:
        """BFS by hex from stack's position, up to stack.speed steps.
        Blocked by: out-of-bounds, other stacks' tiles."""
        origin = Point(stack.x, stack.y)
        best: dict[tuple[int, int], int] = {(origin.x, origin.y): 0}
        queue: list[tuple[int, Point]] = [(0, origin)]
        while queue:
            dist, here = queue.pop(0)
            if dist >= stack.creature.speed:
                continue
            for nb in neighbours(here):
                if not in_bounds(nb, COMBAT_W, COMBAT_H):
                    continue
                key = (nb.x, nb.y)
                occupant = self.stack_at(nb.x, nb.y)
                if occupant is not None and occupant is not stack:
                    continue
                if stack.creature.flies:
                    # Flyer ignores terrain distance — straight-line.
                    if key in best and best[key] <= dist + 1:
                        continue
                    best[key] = dist + 1
                else:
                    if key in best and best[key] <= dist + 1:
                        continue
                    best[key] = dist + 1
                queue.append((dist + 1, nb))
        best.pop((origin.x, origin.y), None)
        return set(best.keys())

    # ------- actions --------------------------------------------------

    def act_move_attack(self, tx: int, ty: int) -> str:
        """Move current stack to (tx,ty). If the target tile has an enemy,
        attempt melee attack from the nearest adjacent empty tile, or
        perform a ranged attack if the stack has shots and isn't adjacent."""
        stack = self.current_stack
        if stack is None:
            return "no active stack"
        target = self.stack_at(tx, ty)

        # Ranged attack on any tile with an enemy, without moving.
        if target is not None and target.side != stack.side:
            if stack.shots > 0 and distance(Point(stack.x, stack.y),
                                            Point(tx, ty)) > 1:
                return self._ranged_attack(stack, target)
            # Melee: step to an adjacent tile and attack.
            return self._move_then_melee(stack, target)

        # Pure move to empty tile.
        if target is None:
            reach = self.move_range(stack)
            if (tx, ty) not in reach:
                return f"{stack.name} can't reach ({tx},{ty})."
            stack.x, stack.y = tx, ty
            stack.done = True
            self.log.append(f"{stack.name} moves to ({tx},{ty}).")
            self.current_idx += 1
            self._skip_to_next_active()
            return f"{stack.name} moves."
        return "friendly tile — can't move through."

    def _move_then_melee(self, stack: CombatStack, target: CombatStack) -> str:
        """Pick the nearest reachable adjacent tile to target and attack.
        If no adjacent tile is reachable, take the longest move *toward*
        the target and end the turn without an attack."""
        reach = self.move_range(stack) | {(stack.x, stack.y)}
        adj = [(nb.x, nb.y) for nb in neighbours(Point(target.x, target.y))
               if in_bounds(nb, COMBAT_W, COMBAT_H)]
        candidates = [(x, y) for (x, y) in adj if (x, y) in reach]
        if not candidates:
            # No adjacent attack tile reachable — step as close as we can
            # and end the turn. This prevents infinite loops and is
            # roughly what the original game does.
            best_move = None
            best_d = hex_distance_point(Point(stack.x, stack.y),
                                          Point(target.x, target.y))
            for (rx, ry) in reach:
                d = hex_distance_point(Point(rx, ry),
                                        Point(target.x, target.y))
                if d < best_d:
                    best_d = d
                    best_move = (rx, ry)
            if best_move is not None:
                stack.x, stack.y = best_move
                self.log.append(
                    f"{stack.name} advances to ({best_move[0]},{best_move[1]})."
                )
            else:
                self.log.append(f"{stack.name} holds position.")
            stack.done = True
            self.current_idx += 1
            self._skip_to_next_active()
            return f"{stack.name} advances."
        # Pick by hex-distance from current pos.
        candidates.sort(key=lambda p: distance(Point(stack.x, stack.y),
                                               Point(p[0], p[1])))
        nx, ny = candidates[0]
        if (nx, ny) != (stack.x, stack.y):
            stack.x, stack.y = nx, ny
            self.log.append(f"{stack.name} moves to ({nx},{ny}).")

        damage, killed = self._calc_damage(stack, target, ranged=False)
        killed_actual = target.take_damage(damage)
        self.log.append(
            f"{stack.name} attacks {target.name} for {damage} "
            f"(killed {killed_actual})."
        )
        # Counterattack (if target still alive and hasn't counterattacked).
        if target.alive and not target.defending:
            cdamage, _ = self._calc_damage(target, stack, ranged=False,
                                           is_counterattack=True)
            k = stack.take_damage(cdamage)
            self.log.append(
                f"{target.name} retaliates for {cdamage} (killed {k})."
            )
        stack.done = True
        self.current_idx += 1
        self._skip_to_next_active()
        if not self._any_alive(0) or not self._any_alive(1):
            self._finalise()
        return f"{stack.name} attacks {target.name}."

    def _ranged_attack(self, stack: CombatStack, target: CombatStack) -> str:
        if stack.shots <= 0:
            return self._move_then_melee(stack, target)
        stack.shots -= 1
        damage, _ = self._calc_damage(stack, target, ranged=True)
        k = target.take_damage(damage)
        self.log.append(
            f"{stack.name} shoots {target.name} for {damage} (killed {k})."
        )
        # No counter on ranged.
        stack.done = True
        self.current_idx += 1
        self._skip_to_next_active()
        if not self._any_alive(0) or not self._any_alive(1):
            self._finalise()
        return f"{stack.name} shoots."

    def act_wait(self) -> str:
        stack = self.current_stack
        if stack is None:
            return "no active stack"
        if stack.waited:
            return "Already waited; must act."
        stack.waited = True
        self._waited_sids.add(stack.sid)
        # Don't mark done — waited stacks act at end of round.
        self.log.append(f"{stack.name} waits.")
        self.current_idx += 1
        self._skip_to_next_active()
        return f"{stack.name} waits."

    def act_defend(self) -> str:
        stack = self.current_stack
        if stack is None:
            return "no active stack"
        stack.defending = True
        stack.done = True
        self.log.append(f"{stack.name} defends (+30% def).")
        self.current_idx += 1
        self._skip_to_next_active()
        return f"{stack.name} defends."

    # ------- damage math ---------------------------------------------

    def _calc_damage(self, attacker: CombatStack, defender: CombatStack,
                     ranged: bool,
                     is_counterattack: bool = False) -> tuple[int, int]:
        """Return (final_damage, killed). Killed is a hint only; caller
        calls `take_damage` to actually apply."""
        ac = attacker.creature
        dc = defender.creature
        # Roll per stack (not per creature — keeps it fast).
        roll = (self.rng.randint(ac.damage_min, ac.damage_max)
                if ac.damage_max >= ac.damage_min else ac.damage_min)
        raw = attacker.count * roll
        atk = ac.attack + attacker.hero_attack_bonus
        dfn = dc.defense + defender.hero_defense_bonus + (3 if defender.defending else 0)
        if atk > dfn:
            mult = 1.0 + 0.10 * (atk - dfn)
        else:
            mult = 1.0 / (1.0 + 0.05 * (dfn - atk))
        dmg = raw * mult
        if ranged:
            d = distance(Point(attacker.x, attacker.y),
                         Point(defender.x, defender.y))
            if d > 5:
                dmg *= 0.5
        if is_counterattack:
            dmg *= 1.0  # no penalty in v0
        final = max(1, int(math.ceil(dmg)))
        killed_hint = final // max(1, dc.hp)
        return final, killed_hint

    # ------- survivor export -----------------------------------------

    def survivors(self, side: int) -> list[ArmyStack]:
        return [ArmyStack(s.creature.name, s.count)
                for s in self.stacks if s.side == side and s.alive]


def _line_rows(n: int) -> list[int]:
    """Compute y-rows for n stacks centred vertically on the COMBAT_H grid."""
    if n <= 0:
        return []
    top = (COMBAT_H - n) // 2
    return [top + i for i in range(n)]
