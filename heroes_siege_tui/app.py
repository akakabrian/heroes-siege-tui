"""Textual application — adventure map + town + combat screens.

Layout:

    +-----------------------------------------+---------------------+
    |                                         |                     |
    |          AdventureView                  |   Status panel      |
    |   (30×20 tile grid; hero/town/fog)      |   (hero, resources, |
    |                                         |    turn/day)        |
    +-----------------------------------------+                     |
    |  Log                                    |                     |
    +-----------------------------------------+---------------------+

Keys (adventure):
  arrows / hjkl / yubn   move cursor
  ENTER                  select hero (or move selected hero one step
                         toward the cursor; or enter town/combat when
                         the cursor is on one)
  SPACE                  end turn
  t                      open town (if cursor on own town)
  ?                      help
  q                      quit

Modal screens (`TownScreen`, `CombatScreen`) use `+`/`-`/letter keys so
they don't collide with the priority arrow bindings.
"""

from __future__ import annotations

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.geometry import Region, Size
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Footer, Header, RichLog, Static

from . import tiles
from .combat import COMBAT_H, COMBAT_W, Combat, CombatStack
from .content import (BUILDINGS, BUILD_ORDER, CREATURES, FACTIONS,
                      HEROES, creatures_for, tavern_pool_for)
from .game import (HIDDEN, SEEN, VISIBLE, ArmyStack, GameState, Hero,
                   MapObject, Town)
from .hex import Point, distance as hex_distance, neighbours as hex_neighbours, in_bounds
from .scenarios import new_game


# --- style cache --------------------------------------------------------


_STYLE_CACHE: dict[tuple[str, str, bool], Style] = {}


def cstyle(fg: str, bg: str, bold: bool = False) -> Style:
    key = (fg, bg, bold)
    s = _STYLE_CACHE.get(key)
    if s is None:
        s = Style(color=f"rgb({fg})", bgcolor=f"rgb({bg})", bold=bold)
        _STYLE_CACHE[key] = s
    return s


def dim_rgb(fg: str, f: float = 0.5) -> str:
    r, g, b = (int(c) for c in fg.split(","))
    return f"{int(r*f)},{int(g*f)},{int(b*f)}"


# --- adventure map widget ----------------------------------------------


class AdventureView(ScrollView):
    """30×20 tile grid, one cell per tile."""

    cursor_x: reactive[int] = reactive(0)
    cursor_y: reactive[int] = reactive(0)
    selected_hid: reactive[int] = reactive(-1)

    def __init__(self, game: GameState) -> None:
        super().__init__()
        self.game = game
        self.virtual_size = Size(game.w, game.h)
        # Start cursor on own first hero.
        own = game.heroes_for(game.current_player)
        if own:
            self.cursor_x = own[0].x
            self.cursor_y = own[0].y

    def watch_cursor_x(self) -> None:
        if self.is_mounted:
            self.refresh()

    def watch_cursor_y(self) -> None:
        if self.is_mounted:
            self.refresh()

    def watch_selected_hid(self) -> None:
        if self.is_mounted:
            self.refresh()

    def render_line(self, y: int) -> Strip:
        game = self.game
        scroll_x = int(self.scroll_offset.x)
        width = self.size.width
        player = game.current_player

        segments: list[Segment] = []
        x = scroll_x
        while x < scroll_x + width:
            if not (0 <= x < game.w) or not (0 <= y < game.h):
                segments.append(Segment(" ", cstyle("40,40,40", "8,10,14")))
                x += 1
                continue
            vis = game.vis_of(player, x, y)
            terrain = game.tile_class(x, y)
            v = tiles.terrain_style(terrain)
            glyph = tiles.terrain_glyph(terrain, x, y)
            fg = v["fg"]
            bg = v["bg"]

            obj = game.obj_at(x, y)
            if obj is not None and vis != HIDDEN:
                og, ofg = tiles.obj_glyph(obj.kind)
                glyph = og
                if obj.kind in ("hero", "town"):
                    fg = tiles.FACTION_COLOR.get(obj.owner, "180,180,180")
                else:
                    fg = ofg

            if vis == HIDDEN:
                glyph = "▓"
                fg = "30,30,36"
                bg = "6,6,10"
            elif vis == SEEN:
                fg = dim_rgb(fg, 0.5)
                bg = dim_rgb(bg, 0.7)

            if x == self.cursor_x and y == self.cursor_y:
                bg = "150,120,50"
                fg = "255,230,120"

            segments.append(Segment(glyph, cstyle(fg, bg, bold=(obj is not None))))
            x += 1

        if not segments:
            segments = [Segment(" " * width, cstyle("40,40,40", "8,10,14"))]
        return Strip(segments).crop(0, width)


