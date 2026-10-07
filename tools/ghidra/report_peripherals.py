#!/usr/bin/env python3
"""Report which peripherals each function uses, as a first map of subsystems.

A function "uses" a peripheral when one of its instructions:
  - reads or writes a peripheral register (after Ghidra's constant
    propagation; registers are listed only for real reads/writes), or
  - loads a literal-pool constant that points into a peripheral, which is how
    IAR code gets peripheral base addresses (also when it only passes them to a
    library call such as gpio_bits_set(GPIOB, ...)).

Bit-band aliases (0x42000000-0x43FFFFFF) are mapped back to their register.
Uses are then propagated up the call graph ("transitive").

Outputs build/reports/peripherals.csv (one row per function) and
build/reports/peripherals.md (grouped by peripheral).
"""

import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (PROGRAM_NAME, ROOT, load_config, load_svd, open_project,
                    start_ghidra)

REPORTS = ROOT / "build" / "reports"

# Cortex-M core peripherals inside the SVD's NVIC block, checked first.
CORE = [
    {"name": "SysTick", "base": 0xE000E010, "size": 0x10,
     "regs": {0x0: "CTRL", 0x4: "LOAD", 0x8: "VAL", 0xC: "CALIB"}},
    {"name": "SCB", "base": 0xE000ED00, "size": 0x90,
     "regs": {0x04: "ICSR", 0x08: "VTOR", 0x0C: "AIRCR", 0x10: "SCR", 0x14: "CCR",
              0x24: "SHCSR", 0x28: "CFSR"}},
]
BITBAND = (0x42000000, 0x44000000)


class PeripheralMap:
    def __init__(self, peripherals):
        self.ranges = list(CORE)
        for p in peripherals:
            self.ranges.append({"name": p["name"], "base": p["base"], "size": p["size"],
                                "regs": {off: name for name, off, _, _ in p["registers"]}})

    def is_base(self, address):
        return any(r["base"] == address for r in self.ranges)

    def lookup(self, address):
        """Return (peripheral, register) for an address, or None."""
        bit = None
        if BITBAND[0] <= address < BITBAND[1]:
            offset = address - BITBAND[0]
            bit = (offset >> 2) & 31
            address = 0x40000000 + ((offset >> 5) & ~3)
        for r in self.ranges:
            if r["base"] <= address < r["base"] + r["size"]:
                offset = address - r["base"]
                reg = r["regs"].get(offset, f"+0x{offset:X}" if offset else "")
                if bit is not None:
                    reg = f"{reg}[{bit}]"
                return r["name"], reg
        return None


def direct_uses(program, function, pmap):
    """Return {peripheral: set(registers)} for one function."""
    memory = program.getMemory()
    listing = program.getListing()
    uses = defaultdict(set)
    for instr in listing.getInstructions(function.getBody(), True):
        for ref in instr.getReferencesFrom():
            to = ref.getToAddress()
            if not to.isMemoryAddress():
                continue
            hit = pmap.lookup(to.getOffset())
            if hit is not None:
                kind = ref.getReferenceType()
                if not (kind.isRead() or kind.isWrite()):
                    hit = (hit[0], "")  # address computed, not accessed here
            else:
                block = memory.getBlock(to)
                if block is None or not block.isInitialized() or block.isVolatile():
                    continue
                if listing.getInstructionAt(to) is not None:
                    continue
                try:
                    value = memory.getInt(to) & 0xFFFFFFFF
                except Exception:
                    continue
                hit = pmap.lookup(value)
                if hit and not hit[1].startswith("+") and pmap.is_base(value):
                    hit = (hit[0], "")  # only the base address is loaded
            if hit:
                peripheral, register = hit
                uses[peripheral].add(register)
    return uses


def main():
    cfg = load_config()
    peripherals, _ = load_svd(ROOT / cfg["svd"]["path"])
    pmap = PeripheralMap(peripherals)
    segments = [(s["start"], s["end"], s["name"]) for s in cfg["segment"]]

    start_ghidra()
    from ghidra.util.task import TaskMonitor

    project = open_project()
    try:
        program = project.openProgram("/", PROGRAM_NAME, True)
        functions = {}
        for f in program.getFunctionManager().getFunctions(True):
            entry = f.getEntryPoint().getOffset()
            functions[entry] = {
                "name": f.getName(),
                "user": str(f.getSymbol().getSource()) == "USER_DEFINED",
                "segment": next((n for s, e, n in segments if s <= entry < e), "?"),
                "direct": direct_uses(program, f, pmap),
                "callees": {c.getEntryPoint().getOffset()
                            for c in f.getCalledFunctions(TaskMonitor.DUMMY)},
            }
    finally:
        project.close()

    # Transitive uses: union over the call graph (cycles are cut).
    memo = {}

    def transitive(entry, stack=()):
        if entry in memo:
            return memo[entry]
        result = set(functions[entry]["direct"])
        for callee in functions[entry]["callees"]:
            if callee in functions and callee not in stack:
                result |= transitive(callee, stack + (entry,))
        memo[entry] = result
        return result

    for entry in functions:
        functions[entry]["transitive"] = transitive(entry)

    REPORTS.mkdir(parents=True, exist_ok=True)
    write_csv(functions)
    write_markdown(functions)
    used = {p for f in functions.values() for p in f["direct"]}
    touching = sum(1 for f in functions.values() if f["direct"])
    print(f"{len(functions)} functions, {touching} use peripherals directly, "
          f"{len(used)} peripherals used")
    print(f"reports in {REPORTS.relative_to(ROOT)}/")


def fmt_uses(uses):
    return " ".join(f"{p}({','.join(sorted(r for r in regs if r))})" if any(regs) else p
                    for p, regs in sorted(uses.items()))


def write_csv(functions):
    with (REPORTS / "peripherals.csv").open("w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["address", "segment", "name", "direct", "transitive"])
        for entry, fn in sorted(functions.items()):
            writer.writerow([f"0x{entry:08X}", fn["segment"], fn["name"],
                             fmt_uses(fn["direct"]), " ".join(sorted(fn["transitive"]))])


def write_markdown(functions):
    by_peripheral = defaultdict(list)
    for entry, fn in functions.items():
        for peripheral, regs in fn["direct"].items():
            by_peripheral[peripheral].append((entry, fn, regs))

    lines = ["# Peripheral usage", "",
             "Generated by `make report`. Do not edit: rebuild instead.", "",
             "| Peripheral | Functions (bootloader / app) |", "|---|---|"]
    for peripheral in sorted(by_peripheral):
        users = by_peripheral[peripheral]
        bl = sum(1 for _, fn, _ in users if fn["segment"] == "bootloader")
        lines.append(f"| [{peripheral}](#{peripheral.lower()}) | {bl} / {len(users) - bl} |")

    for peripheral in sorted(by_peripheral):
        lines += ["", f"## {peripheral}", "",
                  "| Address | Function | Registers |", "|---|---|---|"]
        for entry, fn, regs in sorted(by_peripheral[peripheral], key=lambda u: u[0]):
            name = f"**{fn['name']}**" if fn["user"] else fn["name"]
            regs = ", ".join(sorted(r for r in regs if r)) or "(base address)"
            lines.append(f"| `0x{entry:08X}` | {name} | {regs} |")
    (REPORTS / "peripherals.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
