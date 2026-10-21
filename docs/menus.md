# Menus

How the OLED menus work, with the **Global** menu (SHIFT + STOP) as the
worked example. Goal: add our own entries (MIDI THRU on/off first).

## Global menu (SHIFT + STOP)

Screen id `0x16`. Six entries, two shown at a time:

| # | Label | Program byte | Values (stored → shown) |
|---|---|---|---|
| 0 | `Trans:` | `+0x14` | 0–24 → −12…+12 (transpose) |
| 1 | ` MIDI:` | `+0x12` | 0–15 → channel 1–16 |
| 2 | `PadCH:` | `+0x10` | 0–15 → pad channel 1–16 |
| 3 | `PadAT:` | `+0x11` | 0–2 → Off / Chan / Poly (aftertouch) |
| 4 | ` Taps:` | `+0x1C` | 2–4 (tap tempo taps) |
| 5 | ` Tprt:` | `+0x15` | 0–1 → Off / On |

"Program byte" is an offset in the **current program** in RAM at
`0x20000668`. Despite the name, these settings are **per program**: the same
bytes are in every stored program, e.g. the factory programs at `0x08037000`
+ n × 4 KB (`MPC`, `AbletonLive`, `LogicProX`…), which start with the program
name (16 bytes).

### Code

| Address | Name | Role |
|---|---|---|
| `0x0801DF48` | `encoder_dispatch_APP` | Encoder handler: calls the screen's encoder function by screen id (`0x20004DA8`) |
| `0x0801F3A8` | `global_menu_encoder_APP` | Select mode: cursor 0–**5** (hard-coded). Edit mode: changes the entry's value within its limits. Then redraws |
| `0x080183F8` | `global_menu_draw_APP` | If-chain on the entry number: label at x = `0x13`, value at x = `0x4E`, row height from the font. When the cursor is on the last entry (**5**, hard-coded) it shows entries 4 and 5 |
| `0x08018C3C` | `pad_edit_menu_draw_APP` | Same pattern for the pad edit menu (screen `0x19`, 7 entries) |

State shared by all menus:

| RAM | Meaning |
|---|---|
| `0x20004DA8` | Current screen id (`0x16` Global, `0x19` pad edit…) |
| `0x20004DAE` | Edit mode: 0 = choosing an entry (label highlighted), 1 = editing its value (value highlighted) |
| `0x20004DAF` | Cursor (entry number) |
| `0x20000668` | Current program (0x14B bytes) |

Highlighting is the last argument of `print_LCD_APP` (`invert = 1`).

### What adding an entry takes

There is no menu table: the entries are hard-coded in three places, so a new
entry needs code patches:

1. `global_menu_encoder_APP`: raise the cursor limit (`5` → `6`) and handle
   the value of entry 6 in edit mode.
2. `global_menu_draw_APP`: raise the "last entry" constant (`5` → `6`) and
   draw label and value of entry 6.
3. Storage for the value (see below).

## Where to store our own settings

Two options:

- **In the program**: ruled out, there are no unused bytes
  ([programs.md](programs.md#free-bytes)).
- **Our own settings sector** in the free area (e.g. the last 2 KB sector,
  `0x0802D800`–`0x0802DFFF`), with our own format and version: global for real,
  independent of AKAI's formats. Erased by a firmware update (`C1` erases up to
  `0x0803EFFF`), so settings fall back to defaults after reflashing.