# --- side panels --------------------------------------------------------


class StatusPanel(Static):
    """Right-side status: hero, resources, day/week, cursor info."""

    def __init__(self, game: GameState) -> None:
        super().__init__("", classes="panel")
        self.game = game

    def refresh_panel(self, cursor: tuple[int, int], selected_hid: int) -> None:
        g = self.game
        p = g.current_player
        week = (g.turn - 1) // 7 + 1
        day = (g.turn - 1) % 7 + 1
        r = g.resources[p]
        faction_key = ["knight", "necromancer"][p] if p < 2 else "knight"
        lines = [
            "[b yellow]▌ HoMM II — TUI ▐[/]",
            f"Day {day} · Week {week} · Turn {g.turn}",
            f"Player: [b]P{p + 1}[/] ({FACTIONS[faction_key].name})",
            "",
            "[b]Resources[/]",
            f"  Gold: {r.gold}",
            f"  Wood: {r.wood}   Ore: {r.ore}",
            "",
            f"Cursor: ({cursor[0]}, {cursor[1]})",
        ]
        obj = g.obj_at(cursor[0], cursor[1])
        if obj is not None:
            lines.append(f"  {obj.kind}"
                         + (f" (P{obj.owner+1})" if obj.owner >= 0 else " (neutral)"))
            if obj.kind == "town":
                town = g.town_at(cursor[0], cursor[1])
                if town is not None:
                    lines.append(f"  {town.name} — {town.faction}")
        h = g.hero_at(cursor[0], cursor[1])
        if h is not None:
            lines += [
                "",
                f"[b cyan]{h.name}[/] (P{h.owner + 1})",
                f"  MP: {h.mp}/{h.max_mp}",
                f"  A/D/SP/K: {h.attack}/{h.defense}/{h.spell_power}/{h.knowledge}",
                "  Army:",
            ]
            for s in h.army:
                c = CREATURES.get(s.creature)
                if c is not None:
                    lines.append(f"    {s.count:>4}x {s.creature}")
        if selected_hid >= 0:
            sh = next((h for h in g.mission.heroes if h.hid == selected_hid), None)
            if sh is not None:
                lines += ["", f"[b yellow]Selected:[/] {sh.name} (mp {sh.mp})"]
        lines += ["",
                  f"Own towns: {len(g.towns_for(p))}",
                  f"Own heroes: {len(g.heroes_for(p))}"]
        if g.winner is not None:
            lines += ["", f"[b yellow]VICTORY: P{g.winner + 1}[/]"]
        self.update("\n".join(lines))


class HelpPanel(Static):
    TEXT = (
        "[b]Keys[/]\n"
        "[yellow]←→↑↓[/] / [yellow]hjkl[/]  cursor\n"
        "[yellow]yubn[/]           diagonals\n"
        "[yellow]ENTER[/]          select/move/\n"
        "                 enter site\n"
        "[yellow]t[/]              open town\n"
        "[yellow]ESC[/]            cancel select\n"
        "[yellow]SPACE[/]          end turn\n"
        "[yellow]s[/]              save game\n"
        "[yellow]?[/]              help\n"
        "[yellow]q[/]              quit\n"
    )

    def __init__(self) -> None:
        super().__init__(self.TEXT, classes="panel")


# --- town modal ---------------------------------------------------------


