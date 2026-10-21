/*
 * hackai-mpk: where our code goes in the stock image (docs/patching.md).
 *
 * Part of hackai-mpk. Licensed under GPL-3.0-or-later.
 *
 * Code and constants: the free area after the application, from 0x08026000
 * up to our settings sector at 0x0802D800. RAM: the top 256 bytes, never used
 * by the stock firmware and never initialised (no .data or .bss allowed:
 * mark variables HK_RAM and initialise them lazily).
 */
MEMORY
{
    HK_FLASH (rx) : ORIGIN = 0x08026000, LENGTH = 0x0802D800 - 0x08026000
    HK_RAM   (rw) : ORIGIN = 0x20007F00, LENGTH = 0x100
}

SECTIONS
{
    .text :
    {
        *(.text*)
        *(.rodata*)
    } > HK_FLASH

    .hk_ram (NOLOAD) :
    {
        *(.hk_ram*)
    } > HK_RAM

    .data : { *(.data*) } > HK_RAM
    .bss : { *(.bss*) *(COMMON) } > HK_RAM

    /DISCARD/ : { *(.ARM.exidx*) *(.ARM.attributes) *(.comment) }
}

ASSERT(SIZEOF(.data) == 0, "no initialised data: nothing would copy it to RAM")
ASSERT(SIZEOF(.bss) == 0, "no .bss: nothing would clear it; use HK_RAM")

/* Stock functions and labels, generated from config/symbols.csv. */
INCLUDE stock.ld
