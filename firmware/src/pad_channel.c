/*
 * Per-pad MIDI channel.
 *
 * Part of hackai-mpk. Licensed under GPL-3.0-or-later.
 *
 * When a pad is hit, the stock firmware copies PadCH (program byte 0x10) into
 * the pad's state, and every message of that hit (note on/off, CC, PC,
 * aftertouch) uses the copy. Note repeat does the same on each retrigger.
 * Two jump hooks (pad_channel_hooks.S) replace those two loads of PadCH with
 * hk_pad_channel_of_state(), so each pad can have its own channel; the note
 * off still goes out on the channel of its note on (docs/pads.md).
 */
#include "hk.h"
#include "stock.h"

uint8_t hk_pad_channel(uint8_t pad)
{
    uint8_t channel = pad < 16 ? hk_settings()->pad_channel[pad] : 0;

    return channel ? channel - 1 : PROGRAM[PROG_PAD_CHANNEL];
}

/* Called from the jump hooks with the address of a pad's state record. */
uint8_t hk_pad_channel_of_state(uint32_t state)
{
    uint32_t offset = state - PAD_STATE;
    uint32_t pad = offset / PAD_STATE_BANK * 8 + offset % PAD_STATE_BANK / PAD_STATE_SIZE;

    return hk_pad_channel((uint8_t)pad);
}
