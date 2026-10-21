# LEDs

All the LEDs, the RGB pads and (probably) the button LEDs, hang off a
**chain of 7 shift registers** (74HC595 or similar, 56 outputs) on SPI1. The
firmware does **software PWM**. Found with the simulator's SPI recorder and
Ghidra, matching what was seen on the board.

## Hardware

| Signal | Pin | Evidence |
|---|---|---|
| Serial data / clock | SPI1, master, MSB first, TX only | `FUN_0801b514` (init) |
| Latch (RCLK) | **PB4**, rising edge | Low before each transfer, high after it (`FUN_08010084`) |
| Output enable (/OE) | **PB9**, held low | Reset once at init (hypothesis) |
| DMA | DMA1 channel 3, 7 bytes per transfer | `FUN_08010084` |

SPI1 is remapped to port B by IOMUX (STM32F1 remap: SCK PB3, MOSI PB5,
to be checked on the board). Outputs are **active low**: a 0 bit lights the
LED.

## Software PWM

- Frame buffer: **32 phases × 7 bytes = 224 bytes** at `0x200041D0`.
- Every 200 µs (**5 kHz**, driven from the `TMR3_IRQHandler` path) the state
  machine in `FUN_08010084` sends the 7 bytes of the next phase and latches
  them: phase = (phase + 1) & 31 (counter at `0x20004DEA`, state at
  `0x20004DE9`).
- So each output has **32 brightness levels**, refreshed at about 156 Hz.
  An output lit in *n* of the 32 phases has a brightness of *n*/32.

## Output map

Output *k* is bit (7 − *k* mod 8) of byte *k*/8, bytes counted in the order
they are sent.

