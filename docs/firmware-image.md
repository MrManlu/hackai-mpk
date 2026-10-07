# Firmware image

> The firmware is copyrighted by inMusic Brands. **Do not commit it** (or dumps
> of it) to this repository. Each user should extract it from the official
> updater or from their own unit.

## Extracting it from the official updater

The reference firmware is **v1.13**, from the official Windows updater
`MPK_mini_Plus_Updater_v1.13.exe`. The repository tool finds and verifies it:

```bash
make baserom SRC=/path/to/MPK_mini_Plus_Updater_v1.13.exe
```

How it works: the updater is a PE executable whose resources `7z` can list.
The firmware is stored as a custom resource of type `RT_BIN` with ID `130`
(`.rsrc/0/RT_BIN/130`, repeated under another language ID). It is
262 144 bytes, the size of the MCU flash. Its SHA-256 is in
[`config/baserom.sha256`](../config/baserom.sha256).

Check the first two words, which form the Cortex-M vector table:

```bash
xxd -e -l 16 baserom/firmware.bin
# 00000000: 20002748 08004241 08004289 0800428d
#           ^ initial SP  ^ Reset_Handler (Thumb bit set)
```

## Layout

The file is exactly the size of the MCU flash and maps 1:1 onto
`0x08000000`.

| File offset | Address | Size | Contents | Status |
|---|---|---|---|---|
| `0x00000` | `0x08000000` | 20 KB | **Bootloader** (vector table, flash routines, "Upgrade" screen) | confirmed |
| `0x05000` | `0x08005000` | 20 KB | Byte-for-byte **copy of the bootloader** | confirmed (purpose unknown) |
| `0x0A000` | `0x0800A000` | ~111 KB | **Application** (code ends around `0x25D4C`) | confirmed |
| `0x25D4C` | | | Zero padding | confirmed |
| `0x37000` | `0x08037000` | 9 × 4 KB | Blocks that each hold `0x14B` bytes of data | hypothesis: programs/presets and settings |
| `0x3FFF0` | `0x0803FFF0` | 16 B | Trailer `09e80054ff0c0113ffffffffffffb247` | partly known, see below |

The trailer holds the firmware version in BCD at `0x0803FFF6` (major, `01`)
and `0x0803FFF7` (minor, `13`): **v1.13**. The application reads them for the
version screen (`Ver Y00.00`). The other bytes are unknown (checksum?).

Vector tables:

| Image | Initial SP | Reset_Handler |
|---|---|---|
| Bootloader | `0x20002748` | `0x08004240` |
| Application | `0x20005228` | `0x08024F64` |

(The handler addresses are the vector values with the Thumb bit cleared.)

Both tables have 92 entries (IRQ 0–75). With IAR, every unused handler is its
own 4-byte infinite loop, so the handlers with real code stand out:

| Handler | Bootloader | Application | Probable role |
|---|---|---|---|
| `SysTick_Handler` | `0x08003D78` | `0x080204A0` | System tick / delays |
| `IRQ67_IRQHandler` | `0x08003EFA` | `0x08024588` | **USB OTG FS** (hypothesis*) |
| `USART1_IRQHandler` | — | `0x0801B740` | **MIDI DIN** (hypothesis) |
| `TMR3_IRQHandler` | — | `0x0801AD1A` | Periodic timer (scanning, arpeggiator clock?) |

(*) IRQ 67 is the OTG FS interrupt on the STM32F105/107, which the AT32F415
follows. The SVD says 77 for `OTGFS`, which does not fit in a 76-IRQ table, so
the SVD is probably wrong there. The bootloader uses only SysTick and USB,
which fits a USB update mode.

Open questions:

- [ ] Why is the bootloader stored twice? Backup slot, or an artefact of how
      the updater builds the image?
- [ ] Format of the data blocks at `0x37000` and of the trailer.
- [ ] How the bootloader checks the application before jumping to it
      (checksum/CRC), which matters before flashing a patched image.
- [ ] Protocol used by the updater over USB (probably SysEx).
- [ ] Meaning of the other trailer bytes.
