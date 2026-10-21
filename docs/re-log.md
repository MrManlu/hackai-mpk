# Research log

A diary of the project: what we tried each day, what went wrong, why, and how
it was solved. Dead ends stay in, they are part of the story. Newest entries
at the bottom.

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

## 7 October 2026: Image layout and toolchain

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

## 8 October 2026: First light in an emulator

**The idea:** develop without the hardware on the desk, with a simulator that
runs AKAI's firmware unmodified and shows the OLED in a window.

**Quick feasibility test with Unicorn** (a CPU-only emulator usable from
Python): with no peripherals at all, the bootloader set up the clocks, SysTick,
GPIO, SPI2 and DMA1 channel 5 (the display), then got stuck at `0x08003DE2`,
waiting for a 64-bit counter to advance by 5000. That counter is incremented
by the SysTick interrupt, and Unicorn has no interrupts. Good sign: the
firmware runs, and every obstacle shows up as a clear "waiting for X".

**Unicorn vs QEMU vs Renode:** Unicorn is only a CPU; QEMU has few STM32 boards
and its models are C; Renode (Antmicro) is built for this: platforms described
in text files, peripherals in C#, an STM32F103 platform close to our AT32F415,
an STM32 SPI model and a TFT display model to start from. Chose Renode from
the start (installed in `/opt`).

**First problem:** Renode refused Artery's SVD file. Cause: values like
`read-write ` with a trailing space in `<access>`. Fix: a sanitised copy
generated by the Makefile.

**Result:** the real bootloader boots in Renode and draws **"Upgrade /
v01.13"** on a simulated SSD1306. Only two models of our own were needed.
But "Upgrade" means update mode: the bootloader thought we wanted to update.

## 14 October 2026: The stock firmware boots

**Why the bootloader stayed in update mode:** with the new `make decompile`
(Ghidra decompilation from the terminal) the boot code showed that it reads
two key-matrix columns, PC11 and PC13, which read **0 when pressed**. In the
simulator, unmodelled GPIO inputs read 0: two keys "held" at power-up, which
is exactly the update-mode combination (later identified as SHIFT + PROG
SELECT).

Fixed in three steps, each revealing the next obstacle:

1. Released PC11 and PC13: the application started, then waited forever for
   the USB core reset to finish. Fix: a minimal USB OTG FS model.
2. Then the **factory test mode** appeared ("Ver:Y01-13" and serial numbers):
   the application has its own power-up combinations (PC8 + PC12 = factory
   test; PC9 + PC13 = an endless display test, see 21 October).
3. Released all six columns: **main screen, "PGM1: MPC / BPM: 120"**.

Found on the way: the second copy of the bootloader is a **bootloader update**
the application installs if the last bytes differ, and the bootloader checks
the application only through two marker bytes, no checksum. Those bytes sit
inside the "free" area we wanted for patches.

**Noise:** the terminal filled with warnings (SPI1 data to nothing, late DMA
requests). `make sim` now hides the known noise, `make sim-debug` shows all.

**LEDs:** the hunch from the teardown was right: the LEDs hang off a chain of
**7 shift registers on SPI1**, refreshed every 200 µs with 32-phase software
PWM (latch on PB4). Modelled them.

**The GUI:** chose Qt (PySide6) over PyGame for a panel with the real layout.
It crashed on start-up by the end of the day, unsolved.

## 15 October 2026: A virtual front panel, and a kernel deadlock

**The GUI crash** turned out not to be ours: PySide6 **6.12.0 crashes** on
Python 3.11 after ~10 000 `QLabel.setText` calls (`none_dealloc`), with
nothing else involved. Pinned 6.11.2. Also: Qt objects must not be touched
from the monitor thread, so results go through a queue drained by a timer.

**"The screen scrolls when I press a key"** (seen on the panel): not a refresh
problem. The firmware streams the 512-byte framebuffer without re-setting the
start address, trusting the pointer to wrap. SPI2 is **shared** with another
device that receives 3-byte words on every key event (probably the CV DAC);
those bytes landed in the simulated OLED and shifted the picture. Fix: model
the OLED chip select (PB12).

