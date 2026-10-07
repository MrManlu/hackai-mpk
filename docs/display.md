# Display

## Controller and resolution

The init sequence sent by the bootloader (`SPI2_device_seems_LCD_init_BL`) is
the standard **SSD1306** command set. The `0x8D` charge-pump command is
SSD1306-specific (SH1106 uses `0xAD`), so this is an SSD1306 or compatible
controller.

The visible area is very likely **128 × 32**:

- Text is only drawn at rows `y = 0, 8, 16, 24` and up to `x ≈ 110`.
- The framebuffer flushed over DMA is **512 bytes** = 128 × 32 / 8.
- `0xDA 0x02` (sequential COM pins) is the usual setting for 128 × 32 panels.

The init still sets the multiplex ratio to 64 (`0xA8 0x3F`); this is
harmless but worth checking on the real panel.

## Init sequence

| Bytes | Meaning |
|---|---|
| `AE` | Display off |
| `00 10` | Column start address = 0 |
| `40` | Display start line = 0 |
| `81 xx` | Contrast: `9F` or `CF` (*) |
| `A6` | Normal (not inverted) |
| `A4` | Output follows RAM |
| `A8 3F` | Multiplex ratio = 64 |
| `D3 00` | Display offset = 0 |
| `D5 80` | Clock divide / oscillator |
| `D9 xx` | Pre-charge: `22` or `F1` (*) |
| `DA 02` | COM pins: sequential |
| `DB 20` | VCOMH deselect level |
| `20 00` | Horizontal addressing mode |
| `A0` / `C0` | Segment / COM scan direction (not remapped) |
| `8D xx` | Charge pump: `10` (off) or `14` (on) (*) |
| `AF` | Display on |

(*) These values depend on a flag in RAM. The two sets match the SSD1306
reference values for **external VCC** (`9F`, `22`, `10`) and **internal charge
pump** (`CF`, `F1`, `14`). **Hypothesis:** the firmware supports two panel
or board revisions.

Before the sequence, PB10 (RESET) is pulled low and released, waiting about
1000 ticks of a system timer before and after (the tick unit is not known yet).

## Bus

- **SPI2**, transmit only.
- Each byte is sent with D/C (PB14) low = command and CS (PB12) low during the
  transfer (bootloader, polled mode).
- The application sends the framebuffer through **DMA1 channel 5**, which is
  the SPI2_TX channel on STM32F1-style parts.

## Print routines

| Function (analysis name) | Image | Arguments | Notes |
|---|---|---|---|
| `print_LCD_BL` | Bootloader | `(x, y, str, font)` | Calls `print_LCD_char_POSSIBLE_BL` per character |
| `print_LCD_APP` | Application | `(x, y, str, font, invert)` | Extra last argument, always `0` so far. **Hypothesis:** pixel polarity (inverted text) |

Examples of screens drawn with `print_LCD_APP`: firmware version
(`Ver Y00.00`, major/minor in BCD), calibration of the analogue controls (`VR Reset`,
`VR UP Setting OK!`), pad/CC edit (`PAD 10`, `NOTE 000 CH0`, `CC 000 CH00`),
arpeggiator setup (`Arp Setup`, `ARP:`).

## Relevance for the battery mod

A battery icon needs a free area of the screen and a hook in the main UI
refresh. Next steps:

- [ ] Find the function that flushes the framebuffer and the RAM address of the buffer.
- [ ] Find the font tables (the `font` argument) and the glyph format.
- [ ] Map which screen areas are free on the main screen.
