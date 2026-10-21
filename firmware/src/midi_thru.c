/*
 * MIDI THRU: what arrives at DIN IN also leaves through DIN OUT.
 *
 * Part of hackai-mpk. Licensed under GPL-3.0-or-later.
 *
 * Replaces din_in_poll_APP (0x0801240E), see firmware/hooks.toml. It does
 * what the stock function does (parse the DIN IN bytes into messages; send
 * them to the host if USB is configured, otherwise handle them locally) and,
 * with THRU on (Global menu, entry 7), also queues each complete message for
 * DIN OUT. Whole messages, never single bytes, so they cannot land inside a
 * message of the keyboard itself (docs/midi.md).
 */
#include "hk.h"
#include "stock.h"

/* Bytes in a USB-MIDI packet, by Code Index Number, as the stock code counts
 * them (usb_midi_in_send_APP): 0 for reserved CINs. */
static uint8_t cin_length(uint8_t cin)
{
    static const uint8_t length[16] = {
        0, 0, 2, 3, 3, 1, 2, 3, 3, 3, 3, 3, 2, 2, 3, 1,
    };
    return length[cin & 0x0F];
}

/* Messages dropped because DIN OUT was full (for debugging). */
static struct {
    uint32_t magic;
    uint32_t dropped;
} thru_stats HK_RAM;

#define THRU_STATS_MAGIC 0x55524854u  /* "THRU" */

static void thru_send(const uint8_t *message, uint8_t count)
{
    uint8_t free = (uint8_t)(DIN_TX_READ - DIN_TX_WRITE - 1) & (DIN_TX_SIZE - 1);

    if (count <= free) {
        din_tx_queue_APP(count, message);
        return;
    }
    if (thru_stats.magic != THRU_STATS_MAGIC) {
        thru_stats.magic = THRU_STATS_MAGIC;
        thru_stats.dropped = 0;
    }
    thru_stats.dropped++;
}

void hk_din_in_poll(void)
{
    if (DIN_IN_PAUSED)
        return;

    while (din_rx_count_APP() != 0) {
        uint8_t byte = din_rx_read_APP();
        uint32_t word;

        if (!midi_parser_feed_APP(MIDI_PARSER_DIN, byte, &word))
            continue;

        uint8_t packet[4] = {
            (uint8_t)(word >> 24), (uint8_t)(word >> 16), (uint8_t)(word >> 8), (uint8_t)word,
        };

        if (USB_STATE == USB_CONFIGURED) {
            uint16_t at = USB_IN_WRITE;
            for (int i = 0; i < 4; i++)
                USB_IN_RING[at + i] = packet[i];
            USB_IN_WRITE = (at + 4) & 0x7F;
        } else {
            midi_message_handle_APP(&packet[1]);
        }

        if (hk_settings()->midi_thru) {
            uint8_t count = cin_length(packet[0]);
            if (count)
                thru_send(&packet[1], count);
        }
    }
}
