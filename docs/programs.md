# Program format

A program is **0x14B (331) bytes**. The current one lives in RAM at
`0x20000668`. Stored programs are 4 KB blocks: the factory programs at
`0x08037000` + n × `0x1000` (`MPC`, `AbletonLive`, `LogicProX`, `FLStudio20`,
`Garageband`, `Chromatic`, `MajorPads`, `MinorPads`, and a 9th block with an
empty name), and the user programs at `0x0802F000`, formatted at first boot.
The RAM after `0x20000668 + 0x14B` holds runtime state of the same module
(`+0x14C`, `+0x14D` + 0x18 × n, `+0x64D`, `+0x74D`…), not saved.

## Layout

| Offset | Size | Contents | Evidence |
|---|---|---|---|
| `0x00` | 16 | Program name, zero padded | factory programs |
| `0x10` | 1 | Pad MIDI channel (0–15) | Global menu `PadCH` |
| `0x11` | 1 | Pad aftertouch: Off / Chan / Poly | Global menu `PadAT` |
| `0x12` | 1 | Keyboard MIDI channel (0–15) | Global menu `MIDI` |
| `0x13` | 1 | Octave (4 = centre) | octave LEDs set from it at load |
| `0x14` | 1 | Transpose (12 = 0) | Global menu `Trans` |
| `0x15` | 1 | `Tprt`: Off / On | Global menu |
| `0x16`–`0x1B` | 6 | Arpeggiator (on/off, mode, division, latch, octaves…) | `arp_setup` and arp code |
| `0x1C` | 1 | Tap tempo taps (2–4) | Global menu `Taps` |
| `0x1D`–`0x1E` | 2 | BPM, 14 bits (`0x1D` << 7 \| `0x1E`; 120 = `00 78`) | program load (`FUN_0800a2d8`) |
| `0x1F`–`0x22` | 4 | More arp / timing settings (swing at `0x27`?) | arp code |
| `0x23`–`0x29` | 7 | Joystick setup | joystick menu (`FUN_08017a04`, `FUN_0801f158`) |
| `0x2A`–`0x30` | 7 | Scale / chord setup | `FUN_08016260`, `FUN_0801645c` |
| `0x31`–`0x36` | 6 | CV setup | CV menu (`FUN_0801878c`) |
| `0x37` | 2 × 8 × 7 | Pads, bank A then B, 7 bytes each (note, PC, CC, mode, …) | pad edit menu (`+0x37`–`+0x3D`) |
| `0xA7` | 8 × 20 | Knobs: CC, low, high, mode, name (16, e.g. `QLINK1`) | knob edit menu |
| `0x147` | 4 | Tail: `10 00 02 09` in every factory program | used by `FUN_08016c98`, `FUN_080170f0`… |

Rows marked with menu names are confirmed by the menu code; the grouping of
`0x16`–`0x36` comes from which functions touch the bytes, and the field-level
meaning is still to be checked.

## Free bytes?

**None.** Every offset from `0x10` to `0x36` is read or written by the code
(73 functions load the program base `0x20000668`), the pad and knob records
are fully used by their edit menus, and the tail is used too. The only slack
is at the end of the 16-byte names (factory names are at most 11 characters),
but the PC Program Editor can write full names, and it sends whole programs,
so it would overwrite any byte we borrowed.

So our own settings (MIDI THRU…) go in **our own settings sector**, see
[menus.md](menus.md#where-to-store-our-own-settings).
