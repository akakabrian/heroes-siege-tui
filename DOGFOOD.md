# DOGFOOD — homm2

_Session: 2026-04-23T14:39:22, driver: pty, duration: 1.5 min_

**PASS** — ran for 1.1m, captured 7 snap(s), 1 milestone(s), 0 blocker(s), 0 major(s).

## Summary

Ran a rule-based exploratory session via `pty` driver. Found no findings worth flagging. Game reached 74 unique state snapshots. Captured 1 milestone shot(s); top candidates promoted to `screenshots/candidates/`.

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
- Keys pressed: 663 (unique: 64)
- State samples: 74 (unique: 74)
- Score samples: 0
- Milestones captured: 1
- Phase durations (s): A=41.0, B=16.0, C=9.0
- Snapshots: `/home/brian/AI/projects/tui-dogfood/reports/snaps/homm2-20260423-143814`

Unique keys exercised: +, ,, -, ., /, 0, 1, 2, 3, 4, 5, :, ;, =, ?, B, H, R, [, ], a, b, backspace, c, ctrl+l, d, delete, down, e, end, enter, escape, f1, f2, h, home, j, k, l, left ...

## Milestones

| Event | t (s) | Interest | File | Note |
|---|---|---|---|---|
| first_input | 0.4 | 0.0 | `homm2-20260423-143814/milestones/first_input.txt` | key=up |
