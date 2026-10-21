#!/usr/bin/env python3
"""Print Ghidra's decompilation of one or more functions.

    make decompile F=bootloader_POSSIBLE_BL
    make decompile F="0x08003DC8 main"
    make decompile-all              # every function, into build/decompiled.c

Functions can be given by name or by address. Output is for reading only:
do not paste it into the repository (see CONTRIBUTING notes in README.md).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import PROGRAM_NAME, open_project, start_ghidra


def find_function(program, spec):
    functions = program.getFunctionManager()
    if spec.lower().startswith("0x"):
        address = program.getAddressFactory().getAddress(spec)
        return functions.getFunctionContaining(address)
    for function in functions.getFunctions(True):
        if function.getName() == spec:
            return function
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("functions", nargs="*", help="function names or 0x addresses")
    parser.add_argument("--all", action="store_true", help="every function, by address")
    args = parser.parse_args()
    if not args.functions and not args.all:
        parser.error("give function names or addresses, or --all")

    start_ghidra()
    from ghidra.app.decompiler import DecompInterface

    project = open_project()
    try:
        program = project.openProgram("/", PROGRAM_NAME, True)
        decompiler = DecompInterface()
        decompiler.openProgram(program)
        if args.all:
            targets = list(program.getFunctionManager().getFunctions(True))
        else:
            targets = [find_function(program, spec) for spec in args.functions]
        for spec, function in zip(args.functions or [str(f.getEntryPoint()) for f in targets],
                                  targets):
            if function is None:
                print(f"// {spec}: no such function\n")
                continue
            result = decompiler.decompileFunction(function, 120, None)
            print(f"// {function.getName()} @ {function.getEntryPoint()}")
            print(result.getDecompiledFunction().getC() if result.decompileCompleted()
                  else f"// decompilation failed: {result.getErrorMessage()}")
        decompiler.dispose()
    finally:
        project.close()


if __name__ == "__main__":
    main()
