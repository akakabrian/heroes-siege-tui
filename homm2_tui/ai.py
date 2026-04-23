"""Stub AI for player 2.

V0 policy: each owned hero takes up to `hero.mp // 100` greedy steps
toward the nearest enemy hero or towards the nearest enemy town. If a
tile is blocked or off-map, the AI just stops. When the step lands on
an interactable (monster/town/enemy-hero), `step_hero` sets
`pending_combat` and we return — the adventure-level auto-resolver
takes over.
"""

from __future__ import annotations

from .game import GameState


def _nearest_enemy_target(game: GameState, hero) -> tuple[int, int] | None:
    """Find nearest enemy hero or town (manhattan dist). Returns (x,y)."""
    best: tuple[int, int] | None = None
    best_d = 10 ** 9
    for h in game.mission.heroes:
        if h.owner == hero.owner or not h.alive():
            continue
        d = abs(h.x - hero.x) + abs(h.y - hero.y)
        if d < best_d:
            best_d = d
            best = (h.x, h.y)
    for t in game.mission.towns:
        if t.owner == hero.owner:
            continue
        d = abs(t.x - hero.x) + abs(t.y - hero.y)
        if d < best_d:
            best_d = d
            best = (t.x, t.y)
    return best


def _step_towards(game: GameState, hero, tx: int, ty: int) -> str:
    """Issue one adventure-map step from hero → (tx,ty). Returns log string."""
    dx = (tx > hero.x) - (tx < hero.x)
    dy = (ty > hero.y) - (ty < hero.y)
    # Try diagonal first (faster), then axial fallbacks.
    candidates = [(dx, dy), (dx, 0), (0, dy)]
    for (sx, sy) in candidates:
        if sx == 0 and sy == 0:
            continue
        nx, ny = hero.x + sx, hero.y + sy
        if game.can_step(hero, nx, ny):
            return game.step_hero(hero, nx, ny)
    return f"{hero.name} stalls (no valid move)."


def take_turn(game: GameState) -> list[str]:
    """Run through all of the current player's heroes and walk each one
    a few steps toward an enemy target. Returns a list of log strings."""
    logs: list[str] = []
    heroes = list(game.heroes_for(game.current_player))
    for hero in heroes:
        if not hero.alive():
            continue
        target = _nearest_enemy_target(game, hero)
        if target is None:
            continue
        steps_left = max(1, hero.mp // 120)  # ~up to 12 grass steps
        safety = 20
        while steps_left > 0 and safety > 0 and hero.alive():
            safety -= 1
            if game.pending_combat is not None:
                # Let the caller auto-resolve; then we continue moving
                # if the hero survived.
                break
            if hero.mp <= 0:
                break
            msg = _step_towards(game, hero, *target)
            logs.append(msg)
            if "stalls" in msg or "cannot move" in msg:
                break
            # If combat just got queued, stop issuing further steps until
            # the caller resolves it.
            if game.pending_combat is not None:
                break
            # Recompute target in case it moved (our opponent).
            t2 = _nearest_enemy_target(game, hero)
            if t2 is None:
                break
            target = t2
            steps_left -= 1
    return logs
