"""Hex math for the tactical combat grid — odd-q offset, flat-top.

Identical shape to crimson-fields-tui's hex.py (we reuse the same
coordinate system because the 2×2 block render approach works well in
the terminal and the math is straightforward).

Direction numbering: 0=N, 1=NE, 2=SE, 3=S, 4=SW, 5=NW. We only use the
6 hex directions; no WEST/EAST legacy entries.
"""

from __future__ import annotations

from typing import NamedTuple


NORTH, NORTHEAST, SOUTHEAST, SOUTH, SOUTHWEST, NORTHWEST = 0, 1, 2, 3, 4, 5
DIR_NAMES = ["N", "NE", "SE", "S", "SW", "NW"]


# Offsets keyed by (col_parity, dir). Even columns: NE/SE/SW/NW lean up.
NEIGHBOUR: dict[tuple[int, int], tuple[int, int]] = {
    (0, NORTH):     ( 0, -1),
    (0, NORTHEAST): (+1, -1),
    (0, SOUTHEAST): (+1,  0),
    (0, SOUTH):     ( 0, +1),
    (0, SOUTHWEST): (-1,  0),
    (0, NORTHWEST): (-1, -1),
    (1, NORTH):     ( 0, -1),
    (1, NORTHEAST): (+1,  0),
    (1, SOUTHEAST): (+1, +1),
    (1, SOUTH):     ( 0, +1),
    (1, SOUTHWEST): (-1, +1),
    (1, NORTHWEST): (-1,  0),
}


class Point(NamedTuple):
    x: int
    y: int


def distance(s: Point, t: Point) -> int:
    sx, sy, tx, ty = s.x, s.y, t.x, t.y
    x1 = sy - (sx // 2)
    y1 = sy + ((sx + 1) // 2)
    x2 = ty - (tx // 2)
    y2 = ty + ((tx + 1) // 2)
    dx = x2 - x1
    dy = y2 - y1
    same_sign = (dx >= 0) == (dy >= 0)
    if same_sign:
        return max(abs(dx), abs(dy))
    return abs(dx) + abs(dy)


def neighbours(p: Point) -> list[Point]:
    parity = p.x & 1
    return [Point(p.x + dx, p.y + dy)
            for dx, dy in (NEIGHBOUR[(parity, d)] for d in range(6))]


def in_bounds(p: Point, w: int, h: int) -> bool:
    return 0 <= p.x < w and 0 <= p.y < h
