#!/usr/bin/env python3
"""Check MIDI THRU in the simulator: DIN IN messages must come out of DIN OUT.

    python3 sim/scripts/thru_check.py IMAGE [--stock STOCK]

Sends MIDI bytes into the simulated DIN IN (USART1 receive) and reads what
the firmware sends on DIN OUT (the midiOut monitor). Checks that:

- with --stock, the stock firmware does not forward DIN IN (the reason for
  the mod);
- with THRU off, our firmware does not forward either;
- after switching THRU on in the Global menu, every message comes out, in
  order (running status expanded, clock, CC, program change, SysEx);
- messages stay whole when the keyboard sends at the same time;
- THRU is still on after a reset.

The simulator has no USB host, so this tests the standalone path. Exit status
0 if every check passed.
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sim" / "scripts"))
from simlib import Sim  # noqa: E402
from menu_check import ENCODER_PUSH, SHIFT, STOP, check  # noqa: E402

# Bytes sent into DIN IN, and the messages expected out of DIN OUT.
STREAM = [
    (bytes.fromhex("90 3C 64"), ["90 3C 64"]),                  # note on
    (bytes.fromhex("3E 50"), ["90 3E 50"]),                     # running status
    (bytes.fromhex("F8"), ["F8"]),                              # clock
    (bytes.fromhex("80 3C 00 80 3E 00"), ["80 3C 00", "80 3E 00"]),
    (bytes.fromhex("B1 07 64"), ["B1 07 64"]),                  # CC, channel 2
    (bytes.fromhex("C9 05"), ["C9 05"]),                        # program change, ch 10
    (bytes.fromhex("F0 7E 7F 06 01 F7"), ["F0 7E 7F 06 01 F7"]),  # SysEx identity request
]


def send(sim, data):
    sim.run("; ".join(f"usart1 WriteChar 0x{b:02X}" for b in data))
    sim.run('emulation RunFor "0.02"')


def messages(sim):
    """DIN OUT messages since the last clear, as hex strings."""
    out = sim.run("midiOut Messages 500")
    found = []
    for line in out.splitlines():
        m = re.match(r"\s*[\d.]+ s\s+((?:[0-9A-F]{2} ?)+)", line)
        if m:
            found.append(m.group(1).strip())
    return found


def din_through(sim):
    sim.run("midiOut Clear")
    for data, _ in STREAM:
        send(sim, data)
    sim.run('emulation RunFor "0.1"')
    return messages(sim)


EXPECTED = [m for _, ms in STREAM for m in ms]


def thru_on(sim):
    """Global menu: cursor to entry 7 (THRU), push, turn right, push, leave."""
    sim.combo(SHIFT, STOP)
    for _ in range(7):
        sim.turn(1)
        sim.run('emulation RunFor "0.1"')
    sim.press(*ENCODER_PUSH)
    sim.turn(1)
    sim.run('emulation RunFor "0.1"')
    sim.press(*ENCODER_PUSH)
    sim.combo(SHIFT, STOP)             # leave the menu
    sim.run('emulation RunFor "0.3"')


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image")
    parser.add_argument("--stock", metavar="STOCK", help="also check the stock image")
    args = parser.parse_args()
    failures = []

    if args.stock:
        sim = Sim(args.stock, port=4378)
        try:
            sim.screen(4)
            out = din_through(sim)
            print("stock DIN OUT:", out)
            check("stock firmware does not forward DIN IN", out == [], failures)
        finally:
            sim.close()

    sim = Sim(args.image, port=4379)
    try:
        sim.screen(4)
        out = din_through(sim)
        print("THRU off, DIN OUT:", out)
        check("THRU off: nothing forwarded", out == [], failures)

        thru_on(sim)
        out = din_through(sim)
        print("THRU on, DIN OUT:", out)
        check("THRU on: every message forwarded, in order", out == EXPECTED, failures)

        # Keyboard and DIN IN at the same time: a key goes down and up while
        # a stream of CCs arrives.
        sim.run("midiOut Clear")
        sim.run("keys KeyDown 20")
        ccs = bytes(b for v in range(40) for b in (0xB0, 0x01, v))
        for i in range(0, len(ccs), 12):
            send(sim, ccs[i:i + 12])
        sim.run("keys KeyUp 20")
        sim.run('emulation RunFor "0.3"')
        out = messages(sim)
        cc_out = [m for m in out if m.startswith("B0 01")]
        keys = [m for m in out if not m.startswith("B0 01")]
        print(f"merge: {len(cc_out)} CCs, keyboard: {keys}")
        check("merge: all 40 CCs whole and in order",
              cc_out == [f"B0 01 {v:02X}" for v in range(40)], failures)
        check("merge: the key's note on and note off came out whole",
              len(keys) == 2 and all(len(k.split()) == 3 for k in keys)
              and keys[0][0] == "9" and keys[1][0] in "89", failures)

        sim.run("machine Reset")
        sim.screen(4)
        out = din_through(sim)
        check("THRU still on after a reset", out == EXPECTED, failures)
    finally:
        sim.close()

    print("all checks passed" if not failures else f"{len(failures)} check(s) failed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
