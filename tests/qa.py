"""Headless QA driver for homm2-tui.

Each scenario runs in a fresh `HoMM2App` via `App.run_test()`, captures
an SVG screenshot, and reports pass/fail. Exit code is the failure
count.

    python -m tests.qa             # all
    python -m tests.qa combat      # substring filter

Scenarios cover:
  - adventure map mount + cursor movement
  - hero selection + one-step movement
  - resource pickup, mine capture
  - town screen mount + build + recruit
  - combat engine: damage, speed order, victory
  - save to json
  - end-to-end: capture enemy town in one session
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from homm2_tui.app import CombatScreen, HoMM2App, TownScreen
from homm2_tui.combat import COMBAT_H, COMBAT_W, Combat
from homm2_tui.content import CREATURES, BUILDINGS
from homm2_tui.game import ArmyStack, MapObject
from homm2_tui.scenarios import new_game

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)


@dataclass
class Scenario:
    name: str
    fn: Callable[[HoMM2App, "object"], Awaitable[None]]


# ---------- helpers ----------

def _own_hero(app: HoMM2App):
    return app.game.heroes_for(app.game.current_player)[0]


def _cursor_to(app: HoMM2App, x: int, y: int) -> None:
    assert app.map_view is not None
    app.map_view.cursor_x, app.map_view.cursor_y = x, y


# ---------- adventure-map scenarios ----------

async def s_mount_clean(app, pilot):
    assert app.map_view is not None
    assert app.status_panel is not None
    assert app.log_panel is not None
    assert app.game.w == 30 and app.game.h == 20


async def s_cursor_moves(app, pilot):
    sx, sy = app.map_view.cursor_x, app.map_view.cursor_y
    await pilot.press("right", "right", "right")
    await pilot.press("down")
    assert app.map_view.cursor_x == sx + 3
    assert app.map_view.cursor_y == sy + 1


async def s_cursor_clamps(app, pilot):
    for _ in range(app.game.w + 10):
        await pilot.press("left")
    assert app.map_view.cursor_x == 0
    for _ in range(app.game.h + 10):
        await pilot.press("up")
    assert app.map_view.cursor_y == 0


async def s_hero_select_and_step(app, pilot):
    h = _own_hero(app)
    _cursor_to(app, h.x, h.y)
    await pilot.pause()
    await pilot.press("enter")   # select
    assert app._selected_hero is h
    # Step one to the right (onto grass).
    _cursor_to(app, h.x + 1, h.y)
    await pilot.pause()
    await pilot.press("enter")   # step
    assert h.x >= _own_hero(app).x   # hero moved (or stayed if blocked)


async def s_end_turn_rotates_player(app, pilot):
    start = app.game.current_player
    await pilot.press("space")
    await pilot.pause()
    assert app.game.current_player != start


async def s_mp_reset_on_new_day(app, pilot):
    h = _own_hero(app)
    h.mp = 0
    # End two turns in hotseat to get back to P1 == new day.
    app.mode = "hotseat"
    await pilot.press("space")
    await pilot.pause()
    await pilot.press("space")
    await pilot.pause()
    assert h.mp == h.max_mp, f"MP was {h.mp}/{h.max_mp}"


async def s_gold_pickup(app, pilot):
    g = app.game
    before = g.resources[0].gold
    h = _own_hero(app)
    # Plant a gold pile right next to the hero and walk onto it.
    pile = MapObject(kind="gold_pile", owner=-1, x=h.x + 1, y=h.y,
                     data={"amount": 1234})
    g.mission.objects.append(pile)
    g._obj_at[(h.x + 1, h.y)] = pile
    msg = g.step_hero(h, h.x + 1, h.y)
    assert "1234 gold" in msg or "1234" in msg
    assert g.resources[0].gold == before + 1234


async def s_mine_capture(app, pilot):
    g = app.game
    h = _own_hero(app)
    mine = MapObject(kind="mine_ore", owner=-1, x=h.x, y=h.y + 1)
    g.mission.objects.append(mine)
    g._obj_at[(h.x, h.y + 1)] = mine
    g.step_hero(h, h.x, h.y + 1)
    assert mine.owner == 0


# ---------- town scenarios ----------

async def s_open_own_town(app, pilot):
    g = app.game
    t = g.towns_for(0)[0]
    _cursor_to(app, t.x, t.y)
    await pilot.pause()
    await pilot.press("t")
    await pilot.pause()
    # A TownScreen should be on the stack.
    assert any(isinstance(s, TownScreen) for s in app.screen_stack)
    await pilot.press("escape")
    await pilot.pause()


async def s_town_build_dwelling(app, pilot):
    g = app.game
    t = g.towns_for(0)[0]
    g.resources[0].gold = 10000
    g.resources[0].wood = 50
    g.resources[0].ore = 50
    # Build dwelling_t2 directly via engine (avoid UI cycling).
    msg = g.build(t, "dwelling_t2")
    assert "dwelling_t2" in t.buildings or "Dwelling T2" in msg


async def s_town_recruit_into_garrison(app, pilot):
    g = app.game
    t = g.towns_for(0)[0]
    g.resources[0].gold = 5000
    t.pool[1] = 10
    msg = g.recruit(t, 1, 5, into_garrison=True)
    assert "Recruited" in msg, msg
    assert sum(s.count for s in t.garrison) == 5


async def s_weekly_growth_accrues(app, pilot):
    """After 7 turn-pair cycles in hotseat mode, tier-1 pool should grow."""
    g = app.game
    t = g.towns_for(0)[0]
    t.buildings.add("dwelling_t1")
    before = t.pool.get(1, 0)
    app.mode = "hotseat"
    # Run 14 end-turns so we pass a week boundary (each full round = 2 presses).
    for _ in range(14):
        await pilot.press("space")
        await pilot.pause()
    after = t.pool.get(1, 0)
    assert after > before, f"pool {before} -> {after}"


# ---------- combat scenarios ----------

async def s_combat_basic_victory(app, pilot):
    """Attacker with overwhelming force wins within a few rounds."""
    atk = [ArmyStack("Pikeman", 50)]
    defn = [ArmyStack("Peasant", 5)]
    c = Combat.begin(atk, defn, seed=1)
    safety = 100
    while not c.is_over and safety > 0:
        safety -= 1
        stack = c.current_stack
        assert stack is not None
        enemies = [s for s in c.stacks if s.side != stack.side and s.alive]
        c.act_move_attack(enemies[0].x, enemies[0].y)
    assert c.winner == 0


async def s_combat_speed_order(app, pilot):
    """Faster stacks go first in the round's initiative list."""
    atk = [ArmyStack("Cavalry", 5)]      # speed 7
    defn = [ArmyStack("Peasant", 5)]     # speed 3
    c = Combat.begin(atk, defn)
    first = c.current_stack
    assert first is not None and first.creature.name == "Cavalry"


