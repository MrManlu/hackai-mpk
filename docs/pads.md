# Pads

The 8 pads (×2 banks) are pressure sensors read through the ADC multiplexers
([simulator.md](simulator.md#analog-inputs)). This page covers what a pad
sends and how hackai-mpk gives each pad its own MIDI channel.

## Pad settings (stock)

Each program has a 7-byte record per pad, bank A then B, at program offset
`0x37` + 7 × pad ([programs.md](programs.md)). The pad edit menu (SHIFT +
PROG SELECT, "Move a control to edit", then hit the pad; screen `0x19`) shows
them:

| Menu entry | Record byte | Values |
|---|---|---|
| 1. `Note#` | +0 | 0–127 |
| 2. `CC#` | +1 | 0–127 |
| 3. `PC#` | +2 | 0–127 |
| 4. `Off C` | +6 | colour at rest, 0–32 (palette index) |
| 5. `On C` | +5 | colour when hit, 0–32 |
| 6. `PMode` | +3 | Note / PC / CC |
| 7. `Toggl` | +4 | Off / On |

There is **no channel per pad**: every pad uses `PadCH` from the Global menu
(program byte `0x10`). Changing a colour updates the pad LED at once.

Like every program setting, these live in the program in RAM and are lost on
power-off unless the program is saved (HOME + SAVE).

## What happens on a hit

`pad_event_APP` (`0x08019A74`) handles hits, releases and pressure. On a hit,
at `0x08019F5C`, it copies `PadCH` into the pad's **state record** (RAM
`0x200045D8` + bank × `0x60` + pad × `0x0C`, byte 1). Every message of that hit
then uses the copy: note on and note off, PC, CC, poly and channel aftertouch.
So a note off always goes out on the channel of its note on, even if the
channel changes while the pad is held.

Note repeat (`pad_note_repeat_APP`, `0x0801A4C4`) does the same on every
retrigger (at `0x0801A564`).

The message functions queue USB-MIDI events (ring `0x200048B0`):
`midi_note_on_APP` (`0x080109DA`), `midi_note_off_APP` (`0x08010A0E`),
`midi_cc_APP`, `midi_program_change_APP`, `midi_poly_aftertouch_APP`,
`midi_channel_aftertouch_APP`, `midi_pitch_bend_APP`; see
[midi.md](midi.md) for where they go.

## Per-pad MIDI channel (hackai-mpk)

The pad edit menu gets an 8th entry, **`Chan`**: `Glob` (the program's
`PadCH`, as stock) or 1–16.

- `firmware/src/pad_menu.c`: the menu drawing reimplemented with entry 8, and
  the encoder **wrapped**: entry 8 is ours, entries 1–7 still go to the stock
  encoder (which also updates the LED colours).
- `firmware/src/pad_channel_hooks.S` + `pad_channel.c`: two **jump** hooks
  replace the two loads of `PadCH` (hit and note repeat) with the pad's own
  channel; the pad is found from the address of its state record.
- The channels are stored in our settings sector (`pad_channel[16]`), saved at
  once and **global**: the same for every program, unlike the stock pad
  settings.

Checked in the simulator (`sim/scripts/pad_check.py`, part of `make
mod-sim`): pad 1 starts on channel 10 (MPC program); the pad menu's stock
entries look exactly like the stock ones; with Chan 3, pad 1 sends note on and
note off on channel 3 while pad 2 stays on 10; with both held and released
in overlapping order (pad 1 down, pad 2 down, pad 1 up, pad 2 up), each note
off and each pad's poly aftertouch go out on that pad's channel; editing the
note through the wrapped stock encoder still works; the channel survives a
reset.

**Confirmed on a real unit (2026-10-21)**, over USB: with pad 1 on Chan 3 and
the others on Glob (channel 10), 40 s of playing with overlapping pads gave
364 messages: pad 1 always on channel 3, the others on 10, every note off on
the channel of its note on, no hanging notes, and each pad's aftertouch on its
channel. Read on the computer with `amidi -d` (raw MIDI, not the ALSA
sequencer), unbuffered (`stdbuf -oL`).
