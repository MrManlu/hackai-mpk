# Simulator

The stock firmware runs unmodified in [Renode](https://renode.io), on a
simulated MPK Mini Plus. The OLED shows up in a window.

```bash
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
| Keys, pads, knobs, MIDI | ⚪ not modelled yet |

## Files

| File | Contents |
|---|---|
| `sim/at32f415.repl` | The MCU: memory, NVIC, GPIO, DMA, USART, SPI, I2C, timers. Adapted from Renode's STM32F103 platform |
| `sim/mpk_mini_plus.repl` | The board: the MCU plus what is wired to it (OLED on SPI2, D/C on PB14) |
| `sim/mpk.resc` | Startup script: loads the C# models, the platform, the SVD and `baserom/firmware.bin` |
| `sim/quiet.resc` | Silences known, harmless warnings for `make sim` |
| `sim/peripherals/AT32_CRM.cs` | Clock controller: clocks report ready at once, SysTick follows the configured clock |
| `sim/peripherals/AT32_OTGFS.cs` | USB OTG stub: the USB initialisation finishes as if no host were connected |
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
| Bootloader stays in update mode: unpressed keys read 0 | Key matrix columns PC8–PC13 set high (released) in `mpk.resc` |
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
- [ ] Key matrix model: map PC keyboard keys to row/column pairs.
- [ ] MIDI OUT: the firmware sends USART1 data by DMA (`DMAT`), which
      Renode's `STM32_UART` does not support. Needs a small UART model or an
      extension before MIDI can be bridged to ALSA.
- [ ] IOMUX: the AT32 has extra remap registers at offsets `0x28` and `0x2C`
      that the STM32F1 AFIO model does not know.
- [ ] The first column of the "U" is drawn twice as thick. Stray data in
      column 0, or a bug in the SSD1306 model?
- [ ] `0x40007050` (in PWC, not in the SVD) is written at boot.
- [ ] Timers and peripheral clocks are fixed at 8 MHz in the `.repl`. The
      application's TMR3 will need the right frequency.
