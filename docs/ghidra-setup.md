# Ghidra setup

This procedure gives a clean analysis of the firmware image. **The order of
the steps matters.** Loading the SVD or running auto-analysis before the
memory map is complete gives much worse results.

## Requirements

- Ghidra
- [SVD-Loader-Ghidra](https://github.com/leveldown-security/SVD-Loader-Ghidra)
- The AT32F415 SVD from [ArteryTek/sdk-csp-at32f4](https://github.com/ArteryTek/sdk-csp-at32f4)

## Steps

1. **Import** the image as *Raw Binary*.
   - Language: `ARM:LE:32:Cortex` (Cortex, little endian).
   - Base address: `0x08000000`.
   - **Do not** run auto-analysis yet.

2. **Create the memory map** (*Window → Memory Map*):

   | Block | Start | Size | Permissions |
   |---|---|---|---|
   | `flash` | `0x08000000` | `0x40000` | R-X |
   | `ram` | `0x20000000` | `0x8000` | RW- (uninitialised) |
   | `flash_mirror` (optional, see below) | `0x00000000` | `0x40000` | R-X |

3. **Load the SVD** with `SVD-Loader.py`. This creates the peripheral blocks
   and register labels.

4. **Run auto-analysis.**

5. Disassemble from the reset handlers (`0x08004240` for the bootloader,
   `0x08024F64` for the application) and from the other vector table entries.

## Flash mirror at 0x0

Like STM32 parts, the AT32 maps flash at `0x00000000` too, depending on BOOT0.
Some code may reference that alias.

- *With* the mirror: about 4000 functions left unanalysed.
- *Without* the mirror: about 2000 functions left unanalysed.

Without the mirror is the better default. Add it only if you find code that
really jumps or reads below `0x08000000`.

## Recognising library functions

The firmware seems to use Artery's standard peripheral library (`gpio_bits_set`,
`spi_i2s_flag_get`, `flash_sector_erase`…). An attempt to identify these
automatically with **FunctionID** failed. The databases were built from
the SDK compiled with `arm-none-eabi-gcc -mcpu=cortex-m4 -mthumb` at `-O0`
and `-O2`, and neither gave any match. The vendor most probably used a
different compiler (Keil/IAR) or different flags.

Ideas to try:

- [ ] Build FunctionID databases with `-Os` / `-O3`, or with Keil ARMCC/ArmClang.
- [ ] BSim similarity search instead of exact hashes.
- [ ] Match by constants (peripheral base addresses, flag masks), which is how
      most names so far were assigned by hand.

## LLM-assisted plugins

Tried: GhidrOllama, GhidrAssist and ChatGPT-based Ghidra scripts (with
DeepSeek-R1, among others). Results were poor on this stripped firmware and
manual analysis was faster. They may help to name small leaf functions once
the context (peripherals, strings) is in place.
