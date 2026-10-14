# Simulator

The stock firmware runs unmodified in [Renode](https://renode.io), on a
simulated MPK Mini Plus. The OLED shows up in a window.

```bash
make sim                  # Renode GUI, the OLED in its own window
make sim-dump SIM_TIME=2  # headless: run 2 virtual seconds, print the OLED as text
```

Renode is expected in `/opt/renode_1.17.0-portable/` (the portable Linux
release, which bundles its own .NET). Use `RENODE=/path/to/renode` otherwise.

## Status

| What | Status |
|---|---|
| Bootloader boots, sets the PLL to 120 MHz, starts SysTick | ✅ |
| Bootloader draws its "Upgrade / v01.13" screen | ✅ |
| Bootloader jumps to the application | ❌ stays in update mode (see below) |
| Application | not reached yet |

## Files

| File | Contents |
|---|---|
| `sim/at32f415.repl` | The MCU: memory, NVIC, GPIO, DMA, USART, SPI, I2C, timers. Adapted from Renode's STM32F103 platform |
| `sim/mpk_mini_plus.repl` | The board: the MCU plus what is wired to it (OLED on SPI2, D/C on PB14) |
| `sim/mpk.resc` | Startup script: loads the C# models, the platform, the SVD and `baserom/firmware.bin` |
| `sim/peripherals/AT32_CRM.cs` | Clock controller: clocks report ready at once, SysTick follows the configured clock |
| `sim/peripherals/SSD1306.cs` | The OLED controller, drawn scaled up with a pixel grid. `spi2.oled AsciiArt` dumps it as text |

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

1. `make sim-dump` and look at the log for the place where the firmware is
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

## Open questions

- [ ] **Why does the bootloader stay in update mode?** Probably a button read
      at boot (GPIO) or a check of the application image. Find the decision
      in `bootloader_POSSIBLE_BL` (`0x08003DC8`).
- [ ] The first column of the "U" is drawn twice as thick. Stray data in
      column 0, or a bug in the SSD1306 model?
- [ ] USB OTG: the bootloader polls `GRSTCTL` (`0x50000010`). A stub that
      completes the core reset will be needed.
- [ ] `0x40007050` (in PWC, not in the SVD) is written at boot.
- [ ] Timers and peripheral clocks are fixed at 8 MHz in the `.repl`. The
      application's TMR3 will need the right frequency.
