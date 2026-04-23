# homm2-tui — Heroes of Might & Magic II in the terminal

A clean-room Python reimplementation of the 1996 New World Computing
classic, rendered as a Textual TUI. Adventure map + hex tactical
combat + town management, keyboard-driven, 1v1 scenario playable
start-to-finish in the shell.

Not a wrapper around fheroes2 — see `DECISIONS.md` for why (short
version: fheroes2 is SDL-coupled and needs the original Ubisoft data).
Instead: our own rules, our own constants, HoMM2-shaped gameplay.

## Quick start

```
make all           # creates .venv, installs textual
make run           # launches the one scenario — "Dawn Assault"
make test          # runs the QA harness + perf bench
```

## Keys (adventure map)

| key              | action                                              |
|------------------|-----------------------------------------------------|
| arrows / `hjkl`  | move cursor one tile                                |
| `yubn`           | diagonal cursor moves                               |
| ENTER            | select hero / step toward cursor / enter town      |
| `t`              | open own town (when cursor is on it)                |
| SPACE            | end turn                                            |
| `s`              | save to `homm2_save.json`                            |
| `?`              | help                                                |
| `q`              | quit                                                |

## Keys (combat)

| key              | action                                              |
|------------------|-----------------------------------------------------|
| arrows / `hjkl`  | move hex cursor                                     |
| `yubn`           | hex diagonals (per-column stagger aware)            |
| ENTER            | move to / attack at cursor                          |
| `w`              | wait (defer until end of round)                     |
| `d`              | defend (+30% defence, skip action)                  |
| ESC              | retreat (attacker loses, hero removed)              |

## Keys (town)

| key              | action                                              |
|------------------|-----------------------------------------------------|
| `b` / `B`        | cycle building selection                            |
| `1`-`4`          | pick creature tier                                  |
| `+` / `-`        | +/− recruit count                                   |
| ENTER            | build highlighted building, or buy selected stack   |
| `r`              | recruit hero at tavern (2500 g)                     |
| ESC              | close town screen                                   |

## Scope

Shipped v0 covers stages 1-5 of the `tui-game-build` skill + basic polish:

- 2 factions (Knight vs. Necromancer), 4 creature tiers each
- 30×20 adventure map with one hand-authored scenario
- Hex combat engine with speed-order initiative, melee + ranged, wait /
  defend, damage + retaliation
- Town build queue (5 buildings), weekly creature growth, recruit
- 1 hero per side, army of up to 5 stacks, 4 primary stats
- 3 resources (gold, wood, ore), daily town income + mine capture
- Fog of war, revealed by hero sight radius
- Save to json
- Stub AI (greedy march-to-enemy) or hotseat (`--hotseat` flag)

Out of scope for v0 (documented in `DECISIONS.md`):

- 4 other factions (Barbarian, Sorceress, Warlock, Wizard)
- Spells + magic guild (placeholder only)
- Artifacts, secondary skills, level-ups
- Multiple scenarios, random maps
- Sound, animation, LLM advisor

## Tests

`make test` runs 24 scenarios via `App.run_test()` + Textual's `Pilot`,
plus a hot-path perf bench. All scenarios green on current main.
Screenshots land in `tests/out/`.
