# MIDI routing

How the stock firmware moves MIDI between the controls, USB and the DIN
sockets, and what our MIDI THRU adds.

## Stock routing

| From | USB connected to a computer | No computer (e.g. USB power bank) |
|---|---|---|
| Keys, pads, knobs… | → USB (port 1) | → **DIN OUT** |
| DIN IN | → USB (port "MIDI 2"), i.e. the computer receives it | → handled locally (CV output, transport LEDs). **Never to DIN OUT** |
| Computer, port "MIDI 2" | → DIN OUT | — |
| Computer, port 1 | → handled locally (CV, LEDs, SysEx) | — |

So with a computer the unit is also a **USB ↔ DIN MIDI interface**, and
without one it is a standalone controller whose DIN IN goes nowhere (confirmed
by the behaviour of the real unit: no USB-DIN bridge on a power bank). That
gap is what MIDI THRU fills.

## Code

All four tasks run from the main loop, in this order (`midi_service_APP`,
`0x08010BA8`), so they never interrupt each other; only USART1's receive
interrupt runs concurrently.

| Address | Name | Role |
|---|---|---|
| `0x08010D76` | `usb_midi_out_receive_APP` | Packets from the computer: cable 1 → DIN OUT, cable 0 → `midi_message_handle_APP` or SysEx |
| `0x08010C2A` | `usb_midi_in_send_APP` | Sends the USB-MIDI event ring to the computer (endpoint `0x83`); when the send fails because USB is not configured, copies each event to DIN OUT instead |
| `0x0801238A` | `din_tx_flush_APP` | Moves up to 64 queued bytes to DMA (DMA1 ch 4 → USART1) |
| `0x0801240E` | `din_in_poll_APP` | DIN IN bytes → parser → USB ring (USB configured) or `midi_message_handle_APP` |

Helpers:

| Address | Name | Role |
|---|---|---|
| `0x0801B740` | `USART1_IRQHandler` | Received byte → DIN IN ring (128 bytes at `0x20004730`, write `0x20004D74`) |
| `0x0801B76C` / `0x0801B78E` | `din_rx_count_APP` / `din_rx_read_APP` | Bytes waiting / take one (read index `0x20004D76`) |
| `0x0801249C` | `midi_parser_feed_APP` | Byte stream → USB-MIDI packet (state `0x20004C78`): running status, SysEx in 3-byte chunks, real-time bytes at once; returns 1 when a packet is complete |
| `0x08012698` | `usb_midi_packet_APP` | Packs `CIN | 0x10` (cable 1), then 3 MIDI bytes |
| `0x0801235E` | `din_tx_queue_APP` | Queues n bytes for DIN OUT (64-byte ring `0x200049F4`, write `0x20004DFA`, read `0x20004DFB`). **No overflow check** |
| `0x08011F84` | `midi_message_handle_APP` | A received message: notes on the CV channel drive the CV output; notes `0x73`–`0x77` on the MIDI channel light the transport LEDs (stock "LED feedback") |
| `0x0801C3F0` | `usb_ep_send_APP` | Starts a USB IN transfer if configured (state 3 at `0x200011B8 + 0x112`): returns 0, else 1 |

The USB-MIDI event ring (keyboard and DIN IN events for the computer) is at
`0x200048B0`, 128 bytes of 4-byte packets, write index `0x20004D86`, read
`0x20004D88`.

## MIDI THRU (hackai-mpk)

`firmware/src/midi_thru.c` replaces `din_in_poll_APP` with the same logic
plus, when THRU is on (Global menu, entry 7), a copy of each **complete
message** to DIN OUT:

- Message bytes per packet come from the CIN, with the same table the stock
  code uses to copy events to DIN OUT.
- Whole messages only, never single bytes, so a THRU message never lands
  inside a message of the keyboard (both are queued from the main loop).
- Before queuing, we check the free space in the 64-byte DIN OUT ring (the
  stock queue function does not) and drop the message if it does not fit;
  drops are counted in our RAM.
- Running status in DIN IN comes out with explicit status bytes (the parser
  rebuilds full messages).

With a computer connected, DIN IN still goes to the computer as before, and
also to DIN OUT.

Known limit: SysEx is forwarded in 3-byte chunks as the parser produces them,
so a keyboard message can land between two chunks of a long SysEx. Real-time
messages (clock) are allowed inside SysEx by the MIDI spec; other messages are
not. Fine for clock, notes and CCs; to revisit if long SysEx through the unit
matters.

### Checked in the simulator

`sim/scripts/thru_check.py` (part of `make mod-sim`): the stock firmware never
forwards DIN IN; with THRU off neither do we; with THRU on, notes (with
running status), clock, CC, program change and SysEx come out in order; 40 CCs
arriving while a key is played all come out whole, and so does the key; THRU
is still on after a reset. The simulator has no USB host, so this tests the
standalone path.