**Button sweep:** a script presses every matrix position, resetting in
between, and records the screen and LEDs. It showed that our key matrix model
was **wrong**: the rows are not one-hot, PC0–PC3 carry a **binary row number
(0–12) into a decoder**. Later the encoder push showed up in column 6, so
there are 8 columns, not 6.

Observations on the real unit, each turned into a confirmed fact:

- "LED 53 blinks": the TAP tempo LED.
- "BANK A/B turns from red to green": a two-colour LED, outputs 21 (red) and
  22 (green).
- "PROG SELECT lights the top-right pad in the simulator, but PAD 1 on the
  real one": the pad LED order in the chain is **reversed** (pad n = triplet
  8 − n).
- "When I release PROG SELECT it acts as if pressed again": not a bug, the
  button has two modes (hold + pad, or release + encoder).
- Pads light blue when hit in the MPC program, red otherwise: the colour
  order in each triplet is blue, green, red.
- "ARP leaves its menu when I release it": the same hold/release design.

Panel usability: right click latches a button; a latched SHIFT is released by
the next button (as SHIFT is used on the real unit); a small legend explains
it.

**Analogue controls:** ADC1, 5 channels, behind **multiplexers** selected by
PB0–PB2 (pads, knobs, wheels, joystick). The ADC DMA needs 16-bit accesses.
Endless knobs have two wipers.

**Keybed:** the hypothesis was "velocity is the time between two contacts".
Exactly: rows 0–9 are the keys in pairs, top contact and bottom contact, and
every matrix change is stored with a 64-bit time stamp.

**New roadmap item:** a per-pad MIDI channel (for the Digitakt), after THRU.

**The MIDI bridge and the deadlock.** The first bridge between the simulator
and the desktop used ALSA sequencer virtual ports (python-rtmidi). A test hung
and was killed with `kill -9` while inside ALSA. Result: the kernel `snd-seq`
**deadlocked**. Every program opening the sequencer (even `aconnect -l`),
then PipeWire itself, got stuck in uninterruptible sleep (D state); the desktop
lost its audio. Restarting PipeWire did not help (and `sudo systemctl --user`
fails with "No medium found": user services must be restarted without sudo).
Only a **reboot** fixed it.

After the reboot, a careful retest without `kill -9`: the bridge worked in
both directions, but the processes hung again in the kernel at exit
(`seq_free_client`). Conclusion: a kernel bug in snd-seq teardown (Debian
6.1.0-53), not only the kill. ALSA sequencer: abandoned on this machine.

While the machine rebooted: analysed the **bootloader**: boot decision, the
USB HID update protocol, and flow diagrams (Mermaid). Renamed its functions
to say what they do.

**JACK instead:** installed `pipewire-jack`. python-rtmidi still did not see
PipeWire's JACK: its wheel **bundles its own libjack** (classic jackd). Switched
to `JACK-Client`, which loads the system library: the bridge works through
JACK/PipeWire (`make gui JACK=1`), with clean exits.

## 16 October 2026: The updater

**Anti-rollback?** None: the bootloader never compares versions (`C4` only
reports the installed one), and the application's bootloader self-update
checks for *different* bytes, not newer ones.

To let the simulated bootloader flash, the simulator needed a **flash
controller** model. Two surprises:

- Erase and program did nothing. Cause: the firmware refuses addresses beyond
  `F_SIZE` × 1 KB, and `F_SIZE` (device information at `0x1FFFF7E0`) read 0.
  Fix: system memory with `F_SIZE` = 256.
- The reset macro reloaded the image, wiping whatever the firmware wrote.
  Fix: load once.

With flash persisting across resets, the application revealed that it
**formats the user programs at first boot** (16 sector erases at
`0x0802F000`). The "free" area shrank to `0x08025D4C`–`0x0802DFFF`.

**`tools/mpkflash.py`:** image safety checks, then the protocol (`C4`, `C1`,
`C2` × ~15 000, `C3`), with a simulator transport that writes packets straight
into the bootloader's receive ring in RAM.

- First full run: killed after 10 minutes with no output. Each Renode monitor
  round trip costs ~0.1 s, and every packet needed three. Fix: **256 packets
  per monitor command**, reading back only each reply's status: ~3 minutes.
