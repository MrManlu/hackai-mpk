# Simulator

The stock firmware runs unmodified in [Renode](https://renode.io), on a
simulated MPK Mini Plus.

```bash
make setup-gui            # once: PySide6 in .venv
make gui                  # the MPK Mini Plus panel: OLED, LEDs, buttons, RE panels
make sim                  # Renode GUI, the OLED in its own window
make sim-debug            # same, with every warning (to find missing models)
make sim-dump SIM_TIME=2  # headless: run 2 virtual seconds, print the OLED as text
```

Renode is expected in `/opt/renode_1.17.0-portable/` (the portable Linux
release, which bundles its own .NET). Use `RENODE=/path/to/renode` otherwise.

## Status

| What | Status |
|---|---|
| Bootloader boots, sets the PLL to 120 MHz, starts SysTick | ✅ |
| Bootloader draws its "Upgrade / v01.13" screen | ✅ |
| Bootloader jumps to the application | ✅ |
| Application boots to its main screen ("PGM1: MPC / BPM: 120") | ✅ |
| LEDs (shift-register chain on SPI1, PWM brightness) | ✅ see [leds.md](leds.md) |
| Key matrix (decoder on PC0–PC3, columns PC8–PC13) | ✅ model; 18 buttons mapped (rows 10–12) |
| Panel GUI (PySide6) | ✅ OLED, pad and LED outputs, matrix explorer |
| Keybed, pads (velocity), knobs, wheels, joystick, MIDI | ⚪ not modelled yet |

## Files

| File | Contents |
|---|---|
| `sim/at32f415.repl` | The MCU: memory, NVIC, GPIO, DMA, USART, SPI, I2C, timers. Adapted from Renode's STM32F103 platform |
| `sim/mpk_mini_plus.repl` | The board: the MCU plus what is wired to it (OLED on SPI2, D/C on PB14) |
| `sim/mpk.resc` | Startup script: loads the C# models, the platform, the SVD and `baserom/firmware.bin` |
| `sim/quiet.resc` | Silences known, harmless warnings for `make sim` |
| `sim/peripherals/AT32_CRM.cs` | Clock controller: clocks report ready at once, SysTick follows the configured clock |
| `sim/peripherals/AT32_OTGFS.cs` | USB OTG stub: the USB initialisation finishes as if no host were connected |
| `sim/peripherals/ShiftRegisterLeds.cs` | LED chain: 7 shift registers on SPI1, latch on PB4, average brightness per output |
| `sim/peripherals/SpiRecorder.cs` | Records raw SPI bursts with timestamps, for reverse engineering a bus |
| `sim/peripherals/KeyMatrix.cs` | Key matrix behind a row decoder (PC0–PC3 select row 0–12, PC8–PC13 read columns); `keys Press r c` / `keys Release r c` |
| `sim/scripts/matrix_sweep.py` | `make matrix-sweep`: presses every position on a fresh boot and reports what changes (`build/reports/matrix_sweep.md`) |
| `sim/gui/mpk_panel.py` | The panel GUI: starts Renode with its monitor on TCP and polls the OLED and LEDs |
| `sim/gui/mpk_mini_plus.svg` | The panel drawing. Every control has an `id`; editable in Inkscape |
| `sim/gui/mpk_mini_plus.toml` | Connects SVG ids to the simulator: pad LED channels, button LEDs and matrix positions |
| `sim/peripherals/SSD1306.cs` | The OLED controller, drawn scaled up with a pixel grid. `spi2.oled AsciiArt` dumps it as text, `spi2.oled Statistics` shows counters and state |

The C# models are compiled by Renode when the script loads them, so there is
nothing to build.

## How it works

The AT32F415 copies the STM32F1 register layout for most peripherals, so
Renode's STM32 models work as they are: `STM32F1GPIOPort`, `STM32_UART`,
`STM32SPI` (series F1), `STM32_Timer` and `STM32G0DMA` (same per-channel
layout as the F1 DMA). Interrupt numbers come from the AT32F415 SVD.

What is AT32-specific gets its own model in `sim/peripherals/`. Everything
without a model is still readable and writable: `ApplySVD` makes Renode log
each access with the register name, which is how missing models are found.

### Clocks

The bootloader switches to the PLL with `CRM_CFG = 0x20340000`: PLL source
HICK / 2 = 4 MHz, multiplier 30, **120 MHz**. This matches the SysTick reload
values it uses (`LOAD = 159` at 8 MHz and `LOAD = 2399` at 120 MHz, both
**20 µs per tick**). `AT32_CRM` computes the clock from `CFG` and gives it to
the NVIC.

## The workflow: run, find the blocker, model it

1. `make sim-debug` (or `make sim-dump`) and look at the log for the place where the firmware is
   stuck (`cpu PC`) and at the warnings about unimplemented registers.
2. Find that address in Ghidra: it is usually a loop waiting for a flag.
3. Model the minimum that releases it (in the `.repl`, or in a C# model).
4. Repeat.

Blockers found so far:

| Blocker | Fix |
|---|---|
| Loop on `CRM_CFG.SCLKSTS` after selecting the PLL | `AT32_CRM`: status follows the selection |
| SysTick ran 15× too slow (fixed 8 MHz) | `AT32_CRM` updates the NVIC frequency |
| Renode rejects Artery's SVD (`read-write ` with a trailing space) | `make` writes a cleaned copy for Renode |
| Bootloader stays in update mode: unpressed keys read 0 | `KeyMatrix` model: columns read high when no key is pressed |
| Application waits for the USB core reset (`GRSTCTL.AHBIDL`, `CSFTRST`) | `AT32_OTGFS` stub |
| Application enters the factory test mode (version screen) | Same as above: keys released |
| After `machine Reset` the bootloader always entered update mode | `KeyMatrix` re-drives its columns on every change (the GPIO port forgets them on reset) |
| OLED picture scrolls after pressing a key | Model the OLED chip select (PB12): the 3 bytes sent on each key event belong to another SPI2 device (CV DAC?) |

### Key matrix and power-up key combinations

The keys are read through a **row decoder**: the firmware writes a row
number (0–12) on PC0–PC3, a decoder (74HC154-style) pulls that row low, and
PC8–PC13 read 6 active-low columns. In normal operation it counts 0, 1, …, 12
over and over, reading the columns two or three times per row. That gives
**13 × 6 = 78 positions**:

| Rows | What | Evidence |
|---|---|---|
| 0–9 | Probably the keybed (37 keys; velocity usually needs two contacts per key) | No visible effect when pressed (`make matrix-sweep`) |
| 10–12 | The 18 buttons | LEDs and screens change; see the map below |

Button map, also in `sim/gui/mpk_mini_plus.toml` (C = confirmed by the screen
or an unambiguous behaviour, O = follows the panel order):

| Row | Col 0 (PC8) | Col 1 (PC9) | Col 2 (PC10) | Col 3 (PC11) | Col 4 (PC12) | Col 5 (PC13) |
|---|---|---|---|---|---|---|
| 10 | ARP (C), LED 54 | TAP TEMPO (O), LED 53? | NOTE REPEAT (C), LED 52 | FULL LEVEL (O), LED 50 | OCT − (O), LED 49 | OCT + (O), LED 48 |
| 11 | BANK A/B (C), LED red 21 / green 22 | SCALES (O), LED 19 | CHORDS (O), LED 17 | SHIFT (C), LED 14 | HOME/SAVE (O), LED 12? | PROG SELECT (C), LED 10 |
| 12 | ⏪ (O) | ⏩ (O) | STOP (O) | PLAY (O) | REC (O) | SEQ (O), LED 1 |

The transport LEDs are among outputs 2–6, not yet assigned. BANK A/B is a
two-colour LED: output 21 is red (bank A), 22 green (bank B), confirmed on the
real unit.

**PROG SELECT has two modes.** While held: "Load Program / Press pad to
Load Program" (hold + pad, as in the user guide). Once released: "Load
Program / PGM1: MPC / Enter to Load", browsing programs with the encoder and
loading with its push (LED 10 stays on). In the GUI, latch PROG SELECT with a
right click to use the pad mode. Neither the pads nor the encoder are
modelled yet.

Power-up combinations (both keys held while the firmware checks):

| Who | Row | Columns | Buttons (from the map) | Effect |
|---|---|---|---|---|
| Bootloader | 11 (`GPIOC = 0xB`) | PC11 + PC13 | SHIFT + PROG SELECT | USB **update mode** ("Upgrade" screen) |
| Application (`main`) | 10 (`GPIOC = 0xA`) | PC8 + PC12 | ARP + OCT − | **Factory test mode**: version screen "Ver:Y01-13", own main loop (`FUN_08012d6a`) |
| Application (`main`) | 10 | PC9 + PC13 | TAP TEMPO + OCT + | Calls `FUN_0801fe1a`, unknown (factory reset?) |

These button names come from the map above, so they are as good as its
"O" entries. Check them on the real unit before relying on them.

## Open questions

- [x] Why the bootloader stayed in update mode: keys read as pressed (see
      above).
- [ ] FLASH controller and system memory: the application unlocks the flash
      at boot and reads `0x1FFFF7E0` (flash size) thousands of times and
      `0x1FFFF806`. Not blocking, but saving presets needs a real model.
- [x] Map buttons to matrix positions and LED outputs (first pass, see
      above; "O" entries and the transport LEDs still to confirm).
- [ ] Rows 0-9: the keybed? Find how velocity is measured.
- [ ] MIDI OUT: the firmware sends USART1 data by DMA (`DMAT`), which
      Renode's `STM32_UART` does not support. Needs a small UART model or an
      extension before MIDI can be bridged to ALSA.
- [ ] IOMUX: the AT32 has extra remap registers at offsets `0x28` and `0x2C`
      that the STM32F1 AFIO model does not know.
- [x] The doubled first column on the OLED: SPI DMA requests re-entered
      Renode's DMA copy and duplicated bytes. Request lines are now left
      unconnected (see [leds.md](leds.md)).
- [ ] `0x40007050` (in PWC, not in the SVD) is written at boot.
- [ ] Timers and peripheral clocks are fixed at 8 MHz in the `.repl`. The
      application's TMR3 will need the right frequency.

## The panel GUI

`make gui` starts Renode headless with its monitor on a TCP port, runs
`sim/mpk.resc` and talks to the monitor: about 20 times a second it reads
`spi2.oled Framebuffer` and `spi1.leds Brightness`, and it sends
`keys Press/Release` when you click.

- **Panel**: OLED, pad colours (from the LED outputs and the channel order in
  the TOML), button LEDs and clickable buttons once their LED output and
  matrix position are known.
- **LED outputs**: the 56 outputs of the chain with their brightness.
- **Key matrix**: hold any row/column position to press it.
- **Left click** on a button is momentary; **right click latches** it (yellow
  outline) until the next right click. A latched **SHIFT** is sticky: it
  releases itself after the next button you press (`modifier = true` in the
  TOML). Other latched buttons stay held, so latching two and pressing Reset
  triggers the power-up combinations. Double-clicking SHIFT also works: that is the firmware's own
  Shift Lock.
- `--screenshot file.png --seconds 30` saves a capture and quits (tests).

Use **PySide6 6.11.2** (`sim/gui/requirements.txt`). 6.12.0 with Python 3.11
leaks references to `None` on every call that returns nothing and aborts
after a few thousand calls (`Fatal Python error: none_dealloc`).
