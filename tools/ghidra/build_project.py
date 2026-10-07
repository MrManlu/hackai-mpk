#!/usr/bin/env python3
"""Build the Ghidra project from scratch out of the text files in config/.

Steps, in this order (the order matters, see docs/ghidra-setup.md):
  1. memory blocks for each firmware segment and for RAM
  2. peripheral blocks, register structures and labels from the SVD
  3. vector tables: handler functions named after the SVD interrupts
  4. names from config/symbols.csv
  5. auto-analysis
"""

import argparse
import shutil
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (PROGRAM_NAME, PROJECT_DIR, PROJECT_NAME, ROOT, load_config,
                    read_symbols, start_ghidra)

CORE_VECTORS = {
    1: "Reset_Handler", 2: "NMI_Handler", 3: "HardFault_Handler",
    4: "MemManage_Handler", 5: "BusFault_Handler", 6: "UsageFault_Handler",
    11: "SVC_Handler", 12: "DebugMon_Handler", 14: "PendSV_Handler",
    15: "SysTick_Handler",
}


def parse_int(text):
    return int(text.strip(), 0)


# --------------------------------------------------------------------------
# SVD
# --------------------------------------------------------------------------

def load_svd(path):
    """Return (peripherals, interrupts) with derivedFrom resolved."""
    root = ET.parse(path).getroot()
    default_size = parse_int(root.findtext("size", "32"))
    raw = {p.findtext("name"): p for p in root.find("peripherals")}
    peripherals, interrupts = [], {}

    for name, p in raw.items():
        base = raw.get(p.get("derivedFrom"), p)
        block = base.find("addressBlock")
        registers = []
        for r in base.findall("registers/register"):
            registers.append((r.findtext("name"), parse_int(r.findtext("addressOffset")),
                              parse_int(r.findtext("size", str(default_size))),
                              (r.findtext("description") or "").strip()))
        peripherals.append({
            "name": name,
            "type": base.findtext("name"),
            "base": parse_int(p.findtext("baseAddress")),
            "size": parse_int(block.findtext("size")) if block is not None else 0x400,
            "registers": registers,
        })
        for irq in p.findall("interrupt"):
            interrupts[parse_int(irq.findtext("value"))] = irq.findtext("name")
    return peripherals, interrupts


def merged_ranges(peripherals):
    """Merge overlapping peripheral address ranges into memory blocks."""
    ranges = sorted((p["base"], p["base"] + p["size"], p["name"]) for p in peripherals)
    merged = []
    for start, end, name in ranges:
        if merged and start < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end, name])
    return merged


# --------------------------------------------------------------------------
# Program construction
# --------------------------------------------------------------------------

