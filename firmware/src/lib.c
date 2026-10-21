/*
 * The few C library functions GCC may call on its own (struct and array
 * initialisation). We link without a C library.
 *
 * Part of hackai-mpk. Licensed under GPL-3.0-or-later.
 */
#include <stddef.h>

void *memcpy(void *dst, const void *src, size_t n)
{
    unsigned char *d = dst;
    const unsigned char *s = src;

    while (n--)
        *d++ = *s++;
    return dst;
}

void *memset(void *dst, int c, size_t n)
{
    unsigned char *d = dst;

    while (n--)
        *d++ = (unsigned char)c;
    return dst;
}