class TownScreen(ModalScreen):
    """Town management modal — build queue + recruit + tavern."""

    BINDINGS = [
        Binding("escape", "close",  priority=True, show=True, description="Close"),
        Binding("b",      "cycle_build(1)",  priority=True, show=True, description="Next build"),
        Binding("B",      "cycle_build(-1)", priority=True, show=False),
        Binding("enter",  "apply",  priority=True, show=True, description="Apply/buy"),
        Binding("+",      "recruit(1)",  priority=True, show=False),
        Binding("-",      "recruit(-1)", priority=True, show=False),
        Binding("r",      "recruit_hero", priority=True, show=True, description="Tavern"),
        Binding("tab",    "cycle_tier(1)",  priority=True, show=False),
        Binding("1",      "pick_tier(1)", priority=True, show=False),
        Binding("2",      "pick_tier(2)", priority=True, show=False),
        Binding("3",      "pick_tier(3)", priority=True, show=False),
        Binding("4",      "pick_tier(4)", priority=True, show=False),
    ]

    def __init__(self, game: GameState, town: Town) -> None:
        super().__init__()
        self.game = game
        self.town = town
        self.build_idx = 0
        self.recruit_tier = 1
        self.recruit_count = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="town_box"):
            yield Static("", id="town_title", classes="panel-title")
            yield Static("", id="town_body")

    def on_mount(self) -> None:
        self._refresh()

    def action_close(self) -> None:
        self.app.pop_screen()

    def action_cycle_build(self, delta: int) -> None:
        self.build_idx = (self.build_idx + delta) % len(BUILD_ORDER)
        self._refresh()

    def action_cycle_tier(self, delta: int) -> None:
        self.recruit_tier = ((self.recruit_tier - 1 + delta) % 4) + 1
        self.recruit_count = 0
        self._refresh()

    def action_pick_tier(self, tier: int) -> None:
        self.recruit_tier = tier
        self.recruit_count = 0
        self._refresh()

    def action_apply(self) -> None:
        """ENTER: build the currently highlighted building, OR buy the
        pending recruit count."""
        if self.recruit_count > 0:
            msg = self.game.recruit(self.town, self.recruit_tier,
                                    self.recruit_count, into_garrison=True)
            self.recruit_count = 0
            self._say(msg)
        else:
            bkey = BUILD_ORDER[self.build_idx]
            msg = self.game.build(self.town, bkey)
            self._say(msg)
        self._refresh()

    def action_recruit(self, delta: int) -> None:
        pool = self.town.pool.get(self.recruit_tier, 0)
        self.recruit_count = max(0, min(pool, self.recruit_count + delta))
        self._refresh()

    def action_recruit_hero(self) -> None:
        pool = tavern_pool_for(self.town.faction)
        if not pool:
            self._say("No heroes available.")
            return
        # Pick the first hero matching faction that isn't already on the map.
        existing = {h.class_key for h in self.game.mission.heroes}
        choice = next((h for h in pool if h.key not in existing), pool[0])
        msg = self.game.recruit_hero(self.town, choice.key)
        self._say(msg)
        self._refresh()

    def _say(self, msg: str) -> None:
        parent_app = self.app
        # Forward to main log if available.
        log = getattr(parent_app, "log_panel", None)
        if log is not None:
            log.write(f"[town] {msg}")

    def _refresh(self) -> None:
        g = self.game
        t = self.town
        r = g.resources[t.owner]
        title = self.query_one("#town_title", Static)
        title.update(
            f"[b]{t.name}[/] — {FACTIONS[t.faction].name} "
            f"(Day {g.turn})   [dim]ESC to close[/]"
        )
        body = self.query_one("#town_body", Static)

        lines: list[str] = []
        lines.append(f"[b]Treasury:[/] {r.gold} gold, {r.wood} wood, {r.ore} ore")
        lines.append("")
        lines.append(f"[b]Buildings ({'built today' if t.built_today else 'can build today'}):[/]  "
                     "[dim]b/B to cycle, ENTER to build[/]")
        for i, bkey in enumerate(BUILD_ORDER):
            b = BUILDINGS[bkey]
            marker = ">>" if i == self.build_idx else "  "
            have = "✓" if bkey in t.buildings else " "
            can, _why = g.can_build(t, bkey)
            costs = []
            if b.cost_gold: costs.append(f"{b.cost_gold}g")
            if b.cost_wood: costs.append(f"{b.cost_wood}w")
            if b.cost_ore:  costs.append(f"{b.cost_ore}o")
            cost = " ".join(costs) or "free"
            affordable = "" if can or bkey in t.buildings else "  [red](!)[/]"
            lines.append(f"{marker} [{have}] {b.name:<16} {cost:>14}{affordable}")
        lines.append("")
        lines.append("[b]Recruit[/]  [dim]1-4 tier, +/- count, ENTER buy[/]")
        for tier in range(1, 5):
            c = next((c for c in creatures_for(t.faction) if c.tier == tier), None)
            if c is None:
                continue
            pool = t.pool.get(tier, 0)
            marker = ">>" if tier == self.recruit_tier else "  "
            picked = f"({self.recruit_count})" if tier == self.recruit_tier else ""
            cost = f"{c.cost_gold}g"
            if c.cost_wood: cost += f"+{c.cost_wood}w"
            if c.cost_ore: cost += f"+{c.cost_ore}o"
            lines.append(f"{marker} T{tier} {c.name:<12} {cost:<16} "
                         f"avail: {pool:<3} {picked}")
        lines.append("")
        lines.append("[b]Garrison (defends when no hero):[/]")
        if not t.garrison:
            lines.append("  (empty)")
        for s in t.garrison:
            lines.append(f"  {s.count:>4}x {s.creature}")
        if t.visiting_hid >= 0:
            vh = next((h for h in g.mission.heroes if h.hid == t.visiting_hid), None)
            if vh is not None:
                lines.append("")
                lines.append(f"[b cyan]Visiting hero:[/] {vh.name}")
                for s in vh.army:
                    lines.append(f"  {s.count:>4}x {s.creature}")
        lines.append("")
        lines.append("[dim]r — recruit hero at tavern (2500g)[/]")
        body.update("\n".join(lines))