| Outputs | Bytes | Function | Status |
|---|---|---|---|
| 24–47 | 3–5 | **8 RGB pad LEDs**: pad n = outputs 24 + 3(8 − n) + {0 blue, 1 green, 2 red} | Confirmed (see below) |
| 0–23, 48–55 | 0–2, 6 | Button LEDs | At power-up 17 of them are at 4/32 (dim backlight) and output 21 (BANK A) is fully on. Map in [simulator.md](simulator.md#key-matrix-and-power-up-key-combinations) |

Program colours seen in the simulator (pad LEDs at rest, blue/green/red %):

| Program | Name | Pads |
|---|---|---|
| 1 | MPC | 0 / 0 / 100 (red) |
| 2–3 | | 0 / 47 / 47 |
| 4 | FL Studio | 0 / 100 / 0 (green) |
| 5 | GarageBand | 12 / 62 / 16 (green) |
| 6 | | 16 / 59 / 0 |
| 7 | | 22 / 28 / 0 |
| 8 | | 0 / 0 / 100 (red) |

Confirmed colours:

| Outputs | LED | Evidence |
|---|---|---|
| 45–47 | PAD 1 (the triplet lit in PROG SELECT mode); outputs 47 lit = red at power-up | Real unit: PAD 1 lights; red pads at power-up |
| Pads: offset 2 / 1 / 0 | **Red / green / blue** | Real unit: red at rest and blue when hit with program 1 (MPC), green with program 5 (GarageBand) |
| 21 / 22 | BANK A/B button, **red / green** | Real unit: the button turns from red (bank A) to green (bank B). Simulator: pressing it swaps output 21 for 22 and back |

To find out:

- [x] Which channel of each triplet is red, green and blue: **offset 0 =
      blue, 1 = green, 2 = red**. Red from the power-up colour (program 1,
      "MPC"), green from program 5 ("GarageBand", green pads on the real
      unit, channel 1 dominant in the simulator), blue from the hit colour of
      program 1 (pads turn blue when hit on the real unit, channel 0 in the
      simulator). All three confirmed.
- [x] Which pad each triplet belongs to: **pad n = triplet 8 − n** (PAD 1 =
      outputs 45–47). PAD 1 seen on the real unit; all 8 confirmed in the
      simulator by the firmware's own "PAD-n" screen when each pad is hit.
- [x] Which button each other output belongs to: first pass done with
      `make matrix-sweep` (transport LEDs among 2–6 still to assign).
- [ ] Where the firmware computes the 224-byte buffer from the colours (the
      hook for MIDI feedback on the pads).

## Pad colours (stock)

Pads have two colours each, rest and lit, chosen per pad in the pad edit menu
(`Off C`, `On C`, [pads.md](pads.md)) as indexes into a 33-colour palette at
`0x08024CE0` (`0x00RRGGBB` words):

| Index | Colour | Index | Colour |
|---|---|---|---|
| 0 | off | 17 | cyan |
| 1 | red (MPC pads at rest) | 19 | blue (MPC pads when hit) |
| 6 | yellow | 25 | magenta |
| 10 | green (Garageband pads) | 32 | white |

The 8 physical pads show the current bank (`0x20004DFE`). Functions:

| Address | Name | Role |
|---|---|---|
| `0x0801035A` | `pad_led_colour_APP` | Sets a physical pad's rest or lit colour (RGB) in its LED record (`0x200001B8` + pad × `0x20`) |
| `0x08010384` | `pad_led_show_APP` | Shows a physical pad in its rest or lit colour (writes the PWM buffer) |
| `0x0801A64C` | `bank_toggle_APP` | BANK A/B: reloads the 8 pads' colours and states from the new bank |
| `0x08010120` | `led_set_level_APP` | Any single LED (e.g. transport) to a level 0–32 |

Stock "feedback": notes `0x73`–`0x77` sent to the unit on its MIDI channel
light the transport LEDs ([midi.md](midi.md)). Nothing lights the pads.

## Pad LED feedback (hackai-mpk)

`firmware/src/pad_feedback.c`: a **note on with a pad's own note and
channel** (`Note#`, and `Chan` or `PadCH`) lights that pad in its `On C`
colour; a note off (or velocity 0) gives it back to the stock code (`Off C`,
or lit while held). While a pad is lit by MIDI, hitting it does not change its
LED: the sender is in charge. Pads in PC or CC mode are not affected.

- Messages from the computer (USB, port 1) and from DIN IN: a sequencer
  sending its trigs as notes lights the pads in time.
- Both banks: a pad of the other bank shows its state when the bank changes.
- Not applied while the pads are in a special mode (`0x20004DCE`, e.g. the
  sequencer), which draws its own colours.

Hooks: wrap of `midi_message_handle_APP` (messages to the unit) and of
`pad_led_show_APP` (forces "lit" for pads lit by MIDI, whoever redraws them);
the DIN IN task calls the feedback directly when USB is connected, since DIN
IN then goes to the computer instead of the message handler.

Checked in the simulator (`sim/scripts/feedback_check.py`, part of `make
mod-sim`): the stock firmware ignores the notes; note on 36 / channel 10
lights pad 1 blue and another channel does nothing; hitting the lit pad keeps
it blue; note off brings back red; a note for B1 leaves bank A alone and shows
after BANK A/B; unlit pads still light when hit.

**Confirmed on a real unit (2026-10-21)**, with notes sent from the computer
over USB (`amidi -S`, raw MIDI): `99 24 7F` turned pad 1 blue, hitting it kept
it blue, `89 24 00` brought it back to red; `99 2C 7F` (B1) left bank A red
and showed B1 blue after BANK A/B.

## In the simulator

`sim/peripherals/ShiftRegisterLeds.cs` shifts the SPI bytes, latches them on
PB4 and averages each output over virtual time:

The model averages over whole PWM cycles (64 latches = 2 cycles of 32
phases). An earlier version used a fixed 20 ms window, not a multiple of the
6.4 ms cycle, and steady LEDs seemed to flicker between 12 and 16 %.

```
(mpk) spi1.leds Show          # text bars per byte
(mpk) spi1.leds Brightness    # 56 values, 0-100 %
```

`sim/peripherals/SpiRecorder.cs` records raw bursts on any SPI bus
(`Bursts`, `Summary`), which is how this was found.

Note: SPI DMA request lines are left unconnected in `sim/at32f415.repl`.
Renode's DMA copies memory-to-peripheral blocks as soon as the channel is
enabled, and the SPI's per-byte requests re-entered that copy and duplicated
bytes. This also fixed the doubled first column on the OLED.