- The last command, `C3`, "never finished": the bootloader replies and then
  resets, so its read index never moves. Fix: done when either the index moves
  or the reply appears.
- Verified by reading the whole flash back: byte-identical, and the
  application boots.
- Found that the **application also answers `C4`, with `E4`**, and ignores
  every other command: a safe way to refuse to flash a unit that is not in
  update mode.

## 21 October 2026: Real hardware, the screensaver and our first code

**First contact with the real unit:** `/dev/hidraw1` was root-only; a udev
rule fixed it. `C4` in update mode answered `F4` 1.13; in normal mode `E4`.
Then the real test: **reflashing the stock firmware**, 14 976 packets in 31 s
(2 ms per packet: the 1 ms USB poll each way). The unit restarted by itself.

**Screensaver mod** (first mod): replace the "AKAI Professional" logo.

- *(Dead end)* The string "Akai Professional" in the application is only the
  USB manufacturer name.
- Hint from the real unit: the screensaver comes after 3–5 minutes idle.
  *(Dead end)* A constant 150 000 (5 min in 2 ms ticks?) turned out to belong
  to the CC edit code.
- Rendering the constant data as OLED pages found two fonts and some icons,
  not the logo; the end of the application is compressed init data.
- Background run of the idle simulator to catch the screensaver: too slow
  (30 virtual seconds took ~2 minutes) and it died on a socket timeout.
- What worked: the framebuffer (`0x20003BD0`) is **column-major**, 4 bytes per
  column. That led to the bitmap draw routine and its callers: the 128 × 32
  logo at `0x080248CC`, used by an endless display test and by the
  **screensaver** state machine (15 000 001 ticks of 20 µs = 5 min, inverted
  every 5 s).
- Simulator check without waiting: move the "last activity" time stamp 5
  minutes back. First try failed: during the boot screen the state machine
  resets that time stamp on its way to the normal state, so the script now
  waits for the normal state (and a typo in its address cost one more run).
- Flashed: the custom image appears on the real OLED, inverting every 5 s.

**Menus:** to switch THRU on and off we want our own menu entries. The Global
menu (SHIFT + STOP) has **no menu table**: six entries hard-coded in if-chains,
in a draw function and an encoder function, with the last index as a constant.
Its settings are **per program**, not global.

**Free bytes in the programs?** Mapped the 331-byte program format (name,
settings, 16 pads, 8 knobs). Every settings byte is used by the code, and the
PC editor writes whole programs: no room. Our settings get their own flash
sector instead.

**Free RAM?** Filled the RAM above the stack with `0xA5` in the simulator,
used the UI for a while and looked at what changed: nothing above
`0x20005228` is ever touched (some literals look like addresses up there, but
they are constants).

**The patch system:** C code compiled with GCC and linked at `0x08026000`,
stock functions called by their names from `symbols.csv`, stock functions
replaced by a `B.W` at their entry. Worry before the first run: GNU ld could
emit `BLX` to the stock code, which would switch to ARM state and crash a
Cortex-M; the disassembly showed plain `BL`.

First patch: the Global menu rewritten in C with a 7th entry, **THRU**,
stored in our settings sector as a log of 32-byte records. In the simulator,
entries 1–5 are pixel-identical to the stock ones, THRU reaches the flash and
survives a reset. On the real unit, combined with the screensaver: works,
first time. The THRU itself is still to be written.

Lesson about the tooling: `make export` writes Ghidra's names back to
`symbols.csv` and would undo names changed directly in the CSV; after such
changes, rebuild the Ghidra project instead.

**MIDI THRU, the real thing (same day, afternoon).** Following the DIN IN
bytes through the code: the receive interrupt fills a 128-byte ring, and a
main-loop task parses the bytes into USB-MIDI packets. Then the surprise: the
packets go to the **same queue as the keyboard's events for the computer**.
And the function that sends that queue over USB also copies each event to
DIN OUT, but only when the USB send *fails*. So the stock routing is:

- with a computer, keyboard → USB, DIN IN → USB, computer port "MIDI 2" →
  DIN OUT (a USB ↔ DIN interface);
- without a computer, keyboard → DIN OUT, and DIN IN → only local handling
  (CV output and transport LEDs). DIN IN never reaches DIN OUT.

