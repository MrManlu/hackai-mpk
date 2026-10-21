/*
 * hackai-mpk settings, stored in our own flash sector.
 *
 * Part of hackai-mpk. Licensed under GPL-3.0-or-later.
 *
 * The sector (0x0802D800, 2 KB) is a log of 32-byte records. Saving writes
 * the next free record; the sector is erased only when it is full (every 64
 * saves). Loading takes the last record with a valid magic. The magic word is
 * written last, so a save interrupted by a power cut leaves the previous
 * record as the valid one. A firmware update erases the sector: settings go
 * back to their defaults.
 */
#include "hk.h"
#include "stock.h"

#define SECTOR        0x0802D800u
#define SECTOR_SIZE   0x800u
#define RECORD_WORDS  (sizeof(struct hk_settings) / 4)
#define RECORDS       (SECTOR_SIZE / sizeof(struct hk_settings))

#define HK_SETTINGS_MAGIC 0x314D4B48u  /* "HKM1" */

_Static_assert(sizeof(struct hk_settings) == 32, "records are 32 bytes");

static struct hk_settings current HK_RAM;

static const uint32_t *record(uint32_t n)
{
    return (const uint32_t *)(SECTOR + n * sizeof(struct hk_settings));
}

static int record_is_free(const uint32_t *r)
{
    for (uint32_t i = 0; i < RECORD_WORDS; i++)
        if (r[i] != 0xFFFFFFFFu)
            return 0;
    return 1;
}

static void load(void)
{
    const uint32_t *last = 0;
    uint32_t *dst = (uint32_t *)&current;

    for (uint32_t n = 0; n < RECORDS; n++)
        if (record(n)[0] == HK_SETTINGS_MAGIC)
            last = record(n);

    for (uint32_t i = 0; i < RECORD_WORDS; i++)
        dst[i] = last ? last[i] : 0;
    current.magic = HK_SETTINGS_MAGIC;

    if (current.midi_thru > 1)
        current.midi_thru = 0;
    for (uint32_t i = 0; i < sizeof(current.pad_channel); i++)
        if (current.pad_channel[i] > 16)
            current.pad_channel[i] = 0;
}

static void save(void)
{
    const uint32_t *src = (const uint32_t *)&current;
    uint32_t n = 0;

    while (n < RECORDS && !record_is_free(record(n)))
        n++;

    flash_unlock();
    flash_flag_clear(FLASH_FLAGS_ALL);
    if (n == RECORDS) {
        flash_sector_erase_APP(SECTOR);
        flash_flag_clear(FLASH_FLAGS_ALL);
        n = 0;
    }
    volatile uint32_t *dst = (volatile uint32_t *)record(n);
    for (uint32_t i = 1; i < RECORD_WORDS; i++) {
        flash_word_program_APP(&dst[i], src[i]);
        flash_flag_clear(FLASH_FLAGS_ALL);
    }
    flash_word_program_APP(&dst[0], src[0]);  /* magic last */
    flash_flag_clear(FLASH_FLAGS_ALL);
    flash_lock();
}

const struct hk_settings *hk_settings(void)
{
    if (current.magic != HK_SETTINGS_MAGIC)
        load();
    return &current;
}

void hk_settings_set(uint32_t offset, uint8_t value)
{
    uint8_t *bytes = (uint8_t *)&current;

    hk_settings();
    if (offset < 4 || offset >= sizeof(current) || bytes[offset] == value)
        return;
    bytes[offset] = value;
    save();
}
