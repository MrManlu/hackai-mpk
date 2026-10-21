/*
 * Pad LED feedback: incoming MIDI lights the pads.
 *
 * Part of hackai-mpk. Licensed under GPL-3.0-or-later.
 *
 * A note on with a pad's own note and channel (Note#, and Chan or PadCH)
 * lights that pad in its On colour; a note off (or velocity 0) gives it back
 * to the stock code. While a pad is lit by MIDI, hitting it does not change
 * its LED: the sender is in charge. Works for both banks: a pad of the other
 * bank shows its state when that bank is selected. Messages come from the
 * computer (USB, port 1) and from DIN IN (docs/leds.md).
 *
 * Hooks (firmware/hooks.toml): wraps midi_message_handle_APP (messages to the
 * unit) and pad_led_show_APP (every pad LED update); midi_thru.c calls
 * hk_pad_feedback() for DIN IN when USB is connected, since those messages go
 * to the computer instead of midi_message_handle_APP.
 */
#include "hk.h"
#include "stock.h"

void midi_message_handle_APP_original(uint8_t *message);
void pad_led_show_APP_original(uint8_t pad, uint8_t lit);

/* Pads lit by MIDI, one bit per pad (A1 = bit 0 ... B8 = bit 15). */
static struct {
    uint32_t magic;
    uint16_t lit;
} remote HK_RAM;

#define REMOTE_MAGIC 0x4B434246u  /* "FBCK" */

static uint16_t remote_lit(void)
{
    if (remote.magic != REMOTE_MAGIC) {
        remote.magic = REMOTE_MAGIC;
        remote.lit = 0;
    }
    return remote.lit;
}

/* What the stock code wants the pad to show (lit while held, toggles...). */
static uint8_t stock_lit(uint8_t pad)
{
    volatile uint8_t *state = (volatile uint8_t *)(PAD_STATE + pad / 8 * PAD_STATE_BANK
                                                   + pad % 8 * PAD_STATE_SIZE);
    return state[PAD_STATE_LIT] == 1;
}

void hk_pad_led_show(uint8_t pad, uint8_t lit)
{
    if (pad < 8 && !PAD_SPECIAL_MODE && remote_lit() & (1u << (PAD_BANK * 8 + pad)))
        lit = 1;
    pad_led_show_APP_original(pad, lit);
}

void hk_pad_feedback(const uint8_t *message)
{
    uint8_t status = message[0] & 0xF0;
    uint8_t channel = message[0] & 0x0F;

    if (status != 0x90 && status != 0x80)
        return;
    uint8_t on = status == 0x90 && message[2] != 0;
    uint16_t lit = remote_lit();

    for (uint8_t pad = 0; pad < 16; pad++) {
        volatile uint8_t *record = PAD_RECORD(pad);

        if (record[PAD_MODE] != 0 || record[PAD_NOTE] != message[1]
            || hk_pad_channel(pad) != channel)
            continue;
        if (on)
            lit |= 1u << pad;
        else
            lit &= ~(1u << pad);
        remote.lit = lit;
        if (pad / 8 == PAD_BANK && !PAD_SPECIAL_MODE)
            pad_led_show_APP_original(pad % 8, on || stock_lit(pad));
    }
}

void hk_midi_message_handle(uint8_t *message)
{
    hk_pad_feedback(message);
    midi_message_handle_APP_original(message);
}
