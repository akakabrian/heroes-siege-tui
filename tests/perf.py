"""Hot-path micro-benchmarks for heroes-siege-tui.

Prints mean / p95 / p99 timings for: adventure render_line, combat
render_line, combat engine `act_move_attack`, hero movement range
computation, full end_turn. Uses only the stdlib.
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path


def bench(name: str, fn, iters: int = 200) -> None:
    samples = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    mean = statistics.mean(samples)
    p95 = samples[int(iters * 0.95)] if iters >= 20 else samples[-1]
    p99 = samples[int(iters * 0.99)] if iters >= 100 else samples[-1]
    print(f"  {name:<40} mean={mean:7.3f}ms  p95={p95:7.3f}ms  p99={p99:7.3f}ms")


def main() -> int:
    from heroes_siege_tui.combat import Combat
    from heroes_siege_tui.game import ArmyStack
    from heroes_siege_tui.scenarios import new_game

    print("heroes-siege-tui perf bench")
    print("----------------------")

    # Adventure-map render. We can render lines without mounting the App
    # because AdventureView only relies on self.size at render time.
    from heroes_siege_tui.app import AdventureView
    g = new_game("dawn_assault")
    av = AdventureView(g)
    # Spoof size.
    from textual.geometry import Size
    av._size = Size(60, 20)  # type: ignore[attr-defined]

    def adv_render_all():
        for y in range(g.h):
            av.render_line(y)

    bench("adventure render full map", adv_render_all, iters=100)

    # Combat render.
    from heroes_siege_tui.app import CombatView
    c = Combat.begin([ArmyStack("Pikeman", 50)], [ArmyStack("Skeleton", 50)])
    cv = CombatView(c)
    cv._size = Size(24, 20)  # type: ignore[attr-defined]

    def combat_render_all():
        for y in range(20):
            cv.render_line(y)

    bench("combat render 20 rows", combat_render_all, iters=200)

    # Combat engine step.
    def combat_step():
        cc = Combat.begin([ArmyStack("Pikeman", 20)], [ArmyStack("Peasant", 20)])
        safety = 50
        while not cc.is_over and safety > 0:
            safety -= 1
            stack = cc.current_stack
            if stack is None:
                break
            enemies = [s for s in cc.stacks if s.side != stack.side and s.alive]
            cc.act_move_attack(enemies[0].x, enemies[0].y)

    bench("full combat resolve", combat_step, iters=80)

    # Engine end_turn.
    def end_turn_bench():
        g2 = new_game("dawn_assault")
        for _ in range(14):
            g2.end_turn()

    bench("end_turn x 14", end_turn_bench, iters=80)

    return 0


if __name__ == "__main__":
    sys.exit(main())
