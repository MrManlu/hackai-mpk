#!/usr/bin/env python3
"""Check the per-pad MIDI channel in the simulator.

    python3 sim/scripts/pad_check.py IMAGE [--compare STOCK]

Hits pads (pressure on their ADC inputs) and reads the MIDI they send on DIN
OUT (the simulator has no USB host, so the unit sends there). Checks that:

- pad 1 starts on the program's PadCH (channel 10 in the MPC program);
- the pad edit menu (SHIFT + PROG SELECT, hit the pad) shows the stock
  entries exactly as the stock firmware does (with --compare), plus entry 8;
- after setting Chan to 3, pad 1 plays on channel 3 (note on and note off)
  and pad 2 stays on channel 10;
- a stock entry still works through the wrapped encoder (note 36 -> 37);
- the channel survives a reset.

Exit status 0 if every check passed.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sim" / "scripts"))
from simlib import Sim  # noqa: E402
from menu_check import ENCODER_PUSH, SHIFT, check  # noqa: E402
from thru_check import messages  # noqa: E402

PROG_SELECT, HOME = (11, 5), (11, 4)
PADS = {1: ((0, 3), (0, 7)), 2: ((0, 1), (0, 5))}   # ADC (channel, mux) pairs


def hit(sim, pad, hold=0.2):
    sim.run("; ".join(f"adc1 SetInput {c} {m} 3500" for c, m in PADS[pad]))
    sim.run(f'emulation RunFor "{hold}"')
    sim.run("; ".join(f"adc1 SetInput {c} {m} 0" for c, m in PADS[pad]))
    sim.run('emulation RunFor "0.2"')


def play(sim, pad):
    """MIDI sent by one hit of `pad`, outside any menu."""
    sim.run("midiOut Clear")
    hit(sim, pad)
    return messages(sim)


def open_pad_menu(sim, pad):
    sim.combo(SHIFT, PROG_SELECT)
    sim.run('emulation RunFor "0.2"')
    hit(sim, pad)
    return sim.screen(0.3)


def walk(sim, turns):
    screens = [sim.screen(0.1)]
    for _ in range(turns):
        sim.turn(1)
        screens.append(sim.screen(0.3))
    return screens


def leave_menu(sim):
    sim.press(*HOME)
    sim.run('emulation RunFor "0.5"')


def channel(msg):
    return int(msg.split()[0], 16) & 0x0F


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image")
    parser.add_argument("--compare", metavar="STOCK", help="stock image to compare with")
    args = parser.parse_args()
    failures = []

    stock_screens = None
    if args.compare:
        sim = Sim(args.compare, port=4381)
        try:
            sim.screen(4)
            open_pad_menu(sim, 1)
            stock_screens = walk(sim, 6)
        finally:
            sim.close()

    sim = Sim(args.image, port=4382)
    try:
        sim.screen(4)
        out = play(sim, 1)
        print("pad 1, Glob:", out)
        check("pad 1 starts on PadCH (channel 10)",
              len(out) == 2 and all(channel(m) == 9 for m in out), failures)

        open_pad_menu(sim, 1)
        screens = walk(sim, 7)
        if stock_screens:
            check("pad menu: stock entries look the same (cursor on 1-6)",
                  screens[:6] == stock_screens[:6], failures)
        print("--- pad menu, cursor on entry 8")
        print(screens[-1])

        # Entry 8: push, three detents right (Glob -> 1 -> 2 -> 3), push.
        sim.press(*ENCODER_PUSH)
        for _ in range(3):
            sim.turn(1)
            sim.run('emulation RunFor "0.1"')
        sim.press(*ENCODER_PUSH)
        print("--- Chan set to 3")
        print(sim.screen(0.3))

        # Entry 1 (stock, through the wrapped encoder): note 36 -> 37.
        for _ in range(7):
            sim.turn(-1)
            sim.run('emulation RunFor "0.1"')
        sim.press(*ENCODER_PUSH)
        sim.turn(1)
        sim.run('emulation RunFor "0.1"')
        sim.press(*ENCODER_PUSH)
        leave_menu(sim)

        out = play(sim, 1)
        print("pad 1, Chan 3, note +1:", out)
        check("pad 1 plays on channel 3 (note on and off)",
              len(out) == 2 and all(channel(m) == 2 for m in out), failures)
        check("stock entry edited through the wrapped encoder (note 37)",
              len(out) == 2 and all(m.split()[1] == "25" for m in out), failures)
        out = play(sim, 2)
        print("pad 2:", out)
        check("pad 2 stays on channel 10",
              len(out) == 2 and all(channel(m) == 9 for m in out), failures)

        record = sim.read(0x0802D800, 64)
        print("settings sector:", record.hex(" "))

        sim.run("machine Reset")
        sim.screen(4)
        out = play(sim, 1)
        print("pad 1 after a reset:", out)
        check("channel 3 survives a reset",
              len(out) == 2 and all(channel(m) == 2 for m in out), failures)
    finally:
        sim.close()

    print("all checks passed" if not failures else f"{len(failures)} check(s) failed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
