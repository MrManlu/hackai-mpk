# Decompilation plan

How we turn the stock firmware into something we understand and can extend,
in a way that is **automatic and reproducible**: anyone with the stock
firmware can rebuild the same analysis with one command.

## Approach: functional equivalence, not matching

Game decompilation projects (SM64, OoT…) aim for *matching* decompilation:
C code that, built with the original compiler, gives a byte-identical binary.
That is not realistic here:

- The firmware was built with **IAR Embedded Workbench for ARM** (see
  [Toolchain fingerprint](#toolchain-fingerprint)). IAR is commercial, the free
  edition is limited to 32 KB of code (the application is ~111 KB), and we
  would need the exact version and flags.
- decomp.me and similar tools do not support IAR.

We keep everything else from those projects (text-based knowledge in git,
one-command rebuilds, "bring your own firmware", progress tracking), but
replace byte matching with **functional equivalence checked by tests**, as
done by incremental PC decompilations such as LEGO Island (`isle`).

If an IAR licence becomes available later, the same structure allows moving
to matching.

## Principles

1. **Text is the source of truth.** Names, types and segments live in
   `config/` as text files. Ghidra projects are build artefacts and can always
   be regenerated.
2. **Bring your own firmware.** The stock image is never committed. Tools
   check its SHA-256 before using it.
3. **One command per step.** Everything goes through the `Makefile`.
4. **Measure progress.** A report shows how much of the firmware is named,
   typed and understood.
5. **Never flash without a way back.** Recovery over SWD is tested before any
   patched image goes on a device.

## Toolchain fingerprint

The application startup code (`Reset_Handler` at `0x08024F64`) is the IAR
runtime:

| Address | Routine | Evidence |
|---|---|---|
| `0x08024F64` | `Reset_Handler` | Sets MSP, calls `SystemInit`, jumps to `__iar_program_start` |
| `0x08024F80` | `__iar_program_start` | Sets up the stack and calls `__cmain` |
| `0x08024F1C` | `__cmain` | `__low_level_init` → `__iar_data_init3` → `main` → `exit` |
| `0x08024F3A` | `__low_level_init` | `movs r0, #1; bx lr` (default weak version) |
| `0x08024E94` | `__iar_data_init3` | Walks a PC-relative table of initialiser routines |
| `0x080243B4` | `main` | Called from `__cmain` |
| `0x08024F50` | `__exit` | Semihosting `bkpt 0xAB`, reason `0x18`, `ADP_Stopped_ApplicationExit` |

`nop.w` instructions in `__cmain` are calls removed by the IAR linker.

## Milestones

### M0 · Reproducible foundation

- [x] Reference firmware hash in `config/baserom.sha256`.
- [x] `make baserom`: find and verify the firmware (in the updater or as a raw file)
      and copy it to `baserom/`.
- [x] Python virtual environment with PyGhidra (`make setup`).
- [x] Document required tools in [tools.md](tools.md).

### M1 · Ghidra from text

- [x] `config/segments.toml`: memory map and firmware segments.
- [x] `config/symbols.csv`: address, type, name, status, notes.
- [x] `make ghidra`: build the Ghidra project from scratch (memory map, SVD
      peripherals, vector tables, symbols, auto-analysis).
- [x] `make export`: write names added in Ghidra back to `config/symbols.csv`.
- [x] Seed `symbols.csv` with the names from the 2025 analysis.
- [ ] `config/types.h`: data types, applied by `make ghidra`.

### M2 · Automatic map of the firmware

- [ ] Identify IAR runtime and Artery SDK functions (BSim, constant patterns).
- [x] Peripheral usage report: for each function, the peripherals it
      touches, as a first guess of its subsystem (`make report`, findings in
      [subsystems.md](subsystems.md)).
- [x] Interrupt table with handlers (see [firmware-image.md](firmware-image.md)).
- [ ] Call tree from `main`.
- [ ] `make progress`: progress report.

### SIM · Simulator

Run the stock firmware in Renode to develop and test without the hardware.
Details in [simulator.md](simulator.md).

- [x] AT32F415 platform and MPK Mini Plus board description.
- [x] Clock controller model (PLL, SysTick frequency).
- [x] SSD1306 model: the bootloader screen shows up in a window (`make sim`).
- [x] Bootloader jumps to the application.
- [x] Application boots to its main screen.
- [x] LEDs: shift-register chain model ([leds.md](leds.md)).
- [ ] Panel GUI (PySide6, drawn as SVG) connected to Renode over TCP.
- [ ] Inputs: keys, pads, knobs.
- [ ] MIDI DIN in/out bridged to a virtual ALSA MIDI port.

### M3 · Target subsystems

- [ ] MIDI: DIN in/out (UART) and USB MIDI.
- [ ] Pad LEDs: driver and colour palette.
- [ ] Arpeggiator: data model and step engine.
- [ ] Display and ADC (battery indicator).

### M4 · Hardware access and recovery

- [ ] SWD connection, readout protection status.
- [ ] Full flash dump of a real unit, compared with the reference image.
- [ ] Bootloader update protocol and image check (checksum/CRC).
- [ ] Tested restore of the stock firmware over SWD.

### M5 · Patch framework

- [ ] New code in C, built with GCC, linked against `symbols.csv`.
- [ ] Placed in free flash (~70 KB between `0x08025D4C` and `0x08037000`,
      to confirm that the bootloader writes it), avoiding the
      application-present marker at `0x0802E7FE`–`0x0802E7FF`.
- [ ] Hooks (branch patches) into stock functions.
- [ ] `make patch`: stock image + patches → verified output image.
- [ ] Differential tests in an emulator (Unicorn): original against
      reimplemented function, same inputs, same outputs.

### M6 · Features

1. Hello world: change the boot screen text (validates the whole chain).
2. MIDI THRU.
3. Pad LED feedback.
4. New arpeggiator modes.
5. Battery indicator.
