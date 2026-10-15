# Firmware updater

`tools/mpkflash.py` flashes firmware images over USB with the bootloader's own
protocol ([bootloader.md](bootloader.md#update-mode)). It works on the
simulator and on a real unit, with the same code path. Python 3 only, no extra
packages.

```bash
python3 tools/mpkflash.py check IMAGE          # safety checks, no device needed
python3 tools/mpkflash.py info  --sim | --hid  # ask the bootloader for its version
python3 tools/mpkflash.py flash IMAGE --sim    # flash the simulator, verify, show the boot screen
python3 tools/mpkflash.py flash IMAGE --hid    # flash a real unit
```

Or `make flash-check IMAGE=…`, `make flash-sim IMAGE=…`, `make flash IMAGE=…`.

## Anti-rollback

There is none. The bootloader never compares versions: `C4` only reports the
version of the installed image, and any image can be written over any other.
The only version comparison in the whole firmware is the application's
bootloader self-update (last byte of `0x08004FFF` vs `0x08009FFF`), which
checks for *difference*, not for an older or newer version.

## Safety checks

`check` (and `flash`, before touching anything) refuses an image unless:

| Check | Why |
|---|---|
| Size is 256 KB | The image maps 1:1 onto flash |
| Bootloader payload `0x08005000`–`0x08009FFF` identical to stock | At boot the application copies the payload over the bootloader when their last bytes differ: a bad payload bricks the unit (SWD only) |
| App-present marker `0x0802E7FE`–`0x0802E7FF` not `0xFF` | Otherwise the bootloader stays in update mode |
| Application vector table sane (SP in RAM, reset handler in the app) | A broken app is recoverable, but there is no point flashing it |
| Trailer starts with `09 E8 00 54` | Same layout as the stock image |

It warns when the configuration layout byte (`0x0803FFF5`) differs from stock:
the bootloader would then not keep the unit's calibration.

The bootloader area (`0x08000000`–`0x08004FFF`) is never sent: the bootloader
ignores writes there anyway.

## What `flash` does

1. `C4`: the version reply must be `F4`. The **application answers `E4`**
   (`hid_process_packet_APP`, `0x08024628`) and ignores every other command, so
   a unit that is not in update mode is detected and left alone.
2. `C1`: erase `0x08005000`–`0x0803EFFF`.
3. `C2` for every 16-byte chunk from `0x08005000` to `0x0803EFFF` that is not
   all `0xFF` (already erased), then the whole configuration sector
   `0x0803F800`–`0x0803FFFF` in order: its last chunk (the trailer) makes the
   bootloader commit it, keeping the serial and the calibration. Every reply
   must be `F2`. About 15 000 packets for the stock image.
4. `C3`: the bootloader resets into the new firmware.

## Simulator (`--sim`)

Starts Renode headless, powers on with SHIFT + PROG SELECT held (update mode)
and puts each packet straight into the bootloader's receive ring in RAM
(`0x20001630`, write index `0x2000173E`), as the USB interrupt would. The
simulated bootloader then does the real work: checksums, flash erase and
programming through the flash controller model
([simulator.md](simulator.md)). Packets go in batches of 256 per monitor
command (each round trip costs ~0.1 s): ~120 packets/s, about 3 minutes for a
full image.

After `C3` the tool reads the whole flash back, compares it with what the
update should leave, and prints the boot screen. `--sim-start-image` chooses
the firmware the simulator starts from (default: stock).

Validated: flashing a modified stock image (16 bytes changed in the free area)
gives a byte-exact flash and the application boots.

## Real unit (`--hid`)

Talks to `/dev/hidrawN` (found by VID/PID, or given as `--hid /dev/hidrawN`).
Reports are 32 bytes without report ID.

Permissions: install the udev rule once, then reconnect the unit.

```bash
sudo cp tools/udev/70-mpk-mini-plus.rules /etc/udev/rules.d/
```

```bash
sudo udevadm control --reload
```

To enter update mode: unplug, hold **SHIFT + PROG SELECT**, plug in. The OLED
shows "Upgrade" and the version.

Recommended first steps on hardware:

1. `info --hid` in update mode: must print `1.13`. Harmless.
2. `info --hid` with the unit running normally: must say that the application
   is running (the `E4` reply). Harmless.
3. `flash baserom/firmware.bin --hid`: reflash stock as a round trip.

If anything goes wrong during an update, the bootloader is untouched: enter
update mode again and reflash.
