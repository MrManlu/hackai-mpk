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
| 24–47 | 3–5 | **8 RGB pad LEDs**, one triplet of outputs per pad | Strong hypothesis: at power-up every 3rd output (26, 29, …, 47) is fully on, so all pads show the same colour |
| 0–23, 48–55 | 0–2, 6 | Button LEDs | Hypothesis: at power-up 17 of them are at 4/32 (dim backlight) and output 21 is fully on |

To find out:

- [ ] Which channel of each triplet is red, green and blue. Knowing the colour
      of the pads at power-up identifies the channel at offset 2.
- [ ] Which pad each triplet belongs to (press pads in the simulator and watch).
- [ ] Which button each other output belongs to.
- [ ] Where the firmware computes the 224-byte buffer from the colours (the
      hook for MIDI feedback on the pads).

## In the simulator

`sim/peripherals/ShiftRegisterLeds.cs` shifts the SPI bytes, latches them on
PB4 and averages each output over virtual time:

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
