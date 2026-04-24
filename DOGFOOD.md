# DOGFOOD — homm2

_Session: 2026-04-23T13:19:29, driver: pty, duration: 3.0 min_

**PASS** — ran for 2.0m, captured 10 snap(s), 1 milestone(s), 0 blocker(s), 0 major(s).

## Summary

Ran a rule-based exploratory session via `pty` driver. Found no findings worth flagging. Game reached 89 unique state snapshots. Captured 1 milestone shot(s); top candidates promoted to `screenshots/candidates/`.

## Findings

### Blockers

_None._

### Majors

_None._

### Minors

_None._

### Nits

_None._

### UX (feel-better-ifs)

_None._

## Coverage

- Driver backend: `pty`
- Keys pressed: 1083 (unique: 64)
- State samples: 89 (unique: 89)
- Score samples: 0
- Milestones captured: 1
- Phase durations (s): A=83.1, B=16.0, C=18.0
- Snapshots: `/home/brian/AI/projects/tui-dogfood/reports/snaps/homm2-20260423-131729`

Unique keys exercised: +, ,, -, ., /, 0, 1, 2, 3, 4, 5, :, ;, =, ?, B, H, R, [, ], a, b, backspace, c, ctrl+l, d, delete, down, e, end, enter, escape, f1, f2, h, home, j, k, l, left ...

## Milestones

| Event | t (s) | Interest | File | Note |
|---|---|---|---|---|
| first_input | 0.4 | 0.0 | `homm2-20260423-131729/milestones/first_input.txt` | key=up |
