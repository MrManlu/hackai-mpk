/*
 * Pad edit menu (SHIFT + PROG SELECT, then hit a pad) with our own entry.
 *
 * Part of hackai-mpk. Licensed under GPL-3.0-or-later.
 *
 * Replaces pad_edit_menu_draw_APP (0x08018C3C) and wraps pad_edit_encoder_APP
 * (0x0801E304), see firmware/hooks.toml. Entries 1-7 behave exactly like the
 * stock ones (the stock encoder still edits them, including the live pad LED
 * colour); entry 8, Chan, is ours: the pad's MIDI channel, "Glob" (the
 * program's PadCH, as stock) or 1-16, stored in our settings sector.
 */
#include "hk.h"
#include "stock.h"

enum {
    E_NOTE, E_CC, E_PC, E_OFF_COLOUR, E_ON_COLOUR, E_MODE, E_TOGGLE,  /* stock */
    E_CHANNEL,                                                       /* hackai-mpk */
    ENTRIES
};

static const char *const labels[ENTRIES] = {
    "Note#:", "  CC#:", "  PC#:", "Off C:", " On C:", "PMode:", "Toggl:",
    " Chan:",
};

uint32_t pad_edit_encoder_APP_original(int8_t detents);

/* Three digits, leading zeros blank, as the stock pad menu prints them. */
static void put_number3(char *s, uint8_t n)
{
    s[0] = n / 100 ? '0' + n / 100 : ' ';
    s[1] = n / 100 || n / 10 % 10 ? '0' + n / 10 % 10 : ' ';
    s[2] = '0' + n % 10;
}

/* Two digits, the tens blank when zero. */
static void put_number2(char *s, uint8_t n)
{
    s[0] = n / 10 ? '0' + n / 10 : ' ';
    s[1] = '0' + n % 10;
}

static void put_text(char *s, const char *text)
{
    while (*text)
        *s++ = *text++;
}

static void format_value(uint8_t pad, uint8_t entry, char *v)
{
    volatile uint8_t *record = PAD_RECORD(pad);
    uint8_t b;

    switch (entry) {
    case E_NOTE:
        put_number3(v, record[PAD_NOTE]);
        break;
    case E_CC:
        put_number3(v, record[PAD_CC]);
        break;
    case E_PC:
        put_number3(v, record[PAD_PC]);
        break;
    case E_OFF_COLOUR:
        put_number2(v, record[PAD_OFF_COLOUR]);
        break;
    case E_ON_COLOUR:
        put_number2(v, record[PAD_ON_COLOUR]);
        break;
    case E_MODE:
        b = record[PAD_MODE];
        if (b <= 2)
            put_text(v, b == 0 ? "Note " : b == 1 ? "PC   " : "CC   ");
        break;
    case E_TOGGLE:
        b = record[PAD_TOGGLE];
        if (b <= 1)
            put_text(v, b == 0 ? "Off  " : "On   ");
        break;
    case E_CHANNEL:
        b = hk_settings()->pad_channel[pad];
        if (b == 0)
            put_text(v, "Glob ");
        else
            put_number2(v, b);
        break;
    }
}

void hk_pad_edit_menu_draw(uint8_t pad)
{
    if (UI_SCREEN != SCREEN_PAD_EDIT) {
        framebuffer_clear_APP();
        UI_EDIT = 0;
        UI_CURSOR = 0;
    }
    UI_SCREEN = SCREEN_PAD_EDIT;
    menu_title_rule_APP();

    char title[7] = "Pad A1";
    title[4] = pad > 7 ? 'B' : 'A';
    title[5] = (char)('1' + pad % 8);
    print_LCD_APP((uint16_t)((128 - FONT_MENU[0] * 6) >> 1), 0, title, FONT_MENU, 0);

    uint8_t entry = UI_CURSOR == ENTRIES - 1 ? ENTRIES - 2 : UI_CURSOR;
    for (uint8_t row = 0; row < 2; row++, entry++) {
        uint16_t y = (uint16_t)(FONT_MENU[1] * row + 0x0c);
        char number[3] = { (char)('1' + entry), '.', 0 };
        char value[6] = "     ";

        format_value(pad, entry, value);
        print_LCD_APP(0, y, number, FONT_MENU, 0);
        print_LCD_APP(0x13, y, labels[entry], FONT_MENU, UI_EDIT == 0 && entry == UI_CURSOR);
        print_LCD_APP(0x4e, y, value, FONT_MENU, UI_EDIT == 1 && entry == UI_CURSOR);
    }

    TICKS_LAST_ACTIVITY[0] = TICKS_NOW[0];
    TICKS_LAST_ACTIVITY[1] = TICKS_NOW[1];
    UI_STATE = 2;
}

uint32_t hk_pad_edit_encoder(int8_t detents)
{
    uint8_t pad = PAD_EDITING;

    if (UI_EDIT == 0) {
        if (detents < 1) {
            if (UI_CURSOR != 0)
                UI_CURSOR--;
        } else if (UI_CURSOR < ENTRIES - 1) {
            UI_CURSOR++;
        }
    } else if (UI_CURSOR == E_CHANNEL) {
        uint8_t channel = pad < 16 ? hk_settings()->pad_channel[pad] : 0;

        if (detents < 1 && channel > 0)
            channel--;
        else if (detents >= 1 && channel < 16)
            channel++;
        if (pad < 16)
            hk_settings_set(HK_SETTING(pad_channel) + pad, channel);
    } else {
        return pad_edit_encoder_APP_original(detents);  /* stock entries; redraws */
    }
    hk_pad_edit_menu_draw(pad);
    return 0;
}
