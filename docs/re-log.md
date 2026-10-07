# Research log

Chronological log of the reverse-engineering work, including the dead ends,
which are useful too. Newest entries go at the bottom.

## April 2025: Identifying the MCU

### Extracting the firmware

Extracted the official updater with `7z x MPK.exe` and found the firmware as
the largest file (see [firmware-image.md](firmware-image.md)). Its first
16 bytes, read with `xxd -e`, look like a Cortex-M vector table:

- Initial SP: `0x20002748`
- Reset_Handler: `0x08004241` (Thumb)

### Attempt 1: guessing the STM32 part *(dead end)*

Assumed the MCU was an STM32 (a reasonable guess, but wrong).

1. Estimated the package from a frame of a [teardown video](https://www.youtube.com/watch?v=INlp_lhpZmo), upscaled with a
   deep-learning upscaler: **LQFP-64** (this turned out correct).
2. Narrowed the candidates with the STM32 MCU selector:
   - LQFP-64
   - ≥ 256 KB flash (size of the image)
   - USB
3. Loaded each candidate's SVD in Ghidra. Expected result: many accesses to
   RCC and at least one to the USB peripheral.

Result: the **STM32F1xx** SVDs worked best (41 accesses to RCC), but no
candidate showed any USB access.

### Attempt 2: matching vector tables *(dead end)*

Compiled an empty Arduino sketch for every STM32 board in the STM32duino
core and compared the start of the vector table with the MPK image.

Useful commands:

```bash
# First words of .isr_vector in each ELF
for f in $(find . -name '*.elf'); do
  echo "------ $f"
  arm-none-eabi-objdump -s -j .isr_vector "$f" | grep 8000000 | cut -d' ' -f3
done

# Linker scripts shipped with the core
find ~/.arduino15/packages/STMicroelectronics/ -name '*.ld'

# First 8 bytes of every built .bin
for f in $(find sketch_apr10a/ -name '*.bin'); do
  echo "------ $f"; xxd -e -l8 "$f"
done
```

Result: no matches. The SP and reset values depend on the application's
RAM usage and code layout, so this method only works for nearly identical
firmware.

### Opening the case

Found a suitable screwdriver and opened the unit:

- MCU: **Artery AT32F415RCT7**, LQFP-64.
- A **populated SWD/JTAG header** on the board.

ArteryTek publishes the SVD, peripheral library, docs and toolchain
support: <https://github.com/ArteryTek/sdk-csp-at32f4>.

Takeaway: open the case first. It would have saved two attempts.

## April 2025: Ghidra analysis

### Memory map and order of steps

The early Ghidra attempts failed partly because the memory map was
incomplete. Creating `flash`, (optionally) `flash_mirror` at `0x0` and `ram`
**first**, then loading the SVD, then running auto-analysis, gives a usable
result. Leaving out the mirror halves the number of unanalysed functions
(~2000 against ~4000). Full procedure: [ghidra-setup.md](ghidra-setup.md).

### FunctionID *(dead end so far)*

Built FunctionID databases from the Artery SDK (`-O0` and `-O2`). No matches.
The vendor probably used another compiler or flags.

### LLM-assisted decompilation *(dead end so far)*

Tried ChatGPT-based Ghidra scripts, GhidrOllama and GhidrAssist (with
DeepSeek-R1 among others). Results were poor, so manual analysis continued.

### Display routines

Found the function that prints to the screen. It uses **SPI2 + DMA1 channel 5**.
The bootloader and the application each have their own version. The
application one takes an extra argument, probably pixel polarity.
Details in [display.md](display.md).

## October 2026: Review of the image layout

While writing these docs, a re-check of the image showed:

- The bootloader occupies the first 20 KB, and an identical copy follows at
  file offset `0x5000`.
- The application vector table is at `0x0800A000` (SP `0x20005228`,
  reset `0x08024F64`).
- The upper flash (`0x08037000`+) holds nine 4 KB blocks with `0x14B` bytes
  of data each, probably presets/settings.
- The display init is an SSD1306 sequence and the framebuffer is 512 bytes,
  so the panel is probably 128 × 32.
