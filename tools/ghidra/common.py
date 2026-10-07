"""Shared helpers for the PyGhidra tools: configuration, paths and project access."""

import csv
import os
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"
SEGMENTS = CONFIG / "segments.toml"
SYMBOLS = CONFIG / "symbols.csv"

PROJECT_DIR = ROOT / "build" / "ghidra"
PROJECT_NAME = "hackai-mpk"
PROGRAM_NAME = "firmware"

SYMBOL_FIELDS = ["address", "kind", "name", "type", "status", "notes"]
STATUSES = ["named", "typed", "understood", "reimplemented"]


def load_config():
    with SEGMENTS.open("rb") as f:
        return tomllib.load(f)


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


def read_symbols(path=SYMBOLS):
    """Return the symbols as a dict keyed by integer address."""
    if not path.exists():
        return {}
    with path.open(newline="") as f:
        rows = [row for row in csv.DictReader(f) if not row["address"].startswith("#")]
    return {int(row["address"], 16): row for row in rows}


def write_symbols(symbols, path=SYMBOLS):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SYMBOL_FIELDS, lineterminator="\n")
        writer.writeheader()
        for addr in sorted(symbols):
            row = dict(symbols[addr])
            row["address"] = f"0x{addr:08X}"
            writer.writerow({k: row.get(k, "") for k in SYMBOL_FIELDS})


def start_ghidra():
    """Start the JVM. GHIDRA_INSTALL_DIR must point to the Ghidra install."""
    import pyghidra

    if not os.environ.get("GHIDRA_INSTALL_DIR"):
        raise SystemExit("set GHIDRA_INSTALL_DIR to your Ghidra installation")
    if not pyghidra.started():
        pyghidra.start()


def open_project():
    from ghidra.base.project import GhidraProject

    if not (PROJECT_DIR / f"{PROJECT_NAME}.gpr").exists():
        raise SystemExit("no Ghidra project yet: run `make ghidra`")
    return GhidraProject.openProject(str(PROJECT_DIR), PROJECT_NAME, True)
