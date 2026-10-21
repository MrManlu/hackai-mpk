# Patching: our own code in the stock firmware

hackai-mpk mods are C code compiled with `arm-none-eabi-gcc` and linked into
the free area of the stock image. Stock functions are replaced by ours through
**hooks**: the first instruction of the stock function becomes a jump to our
replacement, so every caller ends up in our code.

```bash
make mod        # → build/mods/hackai.bin (+ .elf, .map, .lst)
make mod-sim    # check it in the simulator
make flash IMAGE=build/mods/hackai.bin   # unit in update mode
```

To combine with the screensaver mod, build our code on top of that image:
`make screensaver PNG=…` then `make mod BASE=build/mods/screensaver.bin`.

## Layout

| Where | What |
|---|---|
| `0x08026000`–`0x0802D7FF` | Our code and constants (`firmware/link.ld`), ~30 KB |
| `0x0802D800`–`0x0802DFFF` | Our settings sector (2 KB), erased (`0xFF`) in the image |
| `0x20007F00`–`0x20007FFF` | Our RAM (256 bytes), not initialised |

The stock application ends at `0x08025D4C`; the app-present marker
(`0x0802E7FE`) is in the next sector and is never touched.

**Why that RAM is free:** the stock firmware's initial stack pointer is
`0x20005228` and the stack grows down from there. In the simulator, filling
`0x20004E00`–`0x20007FFF` with `0xA5` before boot and then using buttons,
menus, keys and the analogue controls left everything from `0x20005228` up
untouched (the deepest stack use reached `0x20005088`). Some app literals look
like addresses up there (`0x20006008`, `0x20007xxx`), but they are constants.

Nothing initialises our RAM (no `.data`/`.bss`: the link fails if there is
any). Variables are marked `HK_RAM` and checked with a magic value before use.

## Files

| File | Role |
|---|---|
| `firmware/include/stock.h` | Stock functions and variables we use (names from `config/symbols.csv`) |
| `firmware/include/hk.h` | Our common definitions (`HK_RAM`, settings API) |
| `firmware/src/*.c` | Our code |
| `firmware/link.ld` | Memory layout above |
| `firmware/hooks.toml` | Which stock functions are replaced by which of ours |
| `tools/build_mod.py` | Compiles, links, patches the hooks, runs the `mpkflash` checks |

`build_mod.py` generates `build/mods/stock.ld` from `config/symbols.csv`, so a
stock function is called by its analysis name, e.g. `print_LCD_APP(...)`.
Functions get the Thumb bit; the linker then emits plain `BL` calls (check
`hackai.lst`: a `BLX` to stock code would switch to ARM state and crash).
The stock code is built with IAR, which follows the AAPCS like GCC, so
arguments and return values match.

### Hooks

```toml
[[replace]]
function = "global_menu_draw_APP"     # stock, from config/symbols.csv
with = "hk_global_menu_draw"          # ours, from firmware/src
```

The first 4 bytes of the stock function become a Thumb-2 `B.W` to ours (range
±16 MB, plenty). The rest of the stock function stays in place, unreachable.
Our function must do the whole job of the stock one: we only replace
functions we fully understand, and check the result against the stock
firmware in the simulator.

## Settings (`firmware/src/settings.c`)

Our settings are a 32-byte record (`struct hk_settings`): magic `HKM1`, then
one byte per setting (`midi_thru` first), the rest reserved (0).

The settings sector is a log of records. Saving writes the next free record
(all `0xFF`), the magic word last; the sector is erased only when all 64
records are used. Loading takes the last record with the magic. A power cut
during a save leaves the previous record as the valid one. Programming flash
uses the stock routines (`flash_sector_erase_APP`, `flash_word_program_APP`).

A firmware update erases the sector (`C1` erases up to `0x0803EFFF`), so the
settings go back to their defaults after reflashing.

Why not inside the AKAI programs: there is no free byte, and the PC editor
writes whole programs ([programs.md](programs.md#free-bytes)).

## First mod: Global menu entry 7, THRU

`firmware/src/global_menu.c` replaces `global_menu_draw_APP` and
`global_menu_encoder_APP` ([menus.md](menus.md)) with C versions that have a
7th entry, ` THRU: Off/On`, stored in our settings. The setting does nothing
yet: the MIDI THRU itself is the next step.

`make mod-sim` (`sim/scripts/menu_check.py`) checks, in the simulator:

- the screens with the cursor on entries 1–5 are pixel-identical to the
  stock menu;
- entry 7 appears and can be switched on with the encoder;
- the record reaches the settings sector in flash (`48 4B 4D 31 01 …`);
- after a reset the menu still shows THRU on.
