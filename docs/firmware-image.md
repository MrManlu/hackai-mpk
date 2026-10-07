# Firmware image

> The firmware is copyrighted by inMusic Brands. **Do not commit it** (or dumps
> of it) to this repository. Each user should extract it from the official
> updater or from their own unit.

## Extracting it from the official updater

The Windows updater (`MPK.exe`) is an archive that `7z` can open:

```bash
7z x MPK.exe
```

The firmware is the largest single file in the extracted tree (a disk-usage
viewer such as `baobab` or `du -a | sort -n` finds it quickly). In the
version analysed it was a 262 144-byte (256 KB) file named `130`.

Check the first two words, which form the Cortex-M vector table:

```bash
xxd -e -l 16 130
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
| `0x3FFF0` | `0x0803FFF0` | 16 B | Trailer (`…09e80054ff0c0113ffff…b247`) | unknown, maybe version/checksum |

Vector tables:

| Image | Initial SP | Reset_Handler |
|---|---|---|
| Bootloader | `0x20002748` | `0x08004240` |
| Application | `0x20005228` | `0x08024F64` |

(The handler addresses are the vector values with the Thumb bit cleared.)

Open questions:

- [ ] Why is the bootloader stored twice? Backup slot, or an artefact of how
      the updater builds the image?
- [ ] Format of the data blocks at `0x37000` and of the trailer.
- [ ] How the bootloader checks the application before jumping to it
      (checksum/CRC), which matters before flashing a patched image.
- [ ] Protocol used by the updater over USB (probably SysEx).
- [ ] Meaning of the file name `130` (firmware version 1.3.0?).
