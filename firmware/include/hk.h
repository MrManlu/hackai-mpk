/*
 * hackai-mpk: common definitions for our code.
 *
 * Part of hackai-mpk. Licensed under GPL-3.0-or-later.
 */
#ifndef HK_H
#define HK_H

#include <stdint.h>

/*
 * Our RAM: the top 256 bytes of RAM (0x20007F00), which the stock firmware
 * never touches (docs/patching.md). Nothing initialises it: it holds whatever
 * was there at power-up, so every user checks a magic value first.
 */
#define HK_RAM __attribute__((section(".hk_ram")))

/* --- Our settings (settings.c) -------------------------------------------- */

struct hk_settings {
    uint32_t magic;       /* HK_SETTINGS_MAGIC: record (and RAM copy) valid */
    uint8_t midi_thru;    /* 0 Off, 1 On */
    uint8_t pad_channel[16]; /* per pad (A1-A8, B1-B8): 0 = the program's
                                PadCH (stock), 1-16 = that MIDI channel */
    uint8_t reserved[11]; /* future settings; 0 by default */
};

/* The current settings (loaded from flash on first use). */
const struct hk_settings *hk_settings(void);

/* Changes one byte of the settings and stores them (only if it changed). */
void hk_settings_set(uint32_t offset, uint8_t value);

#define HK_SETTING(field) ((uint32_t)__builtin_offsetof(struct hk_settings, field))

/* --- Per-pad MIDI channel (pad_channel.c) --------------------------------- */

/* The MIDI channel (0-15) of a pad (0-15), from our settings or PadCH. */
uint8_t hk_pad_channel(uint8_t pad);

/* --- Pad LED feedback (pad_feedback.c) ------------------------------------ */

/* A received MIDI message (status, data1, data2) from USB or DIN IN. */
void hk_pad_feedback(const uint8_t *message);

#endif
