# Screensaver mod

After 5 minutes without touching any control, the MPK Mini Plus shows the
"AKAI Professional" logo and swaps it between normal and inverted every 5
seconds. This mod replaces that bitmap with your own image.

```bash
make screensaver PNG=mods/screensaver/hackai.png   # → build/mods/screensaver.bin
make screensaver-sim                               # see it in the simulator (~1 min)
make flash IMAGE=build/mods/screensaver.bin        # flash a unit in update mode
```

Any image works: it is scaled to fit 128 × 32 (aspect ratio kept, centred)
and turned black and white. **White (bright) pixels light up**; transparency
counts as black. Options for `tools/screensaver.py patch` (or `OPTS=…`):
`--threshold N` (0–255, default 128), `--dither` (Floyd–Steinberg, for photos)
and `--invert`. `python3 tools/screensaver.py preview IMAGE` shows the result
as text without building anything. For crisp results, draw at exactly
128 × 32 with pure black and white.

`python3 tools/screensaver.py extract OUT.png` saves the bitmap of a firmware
image (the stock logo by default). The stock logo is AKAI's artwork: keep it
local, do not commit it.

## How it works

| Address | Name | What |
|---|---|---|
| `0x080248CC` | `bitmap_akai_logo_APP` | The bitmap: header `80 20` (128, 32), then 512 bytes |
| `0x0801FD2E` | `draw_bitmap_APP` | `draw_bitmap(x, y, bitmap, invert)` into the framebuffer |
| `0x08017D98` | `screensaver_update_APP` | UI idle state machine, called from the main loop |
| `0x0801FE1A` | `display_test_APP` | Endless display test (logo inverted, logo, all off, all on): factory test, also uses the bitmap |
| `0x20003BD0` | (framebuffer) | 512 bytes, sent to the SSD1306 by DMA |

**Bitmap format.** Two header bytes (width, height), then one column after
another from left to right; each column has ⌈height / 8⌉ bytes, the least
significant bit of the first byte being the top pixel. For 128 × 32 that is 4
bytes per column, the same layout as the framebuffer (column-major, not the
SSD1306 page order). Total 514 bytes, at a fixed place, so the mod is a plain
same-size data replacement: no code changes, no free space needed.

**Timing.** `screensaver_update_APP` keeps a state in `0x20004DA6`
(1 temporary screen such as the boot screen, 2 normal, 3 screensaver) and
compares the 64-bit tick counter (`0x20004CB8`, ticks of 20 µs) with the time
of the last activity (`0x20004BF0`):

- state 2, idle for ≥ 15 000 001 ticks (**300 s**): draw the bitmap, state 3;
- state 3, every 250 001 ticks (**5 s**): draw it again, inverted or not;
- any activity: back to the normal screen.

The timeouts are literals at `0x08018774` and `0x08018788`, so changing them
would be another easy mod.

## Simulator check

`sim/scripts/screensaver_check.py IMAGE` boots the image, waits for state 2,
then moves the last-activity time stamp 5 minutes into the past, so the
firmware believes nobody touched a control for 5 minutes. It prints the screen
at the screensaver and 5 s later (inverted). Waiting for real would take
about 18 minutes, since the simulator runs about 4× slower than real time.

**Confirmed on a real unit (2026-10-21):** flashed with `make flash`, the
screensaver shows `mods/screensaver/hackai.png` after 5 minutes idle and swaps
it between normal and inverted, like the stock logo.

Validated in the simulator (2026-10-21): with `mods/screensaver/hackai.png`
the screensaver shows the new image and inverts it after 5 s. The patched
image passes the `mpkflash` checks, and the only bytes that differ from stock
are inside the 512-byte bitmap.
