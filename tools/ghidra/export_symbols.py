#!/usr/bin/env python3
"""Write the names given in Ghidra back to config/symbols.csv.

Every user-defined symbol (function or label) outside peripheral memory is
exported. Plate comments become the `notes` column. The `type` and `status`
columns of existing rows are kept; new rows get status "named".

Rows of symbols.csv that are no longer named in Ghidra are kept, unless
--prune is given. To delete a name, remove its row from symbols.csv.

Close the project in the Ghidra GUI (or at least save it) before exporting.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (PROGRAM_NAME, PROJECT_DIR, PROJECT_NAME, SYMBOLS, read_symbols,
                    start_ghidra, write_symbols)


def collect(program):
    from ghidra.program.model.listing import CodeUnit
    from ghidra.program.model.symbol import SourceType, SymbolType

    memory = program.getMemory()
    listing = program.getListing()
    found = {}
    for symbol in program.getSymbolTable().getAllSymbols(True):
        if symbol.getSource() != SourceType.USER_DEFINED:
            continue
        if symbol.getSymbolType() not in (SymbolType.FUNCTION, SymbolType.LABEL):
            continue
        address = symbol.getAddress()
        block = memory.getBlock(address)
        if block is None or block.isVolatile() or not address.isMemoryAddress():
            continue
        if not symbol.isPrimary() and address.getOffset() in found:
            continue
        found[address.getOffset()] = {
            "kind": "func" if symbol.getSymbolType() == SymbolType.FUNCTION else "label",
            "name": symbol.getName(),
            "notes": (listing.getComment(CodeUnit.PLATE_COMMENT, address) or "").replace("\n", " "),
        }
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", type=Path, default=PROJECT_DIR / f"{PROJECT_NAME}.gpr",
                        help="Ghidra project (.gpr) to read, default: the built one")
    parser.add_argument("--program", default=PROGRAM_NAME, help="program name in the project")
    parser.add_argument("--output", type=Path, default=SYMBOLS)
    parser.add_argument("--prune", action="store_true",
                        help="drop rows that are no longer named in Ghidra")
    args = parser.parse_args()

    if not args.project.exists():
        sys.exit(f"{args.project} not found: run `make ghidra` first")

    start_ghidra()
    from ghidra.base.project import GhidraProject

    project = GhidraProject.openProject(str(args.project.parent), args.project.stem, True)
    try:
        program = project.openProgram("/", args.program, True)
        found = collect(program)
    finally:
        project.close()

    old = read_symbols(args.output)
    merged, renamed, added = {}, 0, 0
    for address, sym in found.items():
        row = dict(old.get(address, {"type": "", "status": "named"}))
        if address in old and old[address]["name"] != sym["name"]:
            renamed += 1
        elif address not in old:
            added += 1
        row.update(sym)
        if not sym["notes"]:
            row["notes"] = old.get(address, {}).get("notes", "")
        merged[address] = row

    missing = sorted(set(old) - set(merged))
    for address in missing:
        if args.prune:
            print(f"removed: 0x{address:08X} {old[address]['name']}")
        else:
            merged[address] = old[address]
    write_symbols(merged, args.output)
    print(f"{args.output.name}: {len(merged)} symbols ({added} new, {renamed} renamed, "
          f"{len(missing)} {'removed' if args.prune else 'not in Ghidra, kept'})")


if __name__ == "__main__":
    main()
