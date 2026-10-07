# Ghidra setup

**The project is built automatically by `make ghidra`** (see
[tools.md](tools.md)). This page explains why it is built that way and keeps
the lessons from the manual attempts.

## Memory map and order of steps

The early manual attempts failed partly because the memory map was
incomplete when the SVD was loaded and the analysis was run. The order that
works, and the one the build script follows, is:

1. Memory blocks for flash and RAM.
2. Peripherals from the SVD.
3. Entry points (vector tables).
4. Auto-analysis.

The language is `ARM:LE:32:Cortex` (Thumb only, little endian).

## Flash mirror at 0x0

Like STM32 parts, the AT32 also maps flash at `0x00000000`, depending on
BOOT0. In the manual attempts:

- *with* a `flash_mirror` block at `0x0`: about 4000 functions left unanalysed;
- *without* it: about 2000.

The firmware does not seem to need the alias, so the build leaves it out. If
you find code that really jumps or reads below `0x08000000`, add a block for
it in `config/segments.toml`.

## Recognising library functions

The firmware uses Artery's standard peripheral library (`gpio_bits_set`,
`spi_i2s_flag_get`, `flash_sector_erase`…). FunctionID databases built from the
SDK with GCC (`-O0` and `-O2`) gave no matches. That is expected: the firmware
was built with **IAR** (see [decomp-plan.md](decomp-plan.md#toolchain-fingerprint)),
which generates different code.

Ideas for M2:

- [ ] BSim similarity search instead of exact hashes.
- [ ] Match by constants (peripheral base addresses, flag masks), which is how
      most names so far were assigned by hand.

## LLM-assisted plugins

Tried: GhidrOllama, GhidrAssist and ChatGPT-based Ghidra scripts (with
DeepSeek-R1, among others). Results were poor on this stripped firmware and
manual analysis was faster. Their output should not go into
`config/symbols.csv` without review.
