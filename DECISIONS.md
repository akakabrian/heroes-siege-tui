# HoMM2 TUI — Design Decisions

Judgment calls made during the build. Follow-up readers: see skill
`tui-game-build` section 2 binding tree — this project is pattern **4**
(clean-room Python reimplementation). Siblings for reference:
`crimson-fields-tui` (hex combat), `freeorion-tui` (strategic queue),
`julius-tui` (tile overworld).

## 1. Licensing — clean-room reimpl, not fheroes2 wrap

The canonical open-source engine is
[**fheroes2**](https://github.com/ihhub/fheroes2) (GPL-3.0, very active,
~6k stars). It's a C++ reimplementation of HoMM2 that *requires* the
original Ubisoft game data (DEMO or full).

**Options considered:**
1. **Re-shell fheroes2 over PTY + pyte.** Rejected: fheroes2 is SDL2-
   coupled with a full graphical UI — it doesn't render ANSI to stdout,
   so `pyte` has nothing to parse. Running under SDL→framebuffer→screen-
   scrape is fragile and asset-gated (user must supply `HOMM2.GOG`).
2. **SWIG bindings to fheroes2.** Rejected: the engine has no platform
   layer to swap; input and render are intertwined with SDL callbacks.
3. **Clean-room Python reimpl.** *Chosen.* Write original rules + content
   in Python. Legally clean (no Ubisoft data, no copied fheroes2 code),
   ships standalone.

**Reference-only:** we may *read* the fheroes2 source to check HoMM2-
shaped mechanics (growth rates, speed values, spell effects) — but every
constant and table in this repo is our own choice, not a copy.

## 2. Scope — aggressive MVP

The full HoMM2 has 6 factions × 6 creature tiers × towns × combat ×
spells × heroes × scenarios. We ship a vertical slice that reads as
HoMM2 but fits in one session:

**In v0 (stages 1-5):**
- **2 factions** (Knight, Necromancer) — canonical thematic opposition.
- **4 creature types per faction** (tiers 1-4 approx).
- **30×20 adventure map**, 1 scenario.
- **1 town per player**, basic build queue (5 buildings), creature
  purchase.
- **1 hero per player**, recruitable at tavern, 4 primary stats, army of
  up to 5 stacks.
- **Hex tactical combat**, 11×9 grid, turn order by speed, melee +
  ranged + wait/defend. No spells in v0.
- **3 resources**: gold, wood, ore (drop crystal/gems/sulfur/mercury).
- **Mines + treasure piles** as map objects.
- **Fog of war**: per-player visibility, revealed by hero's sight range.
- **Win**: capture enemy town.
- **Hotseat + stub AI** (same 'end turn' or 'greedy march-to-enemy').

**Stubbed / deferred:**
- Spells + magic guild — placeholder tier list; pressing `s` logs
  "unavailable in v0".
- 4 additional factions — data stubs with faction-token colors, no
  unique units.
- Artifacts, secondary skills, hero level-up cards — tracked in the hero
  struct (empty lists) but no UI.
- Save/load — Phase E if time permits; json dump of dataclasses.
- Sound + animation — Phase D/F, optional.

## 3. Adventure map — tile grid, 30×20

HoMM2 uses a 2D tile grid (NOT hex) for the overworld. Each tile is one
glyph. Hero moves orthogonally + diagonally, 1 tile/action, movement
points deducted per step by terrain cost.

**Tile classes:** `grass`, `dirt`, `water`, `tree`, `mountain`, `rock`,
`sand`, `road`. Plus **objects**: `mine_ore`, `mine_wood`, `gold_pile`,
`hero_red`, `hero_blue`, `town_red`, `town_blue`, `town_neutral`,
`monster`, `chest`.

**Movement points:** grass=100, road=75, sand=150, dirt=100, etc.
Standard-issue hero max MP = 1500 (→ ~15 grass tiles/day).

**Fog of war:** `visibility[player][y][x] ∈ {hidden, seen, visible}`.
Seen tiles render dim; hidden tiles render as `▓` in slate grey.

**Rendering:** 1-cell per tile; two-glyph "stamps" for objects where
alignment permits by using a prime-hash to vary glyph (skill rule 2, but
tile grid so no odd-col stagger). Cursor highlighted via inverse fg/bg.

## 4. Combat — hex grid, 11×9 (classic HoMM2 dims)

