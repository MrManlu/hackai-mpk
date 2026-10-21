#!/usr/bin/env python3
"""Check the pad LED feedback in the simulator.

    python3 sim/scripts/feedback_check.py IMAGE [--stock STOCK]

Sends notes into the simulated DIN IN (the simulator has no USB host, so DIN
IN goes to the unit's own message handler) and reads the pad LED colours from
the shift-register outputs. In the MPC program the pads are red at rest
(Off C 1) and blue when lit (On C 19); pad A1 is note 36, B1 note 44, both on
channel 10 (PadCH). Checks that:

- with --stock, the stock firmware ignores these notes;
- note on 36, channel 10 lights pad 1 blue; another channel does nothing;
- hitting the pad while lit by MIDI keeps it blue (the sender is in charge);
- note off gives it back: red;
- a note for B1 does not touch bank A, B1 shows it after BANK A/B;
- a pad that is not lit by MIDI still lights up when hit (stock behaviour).

Exit status 0 if every check passed.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sim" / "scripts"))
from simlib import Sim  # noqa: E402
from menu_check import check  # noqa: E402
from thru_check import send  # noqa: E402
from pad_check import press_pad  # noqa: E402

BANK = (11, 0)


def pad_colour(sim, pad):
    """'red', 'green', 'blue', 'off' or a mix, for physical pad 1-8."""
    levels = [int(v) for v in sim.run("spi1.leds Brightness").split()
              if v.strip().lstrip("-").isdigit()]
    base = 24 + 3 * (8 - pad)
    blue, green, red = levels[base], levels[base + 1], levels[base + 2]
    lit = [name for name, v in (("red", red), ("green", green), ("blue", blue))
           if v > 0.5 * max(red, green, blue, 1)]
    return "+".join(lit) if max(red, green, blue) > 2 else "off"


def note(sim, data):
    send(sim, bytes.fromhex(data))
    sim.run('emulation RunFor "0.2"')


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image")
    parser.add_argument("--stock", metavar="STOCK", help="also check the stock image")
    args = parser.parse_args()
    failures = []

    if args.stock:
        sim = Sim(args.stock, port=4383)
        try:
            sim.screen(4)
            before = pad_colour(sim, 1)
            note(sim, "99 24 7F")
            after = pad_colour(sim, 1)
            print(f"stock: pad 1 {before} -> {after} after note on 36 ch 10")
            check("stock firmware ignores the note", before == after == "red", failures)
        finally:
            sim.close()

    sim = Sim(args.image, port=4384)
    try:
        sim.screen(4)
        print("pad 1 at rest:", pad_colour(sim, 1))
        check("pad 1 red at rest", pad_colour(sim, 1) == "red", failures)

        note(sim, "92 24 7F")
        check("note on another channel does nothing", pad_colour(sim, 1) == "red", failures)
        note(sim, "82 24 00")

        note(sim, "99 24 7F")
        print("after note on 36 ch 10:", pad_colour(sim, 1))
        check("note on lights pad 1 (On colour, blue)", pad_colour(sim, 1) == "blue", failures)

        press_pad(sim, 1, True)
        held = pad_colour(sim, 1)
        press_pad(sim, 1, False)
        released = pad_colour(sim, 1)
        print(f"hit while lit: held {held}, released {released}")
        check("hitting a lit pad keeps it lit", held == released == "blue", failures)

        note(sim, "89 24 00")
        print("after note off:", pad_colour(sim, 1))
        check("note off gives it back (red)", pad_colour(sim, 1) == "red", failures)

        note(sim, "99 2C 7F")
        check("note for B1 leaves bank A alone", pad_colour(sim, 1) == "red", failures)
        sim.press(*BANK)
        sim.run('emulation RunFor "0.3"')
        print("bank B, pad 1 (B1):", pad_colour(sim, 1))
        check("B1 lit after BANK A/B", pad_colour(sim, 1) == "blue", failures)
        note(sim, "89 2C 00")
        check("B1 note off", pad_colour(sim, 1) == "red", failures)
        sim.press(*BANK)
        sim.run('emulation RunFor "0.3"')

        press_pad(sim, 2, True)
        held = pad_colour(sim, 2)
        press_pad(sim, 2, False)
        print(f"pad 2 (not lit by MIDI): held {held}, released {pad_colour(sim, 2)}")
        check("unlit pads still light up when hit",
              held == "blue" and pad_colour(sim, 2) == "red", failures)
    finally:
        sim.close()

    print("all checks passed" if not failures else f"{len(failures)} check(s) failed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
