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
| `0x05000` | `0x08005000` | 20 KB | **Bootloader update payload** (identical copy in v1.13) | confirmed |
| `0x0A000` | `0x0800A000` | ~111 KB | **Application** (code ends around `0x25D4C`) | confirmed |
| `0x25D4C` | `0x08025D4C` | ~33 KB | Zero padding: **free space for patches** | confirmed |
| `0x2E000` | `0x0802E000` | 4 KB | Zero padding with the **application-present marker** at `0x0802E7FE`–`0x0802E7FF` | confirmed |
| `0x2F000` | `0x0802F000` | 32 KB | **User programs**: zeros in the update image; the application formats them at first boot (16 sector erases, default programs such as "FLStudio20") | confirmed in the simulator |
| `0x37000` | `0x08037000` | 9 × 4 KB | Blocks that each hold `0x14B` bytes of data | hypothesis: factory presets |
| `0x3F800` | `0x0803F800` | 2 KB | **Configuration sector**: serial, calibration (`0x0803F820`), trailer. Preserved by the bootloader on updates | confirmed |
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

- [x] Why the bootloader is stored twice: it is a bootloader update payload,
      see [Boot sequence](#boot-sequence).
- [ ] Format of the data blocks at `0x37000` and of the trailer.
- [x] How the bootloader checks the application before jumping to it: only
      the two marker bytes, no checksum (see [Boot sequence](#boot-sequence)).
- [x] Protocol used by the updater over USB: HID, 32-byte "UO"/"UI"
      packets, see [bootloader.md](bootloader.md).
- [ ] Meaning of the other trailer bytes.

## Boot sequence

Found with the simulator ([simulator.md](simulator.md)) and Ghidra.

**Bootloader** (`bootloader_main_BL`, `0x08003DC8`):

1. Wait 100 ms (5000 SysTick ticks of 20 µs).
2. If either byte at `0x0802E7FE` / `0x0802E7FF` is `0xFF` (erased flash, no
   application), enter update mode.
3. Otherwise read two keys (PC11 + PC13, see [simulator.md](simulator.md#key-matrix-and-power-up-key-combinations)).
   Both held: update mode.
4. Otherwise jump to the application reset vector (`0x0800A004` →
   `0x08024F64`).

There is no checksum of the application. **For patching (M5):** the marker
bytes sit inside the free area after the application. They must stay
non-`0xFF`, and patch code must not be placed over them.

**Application** (`main`, `0x080243B4`):

1. Point `VTOR` at `0x0800A000` (`FUN_0802008c`).
2. **Bootloader self-update:** if the last byte of the bootloader
   (`0x08004FFF`) differs from the last byte of the payload (`0x08009FFF`) and
   the payload is not erased, erase the bootloader (2 KB sectors) and copy the
   20 KB payload over it (`FUN_08024592`). In v1.13 both bytes are `0x04`,
   probably the bootloader version.
3. Initialise presets, peripherals and the display.
4. Check the power-up key combinations (factory test mode, unknown mode).
5. Normal path: load the current program, initialise the rest, main loop.
