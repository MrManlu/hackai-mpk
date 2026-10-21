#!/usr/bin/env python3
"""Check the Global menu (SHIFT + STOP) of a firmware image in the simulator.

    python3 sim/scripts/menu_check.py IMAGE [--compare STOCK]

Opens the menu, walks the cursor through every entry and prints each screen.
With our firmware (an entry " THRU:"), it then switches THRU on, checks that
the setting reached our settings sector in flash, resets the machine and
checks that it is still on. With --compare, it walks the stock menu too and
checks that the stock entries look the same in both (all screens until the
cursor reaches the last stock entry). Exit status 0 if every check passed.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sim" / "scripts"))
from simlib import Sim  # noqa: E402

SHIFT, STOP, ENCODER_PUSH = (11, 3), (12, 2), (11, 6)
SETTINGS = 0x0802D800
MAGIC = b"HKM1"


def open_menu(sim):
    sim.screen(4)                         # boot
    sim.combo(SHIFT, STOP)
    return sim.screen(0.3)


def walk(sim, entries):
    """Screens with the cursor on entry 0, 1, ... entries-1 (and one more turn)."""
    screens = [open_menu(sim)]
    for _ in range(entries):
        sim.turn(1)
        screens.append(sim.screen(0.3))
    return screens


def check(name, ok, failures):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        failures.append(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image")
    parser.add_argument("--compare", metavar="STOCK", help="stock image to compare with")
    args = parser.parse_args()
    failures = []

    stock_screens = None
    if args.compare:
        sim = Sim(args.compare, port=4376)
        try:
            stock_screens = walk(sim, 6)
        finally:
            sim.close()

    sim = Sim(args.image, port=4377)
    try:
        screens = walk(sim, 7)
        for n, s in enumerate(screens):
            print(f"--- cursor on entry {min(n, 6) + 1}" + (" (extra turn)" if n == 7 else ""))
            print(s)
        if stock_screens:
            # Entries 1-5 show the same two rows in both; from entry 6 on ours
            # shows entries 6 and 7, the stock one 5 and 6.
            check("stock entries look the same (cursor on 1-5)",
                  screens[:5] == stock_screens[:5], failures)

        # Cursor is on entry 7 (THRU). Edit: push, turn right, push.
        sim.press(*ENCODER_PUSH)
        sim.turn(1)
        editing = sim.screen(0.3)
        sim.press(*ENCODER_PUSH)
        on = sim.screen(0.3)
        print("--- THRU switched on (editing)")
        print(editing)
        check("THRU value changed on screen", editing != screens[-1], failures)
        record = sim.read(SETTINGS, 32)
        print("settings sector:", record.hex(" "))
        check("THRU setting stored in flash", record[:4] == MAGIC and record[4] == 1, failures)

        sim.run("machine Reset")
        after = walk(sim, 7)[-1]
        print("--- after a reset, cursor on THRU")
        print(after)
        check("THRU still on after a reset", after == on, failures)
    finally:
        sim.close()

    print("all checks passed" if not failures else f"{len(failures)} check(s) failed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