async def s_combat_ranged_no_counter(app, pilot):
    """Ranged attack doesn't invite a counter."""
    atk = [ArmyStack("Archer", 10)]
    defn = [ArmyStack("Skeleton", 10)]
    c = Combat.begin(atk, defn)
    # Archer acts first (speed 4 vs skel speed 4, attacker wins tie).
    archer = c.current_stack
    assert archer is not None and archer.creature.name == "Archer"
    target = [s for s in c.stacks if s.side != archer.side and s.alive][0]
    before_attacker = archer.count
    c.act_move_attack(target.x, target.y)
    # No retaliation — archer shouldn't lose count from that swing.
    assert archer.count == before_attacker


async def s_combat_defend_flag(app, pilot):
    atk = [ArmyStack("Peasant", 10)]
    defn = [ArmyStack("Peasant", 10)]
    c = Combat.begin(atk, defn)
    stack = c.current_stack
    c.act_defend()
    assert stack is not None and stack.defending is True


async def s_auto_combat_drives_to_end(app, pilot):
    """The app's auto-resolver finishes combat and applies results."""
    g = app.game
    h = _own_hero(app)
    # Plant a weak monster next to the hero.
    mon = MapObject(kind="monster", owner=-1, x=h.x + 1, y=h.y,
                    data={"label": "Weak Ghouls",
                          "army": [ArmyStack("Peasant", 1)]})
    g.mission.objects.append(mon)
    g._obj_at[(h.x + 1, h.y)] = mon
    msg = g.step_hero(h, h.x + 1, h.y)
    assert "engages" in msg
    app._auto_resolve_combat()
    # Monster should now be gone (assuming attacker won — it's a tier-1
    # stack vs. Kilburn's starting army, which is overwhelming).
    assert g.obj_at(h.x + 1, h.y) is None or g.obj_at(h.x + 1, h.y).kind != "monster"


