# Subsystems

First map of the application's subsystems, built from the peripheral usage
report (`make report`, output in `build/reports/peripherals.md`).

Everything here is a **hypothesis** until checked in Ghidra and, where
possible, on the hardware. When you confirm one, name the functions in Ghidra,
`make export`, and move the facts to the right document.

DMA channel roles assume the default STM32F1-style request mapping (ADC1 →
channel 1, SPI1_TX → 3, USART1_TX → 4, SPI2_TX → 5). The AT32F415 also has a
flexible DMA mapping mode. Check whether the firmware enables it before relying
on this table.

## MIDI DIN (USART1)

| Address | Uses | Guess |
|---|---|---|
| `0x0801B636` | USART1 (`DT`, `STS`), DMA1 ch4, GPIOB, IOMUX (transitive) | USART1 init: pins remapped to port B, TX by DMA |
| `0x0801238A` | DMA1 ch4 (`CTRL`, `MADDR`) | Start a DMA transmission: **MIDI OUT** |
| `0x0801B740` | `USART1_IRQHandler` | Byte received: **MIDI IN** |
| `0x08020C38` | USART1 base | Helper (flag check or send) |

MIDI THRU will most likely hook the receive interrupt and queue the received
bytes for the DMA transmit path.

## LEDs (SPI1 + DMA): confirmed, see [leds.md](leds.md)

| Address | Uses | Guess |
|---|---|---|
| `0x0801B514` | SPI1 (`DT`), DMA1 ch3, GPIOB, IOMUX (transitive) | SPI1 init, TX by DMA |
| `0x08010084` | SPI1 base, DMA1 ch3 (`CTRL`, `MADDR`), GPIOB | Start a DMA transfer of a buffer |

SPI used only for transmitting, through DMA, is a common way to drive chained
RGB LEDs (WS2812-style protocols encoded on MOSI) or shift registers. The
display uses SPI2, so SPI1 is the best candidate for the pads' RGB LEDs. The
transmitted buffer (`C3MADDR`) would then be the LED colour buffer, the key
to MIDI feedback.

## Analogue inputs (ADC1 + DMA)

| Address | Uses | Guess |
|---|---|---|
| `0x0801ADFE` | ADC1 (`ODT`), DMA1 ch1, GPIOA, GPIOB | ADC init: analogue pins and DMA of the results |
| `0x0801B080` | ADC1, DMA1 ch1 (`CTRL`, `MADDR`) | Start a conversion scan into a RAM buffer |

Probably the knobs and the pitch and modulation wheels (`VR` calibration screens),
maybe also the pads' pressure. For the battery mod: find a free ADC channel and
add it to this scan.

## Periodic scan (TMR3)

| Address | Uses | Guess |
|---|---|---|
| `0x0801AC68` | TMR3, GPIOC | Timer init |
| `0x0801AD1A` | `TMR3_IRQHandler` | Periodic task: key/pad matrix scan, or the arpeggiator/sequencer clock |

## Display (SPI2 + DMA)

| Address | Uses | Guess |
|---|---|---|
| `0x0801F534` | `spi_transmit_AKAI` | Polled byte transmit (commands) |
| `0x0801AB5E` | SPI2 (`DT`), DMA1 ch5 | SPI2 init |
| `0x0801F6F4` | DMA1 ch5 (`CTRL`, `MADDR`) | Framebuffer flush |

See [display.md](display.md).

## USB (OTG FS)

Only one function per image loads the OTG base addresses. The USB stack
probably keeps a pointer to them in a structure, so the report cannot follow
it further. Start from `IRQ67_IRQHandler` (`0x08024588`).
