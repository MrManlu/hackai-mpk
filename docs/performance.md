# Performance: how much CPU the mods take

**Result: the mods add about 0.13 % of CPU load** under a heavy MIDI load.
The real cost to keep in mind is not CPU time but flash writes (below).

```bash
make cpu-load    # ~4 minutes: our image and the stock one, same load
```

## Method

Measured in the simulator with Renode's profiler, `sim/scripts/cpu_load.py`:

1. **Load.** Boot the image with MIDI THRU on (a settings record written
   before boot), then for about one virtual second feed DIN IN at roughly the
   full MIDI rate (~3000 bytes/s): 250 note on/off pairs (a quarter of them
   pad 1's note, so the LED feedback fires) and 250 CCs; meanwhile hit pad 1.
2. **Profiler.** Renode's "collapsed stack" profiler
   (`cpu EnableProfilerCollapsedStack`) counts the instructions executed per
   call stack. The script adds up the instructions run inside our code
   (`0x08026000` up) and under every stock function we hook.
3. **Compare with stock.** The profiler books instructions to the function
   that was *called*, and our replace and wrap hooks are entered with a jump
   from the stock function's entry, so part of our work is booked to the
   stock function (e.g. our DIN IN task to `din_in_poll_APP`). So the same
   load runs on the stock image too: the difference between the two, under
   the hooked functions, is the extra cost of the mods.
4. **From instructions to CPU.** The application runs the core at **144 MHz**
   (SysTick on the processor clock, reload 2879 for its 20 µs tick: 2880
   cycles per tick). The simulator executes 100 M instructions per virtual
   second, the same order as the real Cortex-M4 at 144 MHz (about one
   instruction per cycle, a little less with flash wait states). The share
   measured in the simulator is therefore a fair estimate of the real one.

The simulator is not cycle-accurate, so these are estimates; the margin is
large enough that this does not matter.

## Results (2026-10-21)

| | Instructions |
|---|---|
| Profiled in total (~1.2 virtual s) | 286.6 M |
| Under the hooked functions, stock firmware | 372,706 |
| Under the hooked functions and in our code, hackai | 731,181 |
| **Extra cost of the mods** | **358,475 (0.125 %)** |

Where it goes, as booked by the profiler (functions we call):

| Function | Instructions | Share |
|---|---|---|
| `hk_pad_feedback` | 330,783 | 0.115 % |
| `hk_settings` | 2,345 | 0.001 % |
| `hk_pad_channel_of_state` | 160 | < 0.001 % |

Nearly all of it is the pad LED feedback: for each received note it checks
the 16 pads, about 650 instructions (≈ 5 µs at 144 MHz). Even 10,000 notes per
second over USB would stay under 5 %; it could be made cheaper with a lookup
table if ever needed. Menus run only while you use them; the per-pad channel
costs a few dozen instructions per hit; THRU a few dozen per message.

## Flash writes

Saving a setting programs 8 flash words, and every 64 saves the 2 KB settings
sector is erased. The CPU stalls while the flash is busy, because the code
runs from it: during an erase, a DIN IN byte arriving can be lost, exactly as
with the stock program SAVE. This only happens while editing settings in the
menus. A possible improvement: save when leaving the edit mode instead of on
every encoder step.

## Lessons from measuring

- The profile files are huge: ~450 MB per virtual second of this load. The
  first attempt filled the disk. The script now profiles in ten windows of
  0.1 s, deletes each file once added up, and stops if less than 400 MB are
  free.
- Renode hangs when the profiler is enabled on a named pipe, so a FIFO is
  not an option.
- Renode's USART model holds bytes that arrive back to back and delivers them
  later (also with the stock firmware), so counts of messages out of DIN OUT
  during such a burst are not a measure of losses
  ([simulator.md](simulator.md)).
