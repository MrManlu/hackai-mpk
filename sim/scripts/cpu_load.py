#!/usr/bin/env python3
"""Measure how much CPU our code takes, with Renode's profiler.

    python3 sim/scripts/cpu_load.py [IMAGE] [--elf ELF] [--stock STOCK]

Boots IMAGE (default build/mods/hackai.bin) with MIDI THRU on, then for one
virtual second feeds DIN IN at about the full MIDI rate (note on/off pairs, a
quarter of them for pad 1 so the LED feedback fires, plus CCs) and hits pad 1.
Meanwhile Renode's "collapsed stack" profiler counts the instructions executed
per call stack. Prints the share executed inside our code (0x08026000 up),
on its own and including the stock functions it calls, and the top functions
(names from ELF, default build/mods/hackai.elf).

The profiler books instructions to the function that was *called*. Our
replace and wrap hooks are entered with a jump from the stock function's
entry, so their work is booked to the stock function (din_in_poll_APP...).
With --stock, the same load runs on the stock image too, and the script
compares the instructions spent under every hooked stock function (and in
our code): the difference is the real extra cost of the mods.

The profiler writes several hundred MB per virtual second. To keep the disk
safe, it runs in ten windows of 0.1 s; each file is added up and deleted
before the next, and the script stops if less than 400 MB are free. (A named
pipe would avoid the files, but Renode hangs when the profiler is enabled on
one.) See docs/performance.md.
"""

import argparse
import collections
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sim" / "scripts"))
from simlib import Sim  # noqa: E402
from pad_check import press_pad  # noqa: E402

OURS = (0x08026000, 0x0802D800)
MIN_FREE = 400e6


def hooked_functions():
    """Addresses of the stock functions our hooks replace, wrap or jump into."""
    symbols = {}
    for line in (ROOT / "config" / "symbols.csv").read_text().splitlines()[1:]:
        address, kind, name = line.split(",")[:3]
        symbols[name] = int(address, 16)
    hooks = tomllib.loads((ROOT / "firmware" / "hooks.toml").read_text())
    found = {symbols[h["function"]]: h["function"]
             for kind in ("replace", "wrap") for h in hooks.get(kind, [])}
    # jump hooks sit inside pad_event_APP and pad_note_repeat_APP
    for name in ("pad_event_APP", "pad_note_repeat_APP"):
        found[symbols[name]] = name
    return found


def our_names(elf):
    names = {}
    out = subprocess.run(["arm-none-eabi-nm", str(elf)], capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] in "Tt":
            names[int(parts[0], 16) & ~1] = parts[2]
    return names


def add_profile(path, totals, functions, names, hooked):
    """Adds up one collapsed-stack file ("frame;frame;... count" per line)."""
    with open(path) as f:
        first = True
        for line in f:
            stack, _, count = line.rpartition(" ")
            if not stack:
                continue
            if first:              # the instructions before the profiler started
                first = False
                continue
            count = int(count)
            frames = [int(x, 16) & ~1 for x in stack.split(";")]
            totals["all"] += count
            if OURS[0] <= frames[-1] < OURS[1]:
                totals["own"] += count
            ours = [a for a in frames if OURS[0] <= a < OURS[1]]
            if ours:
                totals["with_calls"] += count
                functions[names.get(ours[0], hex(ours[0]))] += count
            if ours or any(a in hooked for a in frames):
                totals["hooked"] += count     # under a hooked function, or ours
    os.remove(path)


def workload():
    """DIN IN bytes: 250 note on/off pairs (1 in 4 for pad 1) and 250 CCs."""
    data = []
    for i in range(500):
        note = 0x24 if i % 4 == 0 else 0x40 + i % 20
        data += [0x99, note, 0x64, 0x89, note, 0x00] if i % 2 == 0 else [0xB0, 0x07, i % 128]
    return bytes(data)


def measure(image, names, hooked):
    totals, functions = collections.Counter(), collections.Counter()
    profile = Path(tempfile.gettempdir()) / f"hackai-profile-{os.getpid()}.txt"
    stream, sent = workload(), 0
    sim = Sim(image, port=4402)
    try:
        # MIDI THRU on: one settings record ("HKM1", midi_thru = 1) before boot
        # (the stock firmware ignores it).
        sim.run("sysbus WriteDoubleWord 0x0802D800 0x314D4B48; "
                "sysbus WriteDoubleWord 0x0802D804 0x00000001")
        sim.run("machine Reset")
        sim.screen(4)
        for step in range(100):            # 100 steps of 10 ms
            if step % 10 == 0:
                if shutil.disk_usage(profile.parent).free < MIN_FREE:
                    raise SystemExit("less than 400 MB free: stopping")
                sim.run(f"cpu EnableProfilerCollapsedStack @{profile}")
            chunk = stream[sent:sent + 30]  # ~3000 bytes/s, the DIN rate
            sent += len(chunk)
            if chunk:
                sim.run("; ".join(f"usart1 WriteChar 0x{b:02X}" for b in chunk))
            if step % 20 == 5:
                press_pad(sim, 1, True)     # runs 0.2 s
            elif step % 20 == 15:
                press_pad(sim, 1, False)
            else:
                sim.run('emulation RunFor "0.01"')
            if step % 10 == 9:
                sim.run("cpu DisableProfiler")
                add_profile(profile, totals, functions, names, hooked)
    finally:
        sim.close()
        profile.unlink(missing_ok=True)
    return totals, functions, sent


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image", nargs="?", default=str(ROOT / "build" / "mods" / "hackai.bin"))
    parser.add_argument("--elf", default=str(ROOT / "build" / "mods" / "hackai.elf"))
    parser.add_argument("--stock", metavar="STOCK", help="compare with the stock image")
    args = parser.parse_args()

    names = our_names(args.elf) if Path(args.elf).exists() else {}
    hooked = hooked_functions()
    totals, functions, sent = measure(args.image, names, hooked)
    total = totals["all"] or 1
    print(f"{Path(args.image).name}: {sent} bytes into DIN IN, "
          f"{totals['all']:,} instructions profiled")
    print(f"our code, own instructions:    {totals['own']:>12,} ({100 * totals['own'] / total:.3f} %)")
    print(f"our code, with stock calls:    {totals['with_calls']:>12,} "
          f"({100 * totals['with_calls'] / total:.3f} %)")
    for name, count in functions.most_common(8):
        print(f"  {name:30s} {count:>12,} ({100 * count / total:.3f} %)")

    if args.stock:
        stock, _, _ = measure(args.stock, {}, hooked)
        extra = totals["hooked"] - stock["hooked"]
        print(f"under the hooked functions: stock {stock['hooked']:,}, "
              f"mod {totals['hooked']:,} instructions")
        print(f"extra cost of the mods: {extra:,} instructions "
              f"({100 * extra / total:.3f} % of the CPU)")


if __name__ == "__main__":
    main()