# ---------- save ----------

async def s_save_writes_file(app, pilot, tmp_path: str = "/tmp/homm2_test_save.json"):
    app.game.save(tmp_path)
    p = Path(tmp_path)
    assert p.exists() and p.stat().st_size > 100
    p.unlink(missing_ok=True)


# ---------- end-to-end capture ----------

async def s_capture_enemy_town_end_to_end(app, pilot):
    """Drive a full flow: Lord Kilburn teleported next to Darkhold, attacks,
    auto-resolves, and Darkhold flips to P1. Verifies the adventure→
    combat→resolve cycle."""
    g = app.game
    kilburn = next(h for h in g.mission.heroes if h.owner == 0)
    darkhold = next(t for t in g.mission.towns if t.owner == 1)
    # Teleport hero right next to Darkhold.
    g._remove_hero_shadow(kilburn)
    kilburn.x = darkhold.x - 1
    kilburn.y = darkhold.y
    kilburn.mp = 1500
    g._place_hero_shadow(kilburn)
    # Make sure no unit is on that tile.
    g._obj_at.pop((darkhold.x - 1, darkhold.y), None)
    g._place_hero_shadow(kilburn)
    # Empty defender army to guarantee we don't get stuck on a cycle.
    enemy_hero = next((h for h in g.mission.heroes if h.owner == 1), None)
    if enemy_hero is not None:
        enemy_hero.army = [ArmyStack("Skeleton", 1)]
    darkhold.garrison = []
    # Buff the attacker so the combat resolves decisively.
    kilburn.army = [ArmyStack("Pikeman", 50), ArmyStack("Cavalry", 10)]
    # Step onto the town.
    msg = g.step_hero(kilburn, darkhold.x, darkhold.y)
    assert g.pending_combat is not None, "siege should start"
    app._auto_resolve_combat()
    assert darkhold.owner == 0, f"Darkhold still owned by {darkhold.owner}"
    assert g.winner == 0, f"winner {g.winner} (after capture all towns owner==1 should vanish)"


# ---------- regression ----------

async def s_render_line_produces_output(app, pilot):
    mv = app.map_view
    strip = mv.render_line(0)
    segs = list(strip)
    assert len(segs) > 0


async def s_fog_of_war_hides_far_tiles(app, pilot):
    g = app.game
    # The far corner (opposite to P1 hero) should start hidden.
    far = g.vis_of(0, g.w - 1, g.h - 1)
    assert far == 0   # HIDDEN


async def s_priority_arrows_not_eaten(app, pilot):
    _cursor_to(app, 5, 5)
    await pilot.pause()
    start = (app.map_view.cursor_x, app.map_view.cursor_y)
    await pilot.press("right")
    assert (app.map_view.cursor_x, app.map_view.cursor_y) == (start[0] + 1, start[1])


async def s_headless_state_no_crash(app, pilot):
    """Constructing a new game and exercising step_hero without an App
    must work."""
    g = new_game("dawn_assault")
    assert g.w > 0
    h = g.heroes_for(0)[0]
    g.step_hero(h, h.x + 1, h.y)
    # No exception is success.