# --- combat screen ------------------------------------------------------


class CombatView(ScrollView):
    """11x9 hex battlefield — renders with 2-wide blocks, stagger-down
    on odd columns."""

    cursor_x: reactive[int] = reactive(5)
    cursor_y: reactive[int] = reactive(4)

    def __init__(self, combat: Combat) -> None:
        super().__init__()
        self.combat = combat
        # Virtual size: width = COMBAT_W * 2, height = COMBAT_H * 2 + 1.
        self.virtual_size = Size(COMBAT_W * 2, COMBAT_H * 2 + 1)
        self.move_highlight: set[tuple[int, int]] = set()
        self.attack_targets: set[tuple[int, int]] = set()
        self._update_highlights()

    def watch_cursor_x(self) -> None:
        if self.is_mounted:
            self.refresh()

    def watch_cursor_y(self) -> None:
        if self.is_mounted:
            self.refresh()

    def _update_highlights(self) -> None:
        stack = self.combat.current_stack
        if stack is None:
            self.move_highlight = set()
            self.attack_targets = set()
            return
        self.move_highlight = self.combat.move_range(stack)
        self.attack_targets = {(s.x, s.y) for s in self.combat.stacks
                               if s.alive and s.side != stack.side}

    def render_line(self, y: int) -> Strip:
        combat = self.combat
        scroll_x = int(self.scroll_offset.x)
        width = self.size.width

        segments: list[Segment] = []
        hex_x = scroll_x // 2
        x_pixel = hex_x * 2
        while x_pixel < scroll_x + width and hex_x < COMBAT_W:
            parity = hex_x & 1
            raw = y - parity
            in_row = 0 <= raw < COMBAT_H * 2
            if in_row:
                hex_y = raw // 2
                half = raw - hex_y * 2
                chars, style = self._hex_cell(hex_x, hex_y, half)
            else:
                chars, style = "  ", cstyle("60,60,60", "6,6,10")
            left = max(0, scroll_x - x_pixel)
            right = min(2, (scroll_x + width) - x_pixel)
            if left < right:
                segments.append(Segment(chars[left:right], style))
            hex_x += 1
            x_pixel += 2
        if not segments:
            segments = [Segment(" " * width, cstyle("60,60,60", "6,6,10"))]
        return Strip(segments).crop(0, width)

    def _hex_cell(self, hx: int, hy: int, half: int) -> tuple[str, Style]:
        combat = self.combat
        is_cursor = (hx == self.cursor_x and hy == self.cursor_y)
        is_move = (hx, hy) in self.move_highlight
        is_target = (hx, hy) in self.attack_targets
        stack = combat.stack_at(hx, hy)
        current = combat.current_stack

        bg = "16,20,28"
        if is_move:
            bg = "34,44,56"
        if is_target:
            bg = "80,30,30"
        if is_cursor:
            bg = "150,120,50"

        if stack is not None and half == 0:
            fg = "240,90,90" if stack.side == 0 else "120,140,240"
            if current is not None and current.sid == stack.sid:
                fg = "255,230,120"
            glyph = stack.creature.glyph
            content = f"{glyph}{min(99, stack.count):02d}"[:2]
            return content, cstyle(fg, bg, bold=True)
        if stack is not None and half == 1:
            fg = "240,90,90" if stack.side == 0 else "120,140,240"
            return f"{stack.count:>2}"[-2:], cstyle(fg, bg)
        # Empty hex — grid dots.
        return ".·", cstyle("40,45,55", bg)


