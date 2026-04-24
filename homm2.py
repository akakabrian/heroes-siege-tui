"""HoMM2 TUI entry point — `python homm2.py [scenario] [--hotseat|--vs-ai]`."""

from __future__ import annotations

import argparse

from heroes_siege_tui.app import run


def main() -> None:
    p = argparse.ArgumentParser(prog="heroes-siege-tui")
    p.add_argument("scenario", nargs="?", default="dawn_assault",
                   help="scenario key (default: dawn_assault)")
    p.add_argument("--vs-ai", action="store_true", help="P2 is AI (default)")
    p.add_argument("--hotseat", action="store_true",
                   help="both players human on same terminal")
    args = p.parse_args()
    mode = "hotseat" if args.hotseat else "ai"
    run(args.scenario, mode=mode)


if __name__ == "__main__":
    main()