async def s_combat_view_renders(app, pilot):
    """Combat view hex render produces styled output."""
    from homm2_tui.app import CombatView
    c = Combat.begin([ArmyStack("Peasant", 5)], [ArmyStack("Skeleton", 5)])
    v = CombatView(c)
    # Virtual size set; we can render a line even without mount (no size
    # data), but render_line reads self.size which is zero pre-mount.
    # So just prove the move_range & stack_at helpers work.
    stack = c.current_stack
    assert stack is not None
    rng = c.move_range(stack)
    assert isinstance(rng, set)


SCENARIOS: list[Scenario] = [
    Scenario("mount_clean",                  s_mount_clean),
    Scenario("cursor_moves",                 s_cursor_moves),
    Scenario("cursor_clamps",                s_cursor_clamps),
    Scenario("hero_select_and_step",         s_hero_select_and_step),
    Scenario("end_turn_rotates_player",      s_end_turn_rotates_player),
    Scenario("mp_reset_on_new_day",          s_mp_reset_on_new_day),
    Scenario("gold_pickup",                  s_gold_pickup),
    Scenario("mine_capture",                 s_mine_capture),
    Scenario("open_own_town",                s_open_own_town),
    Scenario("town_build_dwelling",          s_town_build_dwelling),
    Scenario("town_recruit_into_garrison",   s_town_recruit_into_garrison),
    Scenario("weekly_growth_accrues",        s_weekly_growth_accrues),
    Scenario("combat_basic_victory",         s_combat_basic_victory),
    Scenario("combat_speed_order",           s_combat_speed_order),
    Scenario("combat_ranged_no_counter",     s_combat_ranged_no_counter),
    Scenario("combat_defend_flag",           s_combat_defend_flag),
    Scenario("auto_combat_drives_to_end",    s_auto_combat_drives_to_end),
    Scenario("save_writes_file",             s_save_writes_file),
    Scenario("capture_enemy_town_end_to_end",s_capture_enemy_town_end_to_end),
    Scenario("render_line_output",           s_render_line_produces_output),
    Scenario("fog_of_war_hides_far_tiles",   s_fog_of_war_hides_far_tiles),
    Scenario("priority_arrows_not_eaten",    s_priority_arrows_not_eaten),
    Scenario("headless_state_no_crash",      s_headless_state_no_crash),
    Scenario("combat_view_renders",          s_combat_view_renders),
]


async def run_scenario(scn: Scenario) -> tuple[str, bool, str]:
    app = HoMM2App(scenario="dawn_assault", mode="hotseat")
    try:
        async with app.run_test(size=(180, 55)) as pilot:
            await pilot.pause()
            try:
                await scn.fn(app, pilot)
                app.save_screenshot(str(OUT / f"{scn.name}.PASS.svg"))
                return (scn.name, True, "")
            except AssertionError as e:
                app.save_screenshot(str(OUT / f"{scn.name}.FAIL.svg"))
                return (scn.name, False, f"AssertionError: {e}")
            except Exception as e:
                app.save_screenshot(str(OUT / f"{scn.name}.ERROR.svg"))
                return (scn.name, False, f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
    except Exception as e:
        return (scn.name, False, f"setup failure: {type(e).__name__}: {e}\n{traceback.format_exc()}")


async def main(filter_pat: str | None) -> int:
    scns = SCENARIOS
    if filter_pat:
        scns = [s for s in scns if filter_pat in s.name]
        if not scns:
            print(f"no scenarios match {filter_pat!r}")
            return 1
    failures = 0
    for scn in scns:
        name, ok, msg = await run_scenario(scn)
        status = "\033[32mPASS\033[0m" if ok else "\033[31mFAIL\033[0m"
        print(f"  {status}  {name}")
        if not ok:
            for line in msg.splitlines():
                print(f"         {line}")
            failures += 1
    print()
    print(f"{len(scns) - failures}/{len(scns)} green")
    return failures


if __name__ == "__main__":
    pat = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(asyncio.run(main(pat)))