class CombatScreen(ModalScreen):
    """Modal screen that hosts the combat."""

    BINDINGS = [
        Binding("left",  "move(-1,0)",  priority=True, show=False),
        Binding("right", "move(1,0)",   priority=True, show=False),
        Binding("up",    "move(0,-1)",  priority=True, show=False),
        Binding("down",  "move(0,1)",   priority=True, show=False),
        Binding("h",     "move(-1,0)",  priority=True, show=False),
        Binding("l",     "move(1,0)",   priority=True, show=False),
        Binding("k",     "move(0,-1)",  priority=True, show=False),
        Binding("j",     "move(0,1)",   priority=True, show=False),
        Binding("y",     "hex_dir(5)",  priority=True, show=False),
        Binding("u",     "hex_dir(1)",  priority=True, show=False),
        Binding("b",     "hex_dir(4)",  priority=True, show=False),
        Binding("n",     "hex_dir(2)",  priority=True, show=False),
        Binding("enter", "fire", priority=True, show=True, description="Move/Attack"),
        Binding("w",     "wait", priority=True, show=True, description="Wait"),
        Binding("d",     "defend", priority=True, show=True, description="Defend"),
        Binding("escape", "retreat", priority=True, show=True, description="Retreat"),
    ]

    def __init__(self, game: GameState, combat: Combat) -> None:
        super().__init__()
        self.game = game
        self.combat = combat
        self.view: CombatView | None = None
        self.info: Static | None = None
        self.clog: RichLog | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="combat_box"):
            yield Static("[b]Combat[/]", classes="panel-title", id="combat_title")
            with Horizontal():
                with Vertical(id="combat_left"):
                    self.view = CombatView(self.combat)
                    yield self.view
                    self.clog = RichLog(id="combat_log", max_lines=100, wrap=True, markup=True)
                    yield self.clog
                self.info = Static("", classes="panel", id="combat_info")
                yield self.info

    def on_mount(self) -> None:
        # Snap cursor to current stack.
        if self.view is not None:
            stack = self.combat.current_stack
            if stack is not None:
                self.view.cursor_x = stack.x
                self.view.cursor_y = stack.y
        self._refresh_info()

    def action_move(self, dx: int, dy: int) -> None:
        if self.view is None:
            return
        nx = max(0, min(COMBAT_W - 1, self.view.cursor_x + dx))
        ny = max(0, min(COMBAT_H - 1, self.view.cursor_y + dy))
        self.view.cursor_x = nx
        self.view.cursor_y = ny
        self._refresh_info()

    def action_hex_dir(self, dir_idx: int) -> None:
        if self.view is None:
            return
        from .hex import NEIGHBOUR
        parity = self.view.cursor_x & 1
        dx, dy = NEIGHBOUR[(parity, dir_idx)]
        self.action_move(dx, dy)

    def action_fire(self) -> None:
        """ENTER: move current stack to cursor, or attack enemy there."""
        if self.view is None:
            return
        stack = self.combat.current_stack
        if stack is None:
            return
        msg = self.combat.act_move_attack(self.view.cursor_x, self.view.cursor_y)
        self._after_action(msg)

    def action_wait(self) -> None:
        msg = self.combat.act_wait()
        self._after_action(msg)

    def action_defend(self) -> None:
        msg = self.combat.act_defend()
        self._after_action(msg)

    def action_retreat(self) -> None:
        """Retreat = attacker loss; resolve with empty attacker survivors."""
        if self.combat.winner is None:
            self.combat.winner = 1  # defender wins by retreat
        self._finish()

    def _after_action(self, msg: str) -> None:
        if self.clog is not None and msg:
            self.clog.write(msg)
        if self.view is not None:
            self.view._update_highlights()
            stack = self.combat.current_stack
            if stack is not None:
                self.view.cursor_x = stack.x
                self.view.cursor_y = stack.y
            self.view.refresh()
        self._refresh_info()
        if self.combat.is_over:
            self._finish()

    def _refresh_info(self) -> None:
        if self.info is None:
            return
        c = self.combat
        stack = c.current_stack
        lines = [
            f"[b]Round {c.round}[/]",
            "",
        ]
        if stack is not None:
            side = "[red]Attacker[/]" if stack.side == 0 else "[blue]Defender[/]"
            lines += [
                f"Active: [b]{stack.name}[/] ({side})",
                f"  count {stack.count}/{stack.max_count}",
                f"  speed {stack.creature.speed}  hp {stack.creature.hp}",
                f"  atk {stack.creature.attack}+{stack.hero_attack_bonus}  "
                f"def {stack.creature.defense}+{stack.hero_defense_bonus}",
                f"  shots {stack.shots}",
            ]
        lines += ["", "[b]Armies[/]"]
        for side in (0, 1):
            tag = "[red]A[/]" if side == 0 else "[blue]D[/]"
            for s in c.stacks:
                if s.side != side or not s.alive:
                    continue
                mark = ">>" if (stack and s.sid == stack.sid) else "  "
                lines.append(f"  {mark} {tag} {s.count:>3}x {s.name}")
        lines += ["",
                  "[dim]enter move/attack · w wait · d defend · esc retreat[/]"]
        self.info.update("\n".join(lines))

    def _finish(self) -> None:
        attacker_wins = self.combat.winner == 0
        a_surv = self.combat.survivors(0)
        d_surv = self.combat.survivors(1)
        msg = self.game.resolve_combat(attacker_wins, a_surv, d_surv)
        parent_app = self.app
        log = getattr(parent_app, "log_panel", None)
        if log is not None:
            log.write(f"[b]Combat:[/] {msg}")
            log.write(f"  Attacker {'wins' if attacker_wins else 'loses'} — "
                      f"{len(a_surv)} stacks survive; defender {len(d_surv)}.")
        self.app.pop_screen()


