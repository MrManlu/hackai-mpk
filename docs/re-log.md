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

## October 2026: Image layout and toolchain

While writing these docs, a re-check of the image showed:

- The bootloader occupies the first 20 KB, and an identical copy follows at
  file offset `0x5000`.
- The application vector table is at `0x0800A000` (SP `0x20005228`,
  reset `0x08024F64`).
- The upper flash (`0x08037000`+) holds nine 4 KB blocks with `0x14B` bytes
  of data each, probably presets/settings.
- The display init is an SSD1306 sequence and the framebuffer is 512 bytes,
  so the panel is probably 128 × 32.
- The application startup code is the **IAR** runtime (`__iar_program_start`,
  `__cmain`, `__iar_data_init3`), which explains why FunctionID with GCC-built
  databases never matched. Decided against matching decompilation (see
  [decomp-plan.md](decomp-plan.md)).
- The firmware is the `RT_BIN/130` resource of the v1.13 updater, and the
  version (`01 13`, BCD) is stored at `0x0803FFF6`.
- Only four application interrupts have real handlers: SysTick, TMR3, USART1
  and IRQ 67 (probably USB).
- The Ghidra project is now built from `config/` by `make ghidra`, seeded with
  the 94 names from the 2025 project.

## October 2026: Simulator (Renode)

Built a Renode model of the board that runs the stock firmware unmodified
([simulator.md](simulator.md)). Each blocker taught something about the
hardware:

- Renode rejected Artery's SVD (stray whitespace in `<access>`): we feed it a
  sanitised copy.
- SysTick ran at the wrong rate until the clock (CRM) model told the NVIC the
  real core frequency.
- The bootloader kept entering update mode: with an unmodelled key matrix, the
  GPIO defaults looked like SHIFT + PROG SELECT held. Modelling the matrix
  fixed it, and showed the power-up key combination.
- The USB core reset wait needed a small OTG FS stub.
- SPI bytes came out twice: Renode's SPI DMA connection re-entered the
  transfer. Removing the DMA connections fixed it (the firmware's own DMA
  setup is enough).
- The OLED picture scrolled when a key was pressed: the SPI2 bus is shared
  with another device (3-byte words, probably the CV DAC). Modelling the chip
  select (PB12) fixed it.
- Key matrix *(two wrong guesses)*: rows are not one-hot but a 4-bit decoder
  (PC0–PC3, 13 rows), and there are 8 columns, not 6.
- GPIO ports forget input levels on reset, so the models re-drive both edges.
- The ADC DMA needs 16-bit accesses; the analogue controls sit behind
  multiplexers selected by PB0–PB2.
- LED brightness flickered until the PWM was measured over 64 latches.

Confirmed on the real unit along the way: BANK A/B is a red/green LED,
pad LEDs are blue/green/red per pad, and the pad order.

GUI: PySide6. **6.12.0 crashes** (`none_dealloc`) on Python 3.11: pinned 6.11.2.
Qt signals from the Renode monitor thread go through a queue drained by a timer.

### MIDI bridge *(one painful dead end)*

The first bridge used ALSA sequencer virtual ports (python-rtmidi). A test
process killed with `kill -9` inside ALSA left half-closed sequencer clients
and **deadlocked the kernel `snd-seq`** (Debian 6.1.0-53): every `aconnect`,
then PipeWire, got stuck in D state; only a reboot helped. Even clean exits
later hung in `seq_free_client`. Switched to **JACK through PipeWire**
(`JACK-Client` under `pw-jack`; python-rtmidi was dropped because its wheel
bundles its own libjack). Lesson: never SIGKILL ALSA MIDI processes.

## October 2026: Bootloader and the updater

Mapped the bootloader: boot decision (marker bytes, then SHIFT + PROG SELECT)
and the USB HID update protocol, "UO"/"UI" packets C1–C4
([bootloader.md](bootloader.md)). **No anti-rollback**: no version is ever
compared.

