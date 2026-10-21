# Documentation

Reverse-engineering notes for the AKAI MPK Mini Plus.

| Document | Contents |
|---|---|
| [decomp-plan.md](decomp-plan.md) | Decompilation strategy and milestones |
| [tools.md](tools.md) | Requirements, `make` targets and the daily workflow |
| [hardware.md](hardware.md) | MCU, debug header, display wiring and other board-level facts |
| [bootloader.md](bootloader.md) | Boot decision and USB HID update protocol, with flow diagrams |
| [updater.md](updater.md) | `tools/mpkflash.py`: image safety checks, flashing the simulator and the real unit over USB, anti-rollback |
| [screensaver.md](screensaver.md) | Screensaver mod: bitmap location and format, timing, `make screensaver` |
| [firmware-image.md](firmware-image.md) | How to get the firmware from the official updater and how the image is laid out |
| [ghidra-setup.md](ghidra-setup.md) | Why the Ghidra project is built the way it is, lessons from the manual attempts |
| [subsystems.md](subsystems.md) | First map of the subsystems (MIDI, LEDs, ADC, timers) |
| [simulator.md](simulator.md) | Running the firmware in Renode: `make sim`, models, known blockers |
| [leds.md](leds.md) | Shift-register LED chain on SPI1, software PWM, output map |
| [display.md](display.md) | OLED controller, init sequence and the bootloader/app print routines |
| [re-log.md](re-log.md) | Chronological research log, including dead ends and lessons learned |

## Conventions

- Addresses are absolute (`0x0800xxxx`) unless marked as a **file offset**.
- Function names such as `print_LCD_APP` are names given during analysis, not
  original symbols. The suffix `_BL` means bootloader, `_APP` means application.
- Facts are marked as **confirmed** (checked on hardware or in the binary) or
  **hypothesis** (plausible, needs checking).
- Never paste large chunks of decompiled or disassembled vendor code. Describe
  the behaviour, give addresses and short snippets only when necessary.