# --- help modal ---------------------------------------------------------


class HelpScreen(ModalScreen):
    BINDINGS = [Binding("escape", "close", priority=True, show=True)]

    def compose(self) -> ComposeResult:
        with Vertical(id="help_box"):
            yield Static("[b yellow]HoMM2 TUI — Help[/]", classes="panel-title")
            yield Static(HelpPanel.TEXT + "\n"
                         "[b]Combat:[/]\n"
                         "  arrows / hjkl / yubn  move cursor\n"
                         "  ENTER  move/attack     w  wait\n"
                         "  d      defend         ESC retreat\n"
                         "\n"
                         "[b]Town:[/]\n"
                         "  b / B  cycle building   ENTER build\n"
                         "  1-4    pick creature tier\n"
                         "  +/-    recruit count    ENTER buy\n"
                         "  r      tavern recruit   ESC close\n",
                         classes="panel")

    def action_close(self) -> None:
        self.app.pop_screen()


# --- main app -----------------------------------------------------------


class HoMM2App(App):
    CSS_PATH = "tui.tcss"

    BINDINGS = [
        Binding("left",  "move(-1,0)",  priority=True, show=False),
        Binding("right", "move(1,0)",   priority=True, show=False),
        Binding("up",    "move(0,-1)",  priority=True, show=False),
        Binding("down",  "move(0,1)",   priority=True, show=False),
        Binding("h",     "move(-1,0)",  priority=True, show=False),
        Binding("l",     "move(1,0)",   priority=True, show=False),
        Binding("k",     "move(0,-1)",  priority=True, show=False),
        Binding("j",     "move(0,1)",   priority=True, show=False),
        Binding("y",     "move(-1,-1)", priority=True, show=False),
        Binding("u",     "move(1,-1)",  priority=True, show=False),
        Binding("b",     "move(-1,1)",  priority=True, show=False),
        Binding("n",     "move(1,1)",   priority=True, show=False),
        Binding("enter", "activate",    priority=True, show=False),
        Binding("escape", "cancel",     priority=True, show=False),
        Binding("space", "end_turn",    priority=True, show=True, description="End turn"),
        Binding("t",     "open_town",   priority=True, show=True, description="Town"),
        Binding("s",     "save",        priority=True, show=True, description="Save"),
        Binding("question_mark", "help", priority=True, show=True, description="Help"),
        Binding("q",     "quit",        priority=True, show=True, description="Quit"),
    ]

    def __init__(self, scenario: str = "dawn_assault", mode: str = "ai") -> None:
        super().__init__()
        self.scenario = scenario
        self.mode = mode
        self.game: GameState = new_game(scenario)
        self.map_view: AdventureView | None = None
        self.status_panel: StatusPanel | None = None
        self.log_panel: RichLog | None = None
        self._selected_hero: Hero | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal():
            with Vertical(id="left"):
                self.map_view = AdventureView(self.game)
                yield self.map_view
                self.log_panel = RichLog(id="bottom_log", max_lines=500,
                                          wrap=True, markup=True)
                yield self.log_panel
            with Vertical(id="right"):
                self.status_panel = StatusPanel(self.game)
                yield self.status_panel
                yield HelpPanel()
        yield Footer()

    def on_mount(self) -> None:
        self.title = "HoMM2 TUI"
        self.sub_title = f"{self.scenario} · P{self.game.current_player + 1}"
        self._refresh_status()
        self._log("[yellow]Welcome to Dawn Assault![/]")
        self._log("Move cursor onto your hero with the arrows and press ENTER to select.")

    # ---- actions ----------------------------------------------------

    def action_move(self, dx: int, dy: int) -> None:
        if self.map_view is None:
            return
        nx = max(0, min(self.game.w - 1, self.map_view.cursor_x + dx))
        ny = max(0, min(self.game.h - 1, self.map_view.cursor_y + dy))
        self.map_view.cursor_x = nx
        self.map_view.cursor_y = ny
        self._refresh_status()

    def action_activate(self) -> None:
        """ENTER:
          - If no hero selected: if cursor on own hero → select it.
                                  if cursor on own town → open town.
          - If hero selected: take one step (adventure map) toward the
            cursor if adjacent; if the cursor is on an adjacent enemy or
            interactable, step onto it (triggering combat / visit).
        """
        if self.map_view is None:
            return
        cx, cy = self.map_view.cursor_x, self.map_view.cursor_y

        if self._selected_hero is None:
            h = self.game.hero_at(cx, cy)
            if h is not None and h.owner == self.game.current_player:
                self._selected_hero = h
                self.map_view.selected_hid = h.hid
                self._log(f"[cyan]Selected {h.name}.[/]")
                self._refresh_status()
                return
            # Town?
            obj = self.game.obj_at(cx, cy)
            if obj is not None and obj.kind == "town" and obj.owner == self.game.current_player:
                town = self.game.town_at(cx, cy)
                if town is not None:
                    self.push_screen(TownScreen(self.game, town))
                return
            self._log("[dim]Nothing to do here.[/]")
            return

        # Try to move the selected hero.
        hero = self._selected_hero
        dx, dy = cx - hero.x, cy - hero.y
        if max(abs(dx), abs(dy)) != 1:
            self._log("[dim]Pick an adjacent tile.[/]")
            return
        msg = self.game.step_hero(hero, cx, cy)
        self._log(msg)

        # Combat pending?
        if self.game.pending_combat is not None:
            self._launch_combat()
            self._selected_hero = None
            self.map_view.selected_hid = -1
        else:
            # Move cursor to new hero position to ease multi-step moves.
            self.map_view.cursor_x = hero.x
            self.map_view.cursor_y = hero.y
        self.map_view.refresh()
        self._refresh_status()

    def _launch_combat(self) -> None:
        pc = self.game.pending_combat
        if pc is None:
            return
        atk = next((h for h in self.game.mission.heroes if h.hid == pc.attacker_hid), None)
        if atk is None:
            return
        def_hero = None
        if pc.defender.kind == "hero":
            def_hero = next((h for h in self.game.mission.heroes
                             if h.hid == pc.defender.hero_hid), None)
        combat = Combat.begin(
            attacker_army=list(atk.army),
            defender_army=list(pc.defender.army),
            attacker_hero=atk,
            defender_hero=def_hero,
            seed=self.game.turn,
        )
        self.push_screen(CombatScreen(self.game, combat))

    def action_cancel(self) -> None:
        self._selected_hero = None
        if self.map_view is not None:
            self.map_view.selected_hid = -1
            self.map_view.refresh()
        self._refresh_status()

    def action_end_turn(self) -> None:
        self.game.end_turn()
        self._log(f"[yellow]— P{self.game.current_player + 1}'s turn "
                  f"(day {self.game.turn}). —[/]")
        self.action_cancel()
        self._refresh_status()
        self.sub_title = f"Day {self.game.turn} · P{self.game.current_player + 1}"
        # Snap cursor to first hero of new player if any.
        if self.map_view is not None:
            own = self.game.heroes_for(self.game.current_player)
            if own:
                self.map_view.cursor_x = own[0].x
                self.map_view.cursor_y = own[0].y
        # Stub AI: if mode is "ai" and current player is 1, take a turn.
        if self.mode == "ai" and self.game.current_player == 1 and self.game.winner is None:
            self.call_after_refresh(self._ai_take_turn)

    def _ai_take_turn(self) -> None:
        from . import ai
        for line in ai.take_turn(self.game):
            self._log(line)
        # If AI triggered a combat, resolve it automatically by picking a
        # simple 'attack current enemy' loop.
        while self.game.pending_combat is not None:
            self._auto_resolve_combat()
        self.game.end_turn()
        self._refresh_status()
        self.sub_title = f"Day {self.game.turn} · P{self.game.current_player + 1}"
        self._log(f"[yellow]— P{self.game.current_player + 1}'s turn "
                  f"(day {self.game.turn}). —[/]")
        if self.map_view is not None:
            self.map_view.refresh()

    def _auto_resolve_combat(self) -> None:
        """Headless combat resolution for stub-AI fights (and for tests).

        Runs a greedy policy: current stack attacks the nearest enemy
        each turn. Terminates when combat.is_over.
        """
        pc = self.game.pending_combat
        if pc is None:
            return
        atk = next((h for h in self.game.mission.heroes if h.hid == pc.attacker_hid), None)
        def_hero = None
        if pc.defender.kind == "hero":
            def_hero = next((h for h in self.game.mission.heroes
                             if h.hid == pc.defender.hero_hid), None)
        if atk is None:
            self.game.resolve_combat(False, [], list(pc.defender.army))
            return
        combat = Combat.begin(
            attacker_army=list(atk.army),
            defender_army=list(pc.defender.army),
            attacker_hero=atk, defender_hero=def_hero,
            seed=self.game.turn,
        )
        safety = 200
        while not combat.is_over and safety > 0:
            safety -= 1
            stack = combat.current_stack
            if stack is None:
                break
            enemies = [s for s in combat.stacks
                       if s.side != stack.side and s.alive]
            if not enemies:
                break
            origin = Point(stack.x, stack.y)
            enemies.sort(key=lambda s: hex_distance(
                origin, Point(s.x, s.y)))
            target = enemies[0]
            combat.act_move_attack(target.x, target.y)
        attacker_wins = combat.winner == 0
        msg = self.game.resolve_combat(attacker_wins,
                                        combat.survivors(0),
                                        combat.survivors(1))
        self._log(f"[b]Auto-combat:[/] {msg} "
                  f"({'atk wins' if attacker_wins else 'def wins'})")

    def action_open_town(self) -> None:
        if self.map_view is None:
            return
        cx, cy = self.map_view.cursor_x, self.map_view.cursor_y
        town = self.game.town_at(cx, cy)
        if town is None:
            self._log("[dim]Cursor is not on a town.[/]")
            return
        if town.owner != self.game.current_player:
            self._log("[dim]That town is not yours.[/]")
            return
        self.push_screen(TownScreen(self.game, town))

    def action_save(self) -> None:
        path = "homm2_save.json"
        try:
            self.game.save(path)
            self._log(f"[green]Saved to {path}[/]")
        except Exception as e:  # noqa: BLE001
            self._log(f"[red]Save failed: {e}[/]")

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    # ---- helpers ---------------------------------------------------

    def _refresh_status(self) -> None:
        if self.status_panel is None or self.map_view is None:
            return
        sel_hid = self._selected_hero.hid if self._selected_hero else -1
        self.status_panel.refresh_panel(
            (self.map_view.cursor_x, self.map_view.cursor_y), sel_hid)

    def _log(self, msg: str) -> None:
        if self.log_panel is not None:
            self.log_panel.write(msg)


def run(scenario: str = "dawn_assault", mode: str = "ai") -> None:
    HoMM2App(scenario=scenario, mode=mode).run()