The real unit agrees: plugged into a computer it bridges USB and DIN; on a
power bank it does not. Found on the way: notes `0x73`–`0x77` sent to the unit
light the transport LEDs, a first bit of "LED feedback" already in the stock
firmware.

Two things to watch in the stock code: the DIN OUT queue function has **no
overflow check**, and the parser's return value was ambiguous in Ghidra
(`undefined8`); the disassembly showed a byte in `r0`, 1 when a message is
complete.

THRU: replaced the DIN IN task with a C version that does the same and, with
THRU on, queues each **complete** message for DIN OUT (after checking the free
space). A new script feeds bytes into the simulated DIN IN and reads DIN OUT.
First run: everything came out except the SysEx, of which only `F7` arrived.
The cause was not the firmware but **our simulator's MIDI monitor**: it took
the closing `F7` (a byte ≥ `0x80`) as a new status byte and threw away the
`F0 7E 7F 06 01` before it. Fixed the monitor: all six checks pass (stock never
forwards; THRU off forwards nothing; THRU on forwards notes with running
status, clock, CC, program change and SysEx in order; messages stay whole
while a key is played; still on after a reset).

Tooling: `make decompile-all` writes every function to `build/decompiled.c`,
which made searching for the ring's readers and writers a matter of `grep`.

**Per-pad MIDI channel (same day, evening).** Without the Digitakt at hand,
the THRU hardware test had to wait, so we moved on to roadmap item 2. The
stock pad edit menu (SHIFT + PROG SELECT, then hit a pad) already has seven
settings per pad (note, CC, PC, two colours, mode, toggle), but no channel:
every pad uses PadCH. Chose a per-pad entry in that menu, "8. Chan: Glob /
1–16".

Where the channel comes from: on a hit, one instruction at `0x08019F5C` loads
PadCH and the next stores it in the pad's state record; note on, note off,
CC, PC and aftertouch all use that copy. Good news: replacing that one load is
enough, and the note off keeps the channel of its note on. Note repeat has
the same load-and-store at `0x0801A564`; without patching it too, repeated
notes would have jumped back to PadCH.

The pad menu's encoder also updates the pad LED colours live, so instead of
rewriting it, the patch system grew two new hook kinds:

- **wrap**: our function runs first and can call the stock one through a
  generated trampoline (the displaced instructions, then a jump back). The
  build refuses instructions that depend on their address. First version of
  that check missed `LDRH` with a literal; rewritten to catch any 32-bit load
  based on PC.
- **jump**: one instruction becomes a jump to a small assembly routine that
  keeps every register, calls C, and jumps back. Before patching, the build
  checks the exact bytes it replaces.

In the simulator: hit pad 1 → `99 24 6A` (channel 10); set Chan 3 → `92 25
6A` / `82 25 00`; pad 2 still on 10; the stock entries 1–7 look and work as
before; channel kept after a reset. One difference noticed along the way: the
note edited from the menu went back to 36 after the reset (stock settings
need SAVE), while our channel stayed: ours is saved at once and global.

Question from the user: pad 1 down, pad 2 down, pad 1 up: does each note off
go out on the right channel? It should, since each pad keeps its channel in
its own state record, but we tested it. The first run "failed": two extra
messages per pad that the test did not expect. They were **poly aftertouch**
(the MPC program has PadAT = Poly, so a held pad sends pressure), and they
also went out on each pad's own channel. Notes: `92` on, `99` on, `82` off,
`89` off, as hoped. The test now checks notes and aftertouch separately.

On the real unit, flashed with screensaver + THRU + pad channels (31 s): pad 1
set to Chan 3 from the new menu entry. To watch the MIDI from the computer we
used `amidi -d` on the raw MIDI port (not the ALSA sequencer that deadlocked
on 15 October). First attempt showed nothing: its output went through a pipe,
was buffered, and was lost when `timeout` stopped it. With `stdbuf -oL` into
a file: 364 messages in 40 seconds, pad 1 on channel 3, the others on 10,
overlapping pads, every note off on its note on's channel, no hanging notes,
aftertouch per pad too. Per-pad MIDI channel: done.
