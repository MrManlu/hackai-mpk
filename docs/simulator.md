# Simulator

The stock firmware runs unmodified in [Renode](https://renode.io), on a
simulated MPK Mini Plus.

```bash
make setup-gui            # once: PySide6 in .venv
make gui                  # the MPK Mini Plus panel: OLED, LEDs, buttons, RE panels
make sim                  # Renode GUI, the OLED in its own window
make sim-debug            # same, with every warning (to find missing models)
make sim-dump SIM_TIME=2  # headless: run 2 virtual seconds, print the OLED as text
```

Renode is expected in `/opt/renode_1.17.0-portable/` (the portable Linux
release, which bundles its own .NET). Use `RENODE=/path/to/renode` otherwise.

## Status

| What | Status |
|---|---|
| Bootloader boots, sets the PLL to 120 MHz, starts SysTick | ✅ |
| Bootloader draws its "Upgrade / v01.13" screen | ✅ |
| Bootloader jumps to the application | ✅ |
| Application boots to its main screen ("PGM1: MPC / BPM: 120") | ✅ |
| LEDs (shift-register chain on SPI1, PWM brightness) | ✅ see [leds.md](leds.md) |
| Key matrix (decoder on PC0–PC3, columns PC8–PC13) | ✅ model; 18 buttons mapped (rows 10–12) |
| Panel GUI (PySide6) | ✅ OLED, pad and LED outputs, matrix explorer |
| Analog inputs: ADC1 + multiplexers (pads, knobs, wheels, joystick) | ✅ see [Analog inputs](#analog-inputs) |
| Encoder (turn on PC4/PC5, push in the key matrix) | ✅ |
| Keybed (37 keys, velocity from two contacts) | ✅ see [Keybed](#keybed) |
| MIDI OUT (DIN) monitor | ✅ `midiOut Messages`, GUI panel |
| MIDI IN (DIN): `usart1 WriteChar` into the firmware's receive buffer | ✅ |
| MIDI bridge to JACK/PipeWire (`make gui JACK=1`) | ✅ |
| USB MIDI | ⚪ not yet |

## Files

| File | Contents |
|---|---|
| `sim/at32f415.repl` | The MCU: memory, NVIC, GPIO, DMA, USART, SPI, I2C, timers. Adapted from Renode's STM32F103 platform |
| `sim/mpk_mini_plus.repl` | The board: the MCU plus what is wired to it (OLED on SPI2, D/C on PB14) |
| `sim/mpk.resc` | Startup script: loads the C# models, the platform, the SVD and `baserom/firmware.bin` |
| `sim/quiet.resc` | Silences known, harmless warnings for `make sim` |
| `sim/peripherals/AT32_CRM.cs` | Clock controller: clocks report ready at once, SysTick follows the configured clock |
| `sim/peripherals/AT32_OTGFS.cs` | USB OTG stub: the USB initialisation finishes as if no host were connected |
| `sim/peripherals/ShiftRegisterLeds.cs` | LED chain: 7 shift registers on SPI1, latch on PB4, average brightness per output |
| `sim/peripherals/SpiRecorder.cs` | Records raw SPI bursts with timestamps, for reverse engineering a bus |
| `sim/peripherals/AT32_ADC.cs` | ADC1 with external 8:1 multiplexers (select PB0–PB2): scan, continuous, DMA; `adc1 SetInput ch mux value` |
| `sim/scripts/analog_sweep.py` | `make analog-sweep`: drives every analog input and reports what changes |
| `sim/peripherals/KeyMatrix.cs` | Key matrix behind a row decoder (PC0–PC3 select row 0–12, PC8–PC15 read columns); `keys Press r c` / `keys Release r c` |
| `sim/peripherals/MidiMonitor.cs` | Decodes the MIDI bytes USART1 transmits (DIN OUT): `midiOut Messages 20` |
| `sim/peripherals/RotaryEncoder.cs` | Detented quadrature encoder on PC4/PC5; `encoder Turn n` |
| `sim/scripts/matrix_sweep.py` | `make matrix-sweep`: presses every position on a fresh boot and reports what changes (`build/reports/matrix_sweep.md`) |
| `sim/gui/mpk_panel.py` | The panel GUI: starts Renode with its monitor on TCP and polls the OLED and LEDs |
| `sim/gui/mpk_mini_plus.svg` | The panel drawing. Every control has an `id`; editable in Inkscape |
| `sim/gui/mpk_mini_plus.toml` | Connects SVG ids to the simulator: pad LED channels, button LEDs and matrix positions |
| `sim/peripherals/SSD1306.cs` | The OLED controller, drawn scaled up with a pixel grid. `spi2.oled AsciiArt` dumps it as text, `spi2.oled Statistics` shows counters and state |

The C# models are compiled by Renode when the script loads them, so there is
nothing to build.

## How it works

The AT32F415 copies the STM32F1 register layout for most peripherals, so
Renode's STM32 models work as they are: `STM32F1GPIOPort`, `STM32_UART`,
`STM32SPI` (series F1), `STM32_Timer` and `STM32G0DMA` (same per-channel
layout as the F1 DMA). Interrupt numbers come from the AT32F415 SVD.

What is AT32-specific gets its own model in `sim/peripherals/`. Everything
without a model is still readable and writable: `ApplySVD` makes Renode log
each access with the register name, which is how missing models are found.

### Clocks

The bootloader switches to the PLL with `CRM_CFG = 0x20340000`: PLL source
HICK / 2 = 4 MHz, multiplier 30, **120 MHz**. This matches the SysTick reload
values it uses (`LOAD = 159` at 8 MHz and `LOAD = 2399` at 120 MHz, both
**20 µs per tick**). `AT32_CRM` computes the clock from `CFG` and gives it to
the NVIC.

## The workflow: run, find the blocker, model it

1. `make sim-debug` (or `make sim-dump`) and look at the log for the place where the firmware is
   stuck (`cpu PC`) and at the warnings about unimplemented registers.
2. Find that address in Ghidra: it is usually a loop waiting for a flag.
3. Model the minimum that releases it (in the `.repl`, or in a C# model).
4. Repeat.

Blockers found so far:

| Blocker | Fix |
|---|---|
| Loop on `CRM_CFG.SCLKSTS` after selecting the PLL | `AT32_CRM`: status follows the selection |
| SysTick ran 15× too slow (fixed 8 MHz) | `AT32_CRM` updates the NVIC frequency |
| Renode rejects Artery's SVD (`read-write ` with a trailing space) | `make` writes a cleaned copy for Renode |
| Bootloader stays in update mode: unpressed keys read 0 | `KeyMatrix` model: columns read high when no key is pressed |
| Application waits for the USB core reset (`GRSTCTL.AHBIDL`, `CSFTRST`) | `AT32_OTGFS` stub |
| Application enters the factory test mode (version screen) | Same as above: keys released |
| After `machine Reset` the bootloader always entered update mode | `KeyMatrix` re-drives its columns on every change (the GPIO port forgets them on reset) |
| OLED picture scrolls after pressing a key | Model the OLED chip select (PB12): the 3 bytes sent on each key event belong to another SPI2 device (CV DAC?) |

### Key matrix and power-up key combinations

The keys are read through a **row decoder**: the firmware writes a row
number (0–12) on PC0–PC3, a decoder (74HC154-style) pulls that row low, and
PC8–PC15 read 8 active-low columns. In normal operation (`FUN_0800a4c8`) it
counts 0, 1, …, 12 over and over, compares each row with its previous reading
and queues every change with a 64-bit timestamp (32-entry queue): the
timestamps are what velocity needs. That gives **13 × 8 = 104 positions**:

| Rows | What | Evidence |
|---|---|---|
| 0–9 | The keybed: two contacts per key, see [Keybed](#keybed) | `FUN_0800a562` |
| 10–12, columns 0–5 | The 18 buttons | LEDs and screens change; see the map below |
| 11, column 6 (PC14) | Encoder push ("Enter") | Loads the program in the "Load Program" screen |

Button map, also in `sim/gui/mpk_mini_plus.toml` (C = confirmed by the screen
or an unambiguous behaviour, O = follows the panel order):

| Row | Col 0 (PC8) | Col 1 (PC9) | Col 2 (PC10) | Col 3 (PC11) | Col 4 (PC12) | Col 5 (PC13) |
|---|---|---|---|---|---|---|
| 10 | ARP (C), LED 54 | TAP TEMPO (O), LED 53? | NOTE REPEAT (C), LED 52 | FULL LEVEL (O), LED 50 | OCT − (O), LED 49 | OCT + (O), LED 48 |
| 11 | BANK A/B (C), LED red 21 / green 22 | SCALES (O), LED 19 | CHORDS (O), LED 17 | SHIFT (C), LED 14 | HOME/SAVE (O), LED 12? | PROG SELECT (C), LED 10 |
| 12 | ⏪ (O) | ⏩ (O) | STOP (O) | PLAY (O) | REC (O) | SEQ (O), LED 1 |

The transport LEDs are among outputs 2–6, not yet assigned. BANK A/B is a
two-colour LED: output 21 is red (bank A), 22 green (bank B), confirmed on the
real unit.

**Hold-to-edit buttons.** ARP and PROG SELECT (and probably others) show a
settings screen while held: turn the encoder to change values, and the
release does the button's own action (ARP toggles the arpeggiator). In the
GUI, hold them with a right click.

**PROG SELECT has two modes.** While held: "Load Program / Press pad to
Load Program" (hold + pad, as in the user guide). Once released: "Load
Program / PGM1: MPC / Enter to Load", browsing programs with the encoder and
loading with its push (LED 10 stays on). In the GUI, latch PROG SELECT with a
right click to use the pad mode. Neither the pads nor the encoder are
modelled yet.

Power-up combinations (both keys held while the firmware checks):

| Who | Row | Columns | Buttons (from the map) | Effect |
|---|---|---|---|---|
| Bootloader | 11 (`GPIOC = 0xB`) | PC11 + PC13 | SHIFT + PROG SELECT | USB **update mode** ("Upgrade" screen) |
| Application (`main`) | 10 (`GPIOC = 0xA`) | PC8 + PC12 | ARP + OCT − | **Factory test mode**: version screen "Ver:Y01-13", own main loop (`FUN_08012d6a`) |
| Application (`main`) | 10 | PC9 + PC13 | TAP TEMPO + OCT + | Calls `FUN_0801fe1a`, unknown (factory reset?) |

These button names come from the map above, so they are as good as its
"O" entries. Check them on the real unit before relying on them.

## Open questions

- [x] Why the bootloader stayed in update mode: keys read as pressed (see
      above).
- [ ] FLASH controller and system memory: the application unlocks the flash
      at boot and reads `0x1FFFF7E0` (flash size) thousands of times and
      `0x1FFFF806`. Not blocking, but saving presets needs a real model.
- [x] Map buttons to matrix positions and LED outputs (first pass, see
      above; "O" entries and the transport LEDs still to confirm).
- [ ] Rows 0-9: the keybed? Find how velocity is measured.
- [ ] MIDI OUT: the firmware sends USART1 data by DMA (`DMAT`), which
      Renode's `STM32_UART` does not support. Needs a small UART model or an
      extension before MIDI can be bridged to ALSA.
- [ ] IOMUX: the AT32 has extra remap registers at offsets `0x28` and `0x2C`
      that the STM32F1 AFIO model does not know.
- [x] The doubled first column on the OLED: SPI DMA requests re-entered
      Renode's DMA copy and duplicated bytes. Request lines are now left
      unconnected (see [leds.md](leds.md)).
- [ ] `0x40007050` (in PWC, not in the SVD) is written at boot.
- [ ] Timers and peripheral clocks are fixed at 8 MHz in the `.repl`. The
      application's TMR3 will need the right frequency.

## The panel GUI

`make gui` starts Renode headless with its monitor on a TCP port, runs
`sim/mpk.resc` and talks to the monitor: about 20 times a second it reads
`spi2.oled Framebuffer` and `spi1.leds Brightness`, and it sends
`keys Press/Release` when you click.

- **Panel**: OLED, pad colours (from the LED outputs and the channel order in
  the TOML), button LEDs and clickable buttons once their LED output and
  matrix position are known.
- **LED outputs**: the 56 outputs of the chain with their brightness.
- **Key matrix**: hold any row/column position to press it.
- **Left click** on a button is momentary; **right click latches** it (yellow
  outline) until the next right click. A latched **SHIFT** is sticky: it
  releases itself after the next button you press (`modifier = true` in the
  TOML). Other latched buttons stay held, so latching two and pressing Reset
  triggers the power-up combinations. Double-clicking SHIFT also works: that is the firmware's own
  Shift Lock.
- `--screenshot file.png --seconds 30` saves a capture and quits (tests).

Use **PySide6 6.11.2** (`sim/gui/requirements.txt`). 6.12.0 with Python 3.11
leaks references to `None` on every call that returns nothing and aborts
after a few thousand calls (`Fatal Python error: none_dealloc`).

## Analog inputs

ADC1 converts **channels 0–4 (PA0–PA4)** in a continuous scan, by DMA (DMA1
channel 1, 16-bit, double buffer at `0x20004B24`). In front of the inputs,
analog multiplexers share the select lines **PB0–PB2**. The scan routine
(`FUN_0801b080`, called from the TMR3 interrupt path) steps the select lines
0–7, filters each reading and stores it in a table of 32 entries of 8 bytes at
`0x200040D0` (value, filtered value, calibration minimum, maximum).

The firmware names each control on the OLED when it moves, which gave this
map (`make analog-sweep`):

| Channel | Multiplexer | Controls |
|---|---|---|
| 0 | dual 4:1 (S0–S1 only) | PAD 4, 2, 3, 1 at positions 0–3 (and again at 4–7) |
| 1 | dual 4:1 (S0–S1 only) | PAD 5, 8, 7, 6 at positions 0–3 (and again at 4–7) |
| 2 | 8:1, auto-calibrated and scaled to 0–4095 | 0 = modulation wheel ("Modulation"), 1 = pitch wheel ("PITCH"), 2–3 = joystick ("JOYSTICK"), 4–7 unused |
| 3 | 8:1 | Knobs 1–8, second wiper |
| 4 | 8:1 | Knobs 1–8, first wiper ("QLINK n") |

- **Pads**: pressure sensors. A press shows "PAD-n / NOTE#… / CH10" and the
  velocity; the pad LED switches from triplet channel 2 (red, rest) to
  channel 0 (hit colour, still to confirm on the real unit).
- **Knobs** are endless: two wipers with triangle waves 90° apart. Turning
  clockwise (value up) means the second wiper lags the first by 90°.
- **Wheels and joystick** use calibration limits stored in flash (pitch and
  mod 100–3095, joystick 110–3583). `mpk.resc` puts the pitch wheel and the
  joystick at the centre of their range at startup.

In the GUI: click a pad (right click to hold), turn a knob with the mouse
wheel or by dragging, drag the wheels and the joystick (pitch and joystick
spring back).

## Encoder

Quadrature on **PC4 (A) and PC5 (B)**, polled by `FUN_0801df48`: state =
PC5:PC4, both high at rest. A detent goes 3 → 1 → 0 → 2 → 3 (+1) or
3 → 2 → 0 → 1 → 3 (−1), counted when the state returns to 3 after at least
three changes. Every 10 ms (500 ticks) the accumulated steps go to the
handler of the active screen (13 menus). The push is in the key matrix at
row 11, column 6 (PC14).

`RotaryEncoder.cs` plays one state per millisecond of virtual time. In the
GUI: mouse wheel or vertical drag to turn, click to push.

Related finding: **PA6** is polled by `FUN_0800fe3c`, which measures the
time between edges to derive a tempo: almost certainly the **CLOCK IN**
jack (sync input).

## Keybed

Rows 0–9 of the key matrix, in pairs (`FUN_0800a562`): key *k* (0–36) is
column *k* mod 8 of row 2·(*k* div 8) (**first, upper contact**) and of row
2·(*k* div 8) + 1 (**second contact**). Key 0 is note 48 (C3), key 36 note 84
(C6) at the default octave.

- First contact closes: the event's timestamp is stored.
- Second contact closes: **Δt = t₂ − t₁** (ticks of 20 µs) gives the velocity
  through a piecewise-linear curve, and the Note On is sent.
- First contact opens: Note Off.

Default curve (thresholds at `0x20000420`, values at `0x20000428`, velocity =
128 − value):

| Δt | Velocity |
|---|---|
| ≤ 2.8 ms (140 ticks) | 127 |
| 2.8 → 8 ms | 127 → 96 |
| 8 → 20 ms | 96 → 64 |
| 20 → 96 ms | 64 → 8 |
| > 96 ms | 8 |

Black keys (mask `0x54A` over the 12 notes: C#, D#, F#, G#, A#) use the
thresholds scaled to 90 % (`0x20000658` = 9 tenths): shorter travel.

Checked in the simulator (`keys KeyDown k travel_us`): 2 ms → 127, 5 ms → 115,
15 ms → 78, 60 ms → 35, 150 ms → 8; a black key at 5 ms → 112.

In the GUI: click a key (lower on the key = faster = louder), right click to
hold, or use the computer keyboard (A W S E D F T G Y H U J K O L from C3).
The **MIDI OUT (DIN)** panel shows what the firmware sends.

Note: at boot the analog controls go from 0 to their rest value, which the
firmware sees as a move; it shows "JOYSTICK" for about a second before the
main screen.

## MIDI

- **DIN OUT**: USART1, sent by DMA. `MidiMonitor.cs` decodes it
  (`midiOut Messages 20`); the GUI shows it in the "MIDI OUT (DIN)" panel.
- **DIN IN**: bytes injected with `usart1 WriteChar 0x90` reach the firmware
  like bytes from the socket: `USART1_IRQHandler` stores them in a 128-byte
  ring buffer at `0x20004730` (write index at `0x20004D74`). MIDI THRU will
  hook here.
- **JACK bridge** (`make gui JACK=1`, needs `pipewire-jack` for `pw-jack` and
  `JACK-Client` from `make setup-gui`): the GUI registers a JACK client
  "MPK Mini Plus sim" with two MIDI ports, `din_out` (what the firmware sends)
  and `din_in` (into the firmware). Connect them with qpwgraph, a DAW, or
  `jack_connect`. Latency is that of the GUI polling (tens of ms) plus the
  simulator running slower than real time: fine for development, not for
  playing.

Why not the ALSA sequencer: an earlier bridge used python-rtmidi virtual ALSA
ports. On Debian's 6.1 kernel, freeing those sequencer clients at process exit
deadlocked `snd-seq` in the kernel (processes stuck in `seq_free_client`,
then PipeWire too), and only a reboot fixed it. JACK through PipeWire never
creates kernel sequencer clients. (python-rtmidi was also unusable for JACK:
its wheel bundles its own libjack, so `pw-jack` cannot redirect it.)