Reuse the crimson-fields-tui hex math directly (odd-q offset, 2-wide
hex). Our direction semantics mirror theirs; only adjustment is bounds
(11×9 vs. ~16×12 Crimson maps).

**Stacks, not individuals.** Each stack has a creature type + count. A
stack attacking does `count × damage_roll` per swing.

**Turn order.** Sort all alive stacks by speed descending; within speed,
attacker wins the tie. Each stack acts once per round.

**Actions:** `move`, `attack` (melee adjacent or ranged any), `wait`
(defer to end of round at same speed), `defend` (skip, +30% defence).

**Ranged.** Tier-3+ creatures may have `shots > 0`. Ranged attack at
range > 1 is valid; melee stacks get no counterattack if hit at range.
Half-damage penalty beyond range 5 (classic rule).

**Morale / luck.** Stubbed to constant 1.0 multiplier in v0.

**Combat ends** when all of one side's stacks are dead. Victor keeps
the map position; loser hero (if present) is removed and its army
destroyed.

## 5. Towns — build queue, creature purchase

**Buildings per town (5 in v0):**
- `town_hall` — +500 gold/day (built turn 1).
- `tavern` — enables hero recruit; cost 500 g + 5 wood.
- `castle_walls` — +30% defender bonus in town siege; 5000 g + 20 wood + 20 ore.
- `magic_guild_1` — placeholder for spells; 2000 g + 5 wood + 5 ore.
- `creature_dwelling_t1..t4` — each dwelling unlocks weekly growth of
  that tier. Cost scales by tier: 400/1000/2000/5000 g plus wood/ore.

**One build per day.** Button is greyed out after build. Weekly
creature growth = base growth (e.g. Peasant = 12/week) accrues every
7th day; unpurchased creatures persist and compound.

**Creature purchase:** spend gold (and maybe ore/wood) to recruit
available stacks into the town's **garrison** (a 5-slot army that
defends the town). A hero visiting the town can transfer stacks between
his army and the garrison.

## 6. Heroes — simple stats

`attack`, `defense`, `spell_power`, `knowledge` (stubbed; no spells yet).
Starting hero has 3-5 tier-1 creatures. Recruited via tavern for 2500 g.
Max 1 hero per player in v0 (a simplification — real HoMM2 allows many).

**Army slots:** up to 5 stacks, each `(creature_type, count)`.

**Movement points:** 1500/day base + small terrain bonus if starting on
road. Reset every morning (= every `end_turn` cycle rolls back to P1).

## 7. UI — four-pane app, modal combat

**Adventure pane** is default. Keys `hjkl` / arrows move **cursor**
(not hero). ENTER over own hero selects it; subsequent ENTER on an
adjacent tile issues a one-tile move. On entering a mine/chest/monster
tile, interact; on entering enemy town, enter siege (combat).

**Modal combat screen** (`CombatScreen`) opens when a battle begins
and blocks the adventure map. Combat is its own key scheme: arrows
move the selected stack's cursor, ENTER attack/move, `w` wait, `d`
defend, `r` retreat (aborts combat; hero loses).

**Town screen** (`TownScreen`) opens when ENTER on a town we own;
shows buildings, garrison, recruit queue.

**Side panel:** current hero stats, resources, turn/day/week,
event log.

## 8. Hex rendering (combat) — 2×2 blocks, same as Crimson

Reuse the exact approach: `HEX_W=2`, `HEX_H=2`, odd columns shifted
down 1 screen row. Cursor inverts fg/bg; move-range highlighted via
background shade lift. See `crimson_tui/app.py::MapView` for the
render loop — our `CombatView` is near-identical.

## 9. Save / Load — json, Phase E

`dataclasses.asdict` + `json.dump`. Creature types + hero types are
module-level constants, so we only save indices, not the content. Load
path reads indices and re-binds. Verified by re-running sim a few ticks
and diffing state.

## 10. No vendor tree

There's no upstream to vendor — we don't need fheroes2's C++ and don't
ship Ubisoft's data. `make bootstrap` is a no-op. This is a plain
Python project; `make venv` + `make run` is the whole install.

## 11. Scenario design

One scenario "Dawn Assault": P1 (Knight, red) in NW corner town
Greyspire, P2 (Necromancer, blue) in SE corner town Darkhold. Gold
pile + ore mine in neutral centre. One neutral monster stack guarding
a treasure in the middle. Goal: capture enemy town.

Hand-authored in `heroes_siege_tui/scenarios.py`; no file parsing.
