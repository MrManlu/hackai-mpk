/*
 * Global menu (SHIFT + STOP) with our own entries.
 *
 * Part of hackai-mpk. Licensed under GPL-3.0-or-later.
 *
 * Replaces global_menu_draw_APP (0x080183F8) and global_menu_encoder_APP
 * (0x0801F3A8), see firmware/hooks.toml. Entries 1-6 behave exactly like the
 * stock ones (docs/menus.md); entry 7, THRU, is ours and is stored in our
 * settings sector.
 */
#include "hk.h"
#include "stock.h"

enum {
    E_TRANS, E_MIDI, E_PADCH, E_PADAT, E_TAPS, E_TPRT,  /* stock */
    E_THRU,                                             /* hackai-mpk */
    ENTRIES
};

static const char *const labels[ENTRIES] = {
    "Trans:", " MIDI:", "PadCH:", "PadAT:", " Taps:", " Tprt:",
    " THRU:",
};

/* Two digits, the tens blank when zero, as the stock menus print numbers. */
static void put_number(char *s, uint8_t n)
{
    s[0] = n / 10 ? '0' + n / 10 : ' ';
    s[1] = '0' + n % 10;
}

static void put_text(char *s, const char *text)
{
    while (*text)
        *s++ = *text++;
}

/* The value column: 5 characters. */
static void format_value(uint8_t entry, char *v)
{
    uint8_t b;

    switch (entry) {
    case E_TRANS:
        b = PROGRAM[PROG_TRANSPOSE];
        if (b < 12) {
            v[0] = '-';
            put_number(&v[1], 12 - b);
        } else {
            put_number(&v[1], b - 12);
        }
        break;
    case E_MIDI:
        put_number(v, PROGRAM[PROG_MIDI_CHANNEL] + 1);
        break;
    case E_PADCH:
        put_number(v, PROGRAM[PROG_PAD_CHANNEL] + 1);
        break;
    case E_PADAT:
        b = PROGRAM[PROG_PAD_AFTERTOUCH];
        if (b <= 2)
            put_text(v, b == 0 ? "Off  " : b == 1 ? "Chan " : "Poly ");
        break;
    case E_TAPS:
        v[0] = '0' + PROGRAM[PROG_TAPS];
        break;
    case E_TPRT:
        put_text(v, PROGRAM[PROG_TPRT] == 0 ? "On   " : "OnOff");
        break;
    case E_THRU:
        put_text(v, hk_settings()->midi_thru ? "On   " : "Off  ");
        break;
    }
}

void hk_global_menu_draw(void)
{
    if (UI_SCREEN != SCREEN_GLOBAL) {
        framebuffer_clear_APP();
        UI_EDIT = 0;
        UI_CURSOR = 0;
    }
    UI_SCREEN = SCREEN_GLOBAL;
    menu_title_rule_APP();
    print_LCD_APP((uint16_t)((128 - FONT_MENU[0] * 6) >> 1), 0, "Global", FONT_MENU, 0);

    /* Two rows: the cursor entry and the next one, or the last two. */
    uint8_t entry = UI_CURSOR == ENTRIES - 1 ? ENTRIES - 2 : UI_CURSOR;
    for (uint8_t row = 0; row < 2; row++, entry++) {
        uint16_t y = (uint16_t)(FONT_MENU[1] * row + 0x0c);
        char number[3] = { (char)('1' + entry), '.', 0 };
        char value[6] = "     ";

        format_value(entry, value);
        print_LCD_APP(0, y, number, FONT_MENU, 0);
        print_LCD_APP(0x13, y, labels[entry], FONT_MENU, UI_EDIT == 0 && entry == UI_CURSOR);
        print_LCD_APP(0x4e, y, value, FONT_MENU, UI_EDIT == 1 && entry == UI_CURSOR);
    }

    TICKS_LAST_ACTIVITY[0] = TICKS_NOW[0];
    TICKS_LAST_ACTIVITY[1] = TICKS_NOW[1];
    UI_STATE = 2;
}

/* Steps a program byte between lo and hi; returns 1 if it changed. */
static int step(uint8_t offset, int8_t detents, uint8_t lo, uint8_t hi)
{
    uint8_t b = PROGRAM[offset];

    if (detents < 1) {
        if (b <= lo)
            return 0;
        PROGRAM[offset] = b - 1;
    } else {
        if (b >= hi)
            return 0;
        PROGRAM[offset] = b + 1;
    }
    return 1;
}

void hk_global_menu_encoder(int8_t detents)
{
    if (UI_EDIT == 0) {
        if (detents < 1) {
            if (UI_CURSOR != 0)
                UI_CURSOR--;
        } else if (UI_CURSOR < ENTRIES - 1) {
            UI_CURSOR++;
        }
    } else {
        switch (UI_CURSOR) {
        case E_TRANS:
            if (step(PROG_TRANSPOSE, detents, 0, 24))
                transpose_apply_POSSIBLE_APP();
            break;
        case E_MIDI:
            step(PROG_MIDI_CHANNEL, detents, 0, 15);
            break;
        case E_PADCH:
            step(PROG_PAD_CHANNEL, detents, 0, 15);
            break;
        case E_PADAT:
            step(PROG_PAD_AFTERTOUCH, detents, 0, 2);
            break;
        case E_TAPS:
            step(PROG_TAPS, detents, 2, 4);
            break;
        case E_TPRT:
            step(PROG_TPRT, detents, 0, 1);
            break;
        case E_THRU:
            hk_settings_set(HK_SETTING(midi_thru), detents < 1 ? 0 : 1);
            break;
        }
    }
    hk_global_menu_draw();
}