class Builder:
    def __init__(self, program, image, cfg):
        from ghidra.program.model.symbol import SourceType
        from ghidra.util.task import TaskMonitor

        self.program = program
        self.image = image
        self.cfg = cfg
        self.base = cfg["firmware"]["base"]
        self.space = program.getAddressFactory().getDefaultAddressSpace()
        self.memory = program.getMemory()
        self.listing = program.getListing()
        self.symbols = program.getSymbolTable()
        self.functions = program.getFunctionManager()
        self.monitor = TaskMonitor.DUMMY
        self.IMPORTED = SourceType.IMPORTED
        self.USER = SourceType.USER_DEFINED

    def addr(self, value):
        return self.space.getAddress(value)

    def set_perms(self, block, perms, volatile=False):
        block.setRead("r" in perms)
        block.setWrite("w" in perms)
        block.setExecute("x" in perms)
        block.setVolatile(volatile)

    def create_memory(self):
        from java.io import ByteArrayInputStream

        for seg in self.cfg["segment"]:
            data = self.image[seg["start"] - self.base:seg["end"] - self.base]
            block = self.memory.createInitializedBlock(
                seg["name"], self.addr(seg["start"]), ByteArrayInputStream(data),
                len(data), self.monitor, False)
            self.set_perms(block, seg["perms"])
            if "note" in seg:
                block.setComment(seg["note"])
        for mem in self.cfg.get("memory", []):
            block = self.memory.createUninitializedBlock(
                mem["name"], self.addr(mem["start"]), mem["size"], False)
            self.set_perms(block, mem["perms"])

    def create_peripherals(self, peripherals):
        from ghidra.program.model.data import (CategoryPath, DataTypeConflictHandler,
                                               StructureDataType, UnsignedCharDataType,
                                               UnsignedIntegerDataType,
                                               UnsignedShortDataType)

        for start, end, name in merged_ranges(peripherals):
            block = self.memory.createUninitializedBlock(
                name, self.addr(start), end - start, False)
            self.set_perms(block, "rw", volatile=True)

        dtm = self.program.getDataTypeManager()
        category = CategoryPath("/SVD")
        by_size = {8: UnsignedCharDataType.dataType, 16: UnsignedShortDataType.dataType,
                   32: UnsignedIntegerDataType.dataType}
        types = {}
        for p in peripherals:
            if p["type"] not in types:
                struct_dt = StructureDataType(category, p["type"], p["size"])
                for name, offset, bits, desc in p["registers"]:
                    if offset + bits // 8 > p["size"]:
                        continue
                    if struct_dt.getComponentContaining(offset).getDataType().getName() != "undefined":
                        continue  # alternate register at the same offset
                    struct_dt.replaceAtOffset(offset, by_size[bits], bits // 8, name, desc)
                types[p["type"]] = dtm.addDataType(struct_dt, DataTypeConflictHandler.REPLACE_HANDLER)
            address = self.addr(p["base"])
            self.listing.createData(address, types[p["type"]])
            self.symbols.createLabel(address, p["name"], self.IMPORTED)

    def create_vectors(self, interrupts):
        from ghidra.program.model.data import PointerDataType

        for seg in self.cfg["segment"]:
            if "vectors" not in seg:
                continue
            table = seg["vectors"]
            suffix = seg.get("suffix", "")
            entries = self.read_vector_table(seg)
            self.symbols.createLabel(self.addr(table), f"vector_table{suffix}", self.IMPORTED)

            targets = {}
            for index, value in entries:
                targets.setdefault(value & ~1, []).append(index)
            for target, indices in targets.items():
                if len(indices) > 1:
                    name = "Default_Handler"
                elif indices[0] in CORE_VECTORS:
                    name = CORE_VECTORS[indices[0]]
                elif indices[0] >= 16:
                    name = interrupts.get(indices[0] - 16, f"IRQ{indices[0] - 16}") + "_IRQHandler"
                else:
                    name = f"Vector{indices[0]}_Handler"
                self.make_function(target, name + suffix, self.IMPORTED)

            for i in range(entries[-1][0] + 1):
                self.listing.createData(self.addr(table + 4 * i), PointerDataType())

    def read_vector_table(self, seg):
        """Entries (index, value) until the first word that is not a handler."""
        entries = []
        offset = seg["vectors"] - self.base
        for index in range(1, 256):
            (value,) = struct.unpack_from("<I", self.image, offset + 4 * index)
            if value == 0:
                continue
            if not (value & 1 and seg["start"] <= value < seg["end"]):
                break
            entries.append((index, value))
        return entries

    def make_function(self, address, name, source):
        from ghidra.app.cmd.disassemble import DisassembleCommand
        from ghidra.app.cmd.function import CreateFunctionCmd

        addr = self.addr(address)
        func = self.functions.getFunctionAt(addr)
        if func is None:
            DisassembleCommand(addr, None, True).applyTo(self.program, self.monitor)
            CreateFunctionCmd(addr).applyTo(self.program, self.monitor)
            func = self.functions.getFunctionAt(addr)
        if func is not None:
            func.setName(name, source)
        else:
            self.symbols.createLabel(addr, name, source)

    def apply_symbols(self, symbols):
        from ghidra.program.model.listing import CodeUnit

        for address, row in symbols.items():
            if row["kind"] == "func":
                self.make_function(address, row["name"], self.USER)
            else:
                self.symbols.createLabel(self.addr(address), row["name"], self.USER)
            if row.get("notes"):
                self.listing.setComment(self.addr(address), CodeUnit.PLATE_COMMENT, row["notes"])


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true",
                        help="delete an existing project (run `make export` first!)")
    parser.add_argument("--no-analysis", action="store_true", help="skip auto-analysis")
    args = parser.parse_args()

    cfg = load_config()
    if PROJECT_DIR.exists():
        if not args.force:
            sys.exit(f"{PROJECT_DIR.relative_to(ROOT)} exists. Export your names with "
                     "`make export`, then rebuild with `make rebuild`.")
        shutil.rmtree(PROJECT_DIR)
    PROJECT_DIR.mkdir(parents=True)

    image = (ROOT / cfg["firmware"]["path"]).read_bytes()
    peripherals, interrupts = load_svd(ROOT / cfg["svd"]["path"])
    symbols = read_symbols()

    start_ghidra()
    from ghidra.base.project import GhidraProject
    from ghidra.program.database import ProgramDB
    from ghidra.program.model.lang import LanguageID
    from ghidra.program.util import DefaultLanguageService

    project = GhidraProject.createProject(str(PROJECT_DIR), PROJECT_NAME, False)
    language = DefaultLanguageService.getLanguageService().getLanguage(
        LanguageID(cfg["firmware"]["language"]))
    program = ProgramDB(PROGRAM_NAME, language, language.getDefaultCompilerSpec(), project)

    builder = Builder(program, image, cfg)
    tx = program.startTransaction("build from config")
    try:
        print("memory map")
        builder.create_memory()
        print(f"SVD: {len(peripherals)} peripherals")
        builder.create_peripherals(peripherals)
        print("vector tables")
        builder.create_vectors(interrupts)
        print(f"symbols.csv: {len(symbols)} symbols")
        builder.apply_symbols(symbols)
    finally:
        program.endTransaction(tx, True)

    if not args.no_analysis:
        print("auto-analysis (takes a few minutes)")
        tx = program.startTransaction("auto-analysis")
        try:
            GhidraProject.analyze(program)
            # Analysis may rename functions; make sure our names win.
            builder.apply_symbols(symbols)
        finally:
            program.endTransaction(tx, True)

    project.saveAs(program, "/", PROGRAM_NAME, True)
    functions = program.getFunctionManager().getFunctionCount()
    project.close()
    print(f"done: {functions} functions in {PROJECT_DIR.relative_to(ROOT)}/{PROJECT_NAME}.gpr")


if __name__ == "__main__":
    main()
