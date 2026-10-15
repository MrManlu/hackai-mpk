# Hardware

## Microcontroller

**Confirmed** (read from the chip marking after opening the case):

| Item | Value |
|---|---|
| Part | **Artery AT32F415RCT7** |
| Core | ARM Cortex-M4 |
| Package | LQFP-64 |
| Flash | 256 KB (`0x08000000`–`0x0803FFFF`) |
| SRAM | 32 KB (`0x20000000`–`0x20007FFF`) |
| USB | OTG full speed |

Despite the name, the AT32F415 is **not** a clone of the STM32F415. It is
Artery's own Cortex-M4 part, closely modelled on the **STM32F1** family: the
pinout and most peripheral register layouts follow the STM32F103/F105 style.
This explains two early observations (see [re-log.md](re-log.md)):

- The STM32F1 SVDs gave the best results in Ghidra (many hits on the clock
  controller at the RCC/CRM address).
- None of them showed any access to the USB peripheral. **Hypothesis:** the
  AT32F415 uses an OTG-style USB block (as in the STM32F105/107 connectivity
  line), not the F103 USB device block, so its registers sit at a different
  address.

Vendor resources (SVD, peripheral library, docs, toolchain support):
<https://github.com/ArteryTek/sdk-csp-at32f4>

## Debug header

**Confirmed:** the main board has a **populated SWD/JTAG header** (with SWO).

To document:

- [ ] Pinout of the header (photo + table)
- [ ] Whether readout protection is enabled
- [ ] Tested probes (ST-Link, J-Link, CMSIS-DAP, Artery AT-Link) and OpenOCD config

## Display

SSD1306-compatible OLED driven over **SPI2**. Details in [display.md](display.md).

| Signal | Pin | Status |
|---|---|---|
| SCK | PB13 (SPI2 default) | hypothesis |
| MOSI | PB15 (SPI2 default) | hypothesis |
| CS | PB12 | from code; confirmed in the simulator (another device shares SPI2, see [display.md](display.md#shared-bus-a-second-device-on-spi2)) |
| D/C | PB14 | from code |
| RESET | PB10 | from code |

"From code" means the pin is toggled by the display routines in the
bootloader. It still needs checking against the board traces.

## Other peripherals

To document: key matrix, pads (velocity sensing and RGB LED driver),
knobs, pitch/mod wheels, MIDI IN/OUT (UART used), CV/Gate outputs, power supply.

## Photos

To add: board top/bottom, MCU close-up, debug header.
