@ Per-pad MIDI channel: the two places where the stock firmware loads PadCH
@ for a pad (firmware/hooks.toml, [[jump]]). Each one replaces a 4-byte load
@ of PadCH into r0, keeps every other register, and returns to the next
@ stock instruction.
@
@ Part of hackai-mpk. Licensed under GPL-3.0-or-later.

    .syntax unified
    .thumb

@ pad_event_APP, 0x08019F5C: "ldrb.w r0, [r9, #16]" (a pad hit), followed by
@ "strb.w r0, [r8, #1]": r8 is the pad's state record.
    .section .text.hk_pad_hit_channel
    .global hk_pad_hit_channel
    .thumb_func
hk_pad_hit_channel:
    push    {r1-r4, r12, lr}        @ 6 registers: the stack stays 8-byte aligned
    mov     r0, r8
    bl      hk_pad_channel_of_state
    pop     {r1-r4, r12, lr}
    ldr.w   pc, =0x08019F61         @ back to the stock code (Thumb bit set)
    .ltorg

@ pad_note_repeat_APP, 0x0801A564: "ldrb.w r0, [sp, #4]" (PadCH saved on the
@ stack), followed by "strb r0, [r6, #1]": r6 is the pad's state record.
    .section .text.hk_pad_repeat_channel
    .global hk_pad_repeat_channel
    .thumb_func
hk_pad_repeat_channel:
    push    {r1-r4, r12, lr}
    mov     r0, r6
    bl      hk_pad_channel_of_state
    pop     {r1-r4, r12, lr}
    ldr.w   pc, =0x0801A569
    .ltorg
