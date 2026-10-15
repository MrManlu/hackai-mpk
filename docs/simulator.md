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
| Button matrix (rows PC0–PC3, columns PC8–PC13) | ✅ model; which button is where: to map |
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
| `sim/peripherals/KeyMatrix.cs` | Button matrix: rows driven by the firmware, columns read back; `keys Press r c` / `keys Release r c` |
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

### Key matrix and power-up key combinations

Rows PC0–PC3 are outputs, columns PC8–PC13 are active-low inputs. Both the
bootloader and the application drive a row pattern on GPIOC, wait, and read
two columns. Both columns low (both keys held) selects a special mode:

| Who | Rows written | Columns | Effect |
|---|---|---|---|
| Bootloader | `GPIOC = 0xB` (PC2 low) | PC11 + PC13 | USB **update mode** ("Upgrade" screen) |
| Application (`main`) | `GPIOC = 0xA` (PC0, PC2 low) | PC8 + PC12 | **Factory test mode**: version screen "Ver:Y01-13", serial-like strings, own main loop (`FUN_08012d6a`) |
| Application (`main`) | `GPIOC = 0xA` | PC9 + PC13 | Calls `FUN_0801fe1a`, unknown (factory reset?) |

Which physical keys these are is still to be found (they share rows, so the
key per row/column pair matters).

## Open questions

- [x] Why the bootloader stayed in update mode: keys read as pressed (see
      above).
- [ ] FLASH controller and system memory: the application unlocks the flash
      at boot and reads `0x1FFFF7E0` (flash size) thousands of times and
      `0x1FFFF806`. Not blocking, but saving presets needs a real model.
- [ ] Map which button sits at each matrix position and which LED output
      each button uses (GUI: "Key matrix" and "LED outputs" panels), and
      record them in `sim/gui/mpk_mini_plus.toml`.
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
- `--screenshot file.png --seconds 30` saves a capture and quits (tests).

Use **PySide6 6.11.2** (`sim/gui/requirements.txt`). 6.12.0 with Python 3.11
leaks references to `None` on every call that returns nothing and aborts
after a few thousand calls (`Fatal Python error: none_dealloc`).
