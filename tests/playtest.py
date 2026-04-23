"""End-to-end playtest via Textual Pilot.

Boots the app, moves the hero's cursor, opens the town, recruits, quits.
Exits 0 on success, non-zero on any unexpected error.

    python -m tests.playtest
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from pathlib import Path

from homm2_tui.app import HoMM2App, TownScreen

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)


async def _run() -> int:
    app = HoMM2App(scenario="dawn_assault", mode="ai")
    async with app.run_test(size=(160, 48)) as pilot:
        # Mount sanity.
        assert app.map_view is not None
        assert app.status_panel is not None

        # Move cursor onto own hero.
        hero = app.game.heroes_for(app.game.current_player)[0]
        app.map_view.cursor_x = hero.x
        app.map_view.cursor_y = hero.y
        await pilot.pause()

        # Select hero (ENTER).
        await pilot.press("enter")
        await pilot.pause()
        assert app._selected_hero is hero, "hero should be selected"

        # Move cursor one step east and take a step.
        app.map_view.cursor_x = hero.x + 1
        app.map_view.cursor_y = hero.y
        await pilot.press("enter")
        await pilot.pause()

        # Visit the player's town: jump cursor there and press 't'.
        town = next(t for t in app.game.mission.towns
                    if t.owner == app.game.current_player)
        app.map_view.cursor_x = town.x
        app.map_view.cursor_y = town.y
        await pilot.press("t")
        await pilot.pause()
        assert isinstance(app.screen, TownScreen), "town screen should open"

        # Try one recruit tick (ignore failure — budget may be zero).
        await pilot.press("plus")
        await pilot.pause()
        await pilot.press("enter")  # apply
        await pilot.pause()

        # Close town.
        await pilot.press("escape")
        await pilot.pause()

        # Screenshot for the record.
        app.save_screenshot(str(OUT / "playtest.svg"))

        # Quit.
        await pilot.press("q")
        await pilot.pause()
    return 0


def main() -> int:
    try:
        return asyncio.run(_run())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