Flash in the simulator:

- Flash operations did nothing at first: the firmware refuses addresses beyond
  `F_SIZE` × 1 KB, and `F_SIZE` (`0x1FFFF7E0`) read 0. Added system memory
  with `F_SIZE` = 256.
- The reset macro reloaded the image, wiping what the firmware wrote: the
  image is now loaded once.
- With flash persisting, the application turned out to **format the user
  programs at first boot** (16 sector erases at `0x0802F000`). The "free"
  area is only `0x08025D4C`–`0x0802DFFF`.

`tools/mpkflash.py` ([updater.md](updater.md)):

- Simulator transport: packets are written straight into the bootloader's
  receive ring in RAM. Each monitor round trip costs ~0.1 s, so 15 000 packets
  took ~50 min one by one; batching 256 packets per monitor line brought it
  to ~3 min.
- `C3` replies and resets before the read index moves: done when either the
  index moves or a reply appears.
- The **application also answers `C4`, with `E4`**, and ignores the rest: a
  safe way to tell the bootloader (`F4`) from the application.
- Real unit (2026-10-21): `C4` probe in both modes, then a stock round-trip
  flash, 14 976 packets in 31 s (2 ms per packet, the 1 ms USB poll each way).

## October 2026: Screensaver mod

- *(Dead end)* The "Akai Professional" string at `0x0802502C` is only the USB
  manufacturer string (converted to UTF-16 for the descriptor).
- *(Dead end)* A constant 150000 (5 min in 2 ms ticks?) belongs to the CC
  edit code.
- Rendering the constant data as OLED pages found two fonts and icons; the
  end of the application is IAR-compressed init data, not bitmaps.
- The framebuffer (`0x20003BD0`) is column-major, 4 bytes per column, which
  led to the bitmap draw routine (`draw_bitmap_APP`) and the 128 × 32 logo at
  `0x080248CC`. Two users: an endless display test (factory) and the
  **screensaver** state machine: 15 000 001 ticks of 20 µs = 5 min, inverted
  every 5 s.
- Waiting 5 virtual minutes takes ~20 real minutes (the simulator runs ~4×
  slower than real time), so the check script moves the "last activity" time
  stamp back instead. First attempt failed: during the boot screen the state
  machine resets that time stamp on its way to the normal state, so the
  script must wait for state 2.
- Same-size data patch, no code. Confirmed on the real unit (2026-10-21).

## October 2026: Menus, programs and the first code patch

- The Global menu (SHIFT + STOP) has **no menu table**: six entries
  hard-coded in if-chains in a draw function and an encoder function, with
  the last index (5) as a constant ([menus.md](menus.md)).
- Its settings are **per program**, not global: bytes `0x10`–`0x1C` of the
  0x14B-byte program. Mapped the program format and looked for free bytes:
  every byte from `0x10` to `0x36` is used by the code (73 functions load the
  program base), and the PC editor writes whole programs. **No free bytes**
  ([programs.md](programs.md)).
- Free RAM: filling RAM above the stack with `0xA5` before boot and exercising
  the UI showed that nothing above `0x20005228` is ever touched (some app
  literals look like addresses up there but are constants).
- Patch system ([patching.md](patching.md)): C code linked at `0x08026000`,
  stock functions called by their analysis names, stock functions replaced by
  a `B.W` at their entry. Checked that GNU ld emits `BL` (not `BLX`) to
  absolute Thumb symbols. Settings in our own sector as a log of 32-byte
  records.
- First patch: the Global menu reimplemented in C with a 7th entry, THRU
  (setting only). In the simulator its screens for entries 1–5 are
  pixel-identical to the stock ones. Confirmed on the real unit (2026-10-21).
- Ghidra workflow: `make export` writes Ghidra's names back to
  `symbols.csv`, which would undo renames made in the CSV. When renaming in
  the CSV, rebuild the project (`build_project.py --force`) instead.
