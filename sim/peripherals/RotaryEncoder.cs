//
// Quadrature rotary encoder with detents, for Renode.
//
// Part of hackai-mpk. Licensed under GPL-3.0-or-later.
//
// Outputs 0 (A) and 1 (B) idle high (both contacts open, pull-ups). One detent
// clockwise goes A,B = 11 -> 10 -> 00 -> 01 -> 11; counter-clockwise the other
// way round. Each state is held `stepMicroseconds` of virtual time so the
// firmware's polling sees it.
//
// MPK Mini Plus (FUN_0801df48): state = PC5:PC4; arriving at 3 from 2 counts
// +1, from 1 counts -1. With A = PC4 and B = PC5, the clockwise sequence
// above arrives from state 2 (A=0, B=1): +1.
//
// Connections in the .repl:
//   encoder: Miscellaneous.RotaryEncoder @ sysbus <address>
//       0 -> gpioPortC@4
//       1 -> gpioPortC@5
//
// Monitor commands (for `encoder`):
//   Turn 3 / Turn -1     detents clockwise / counter-clockwise
//
using System.Collections.Generic;

using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.Timers;

namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    public class RotaryEncoder : INumberedGPIOOutput, IDoubleWordPeripheral, IKnownSize
    {
        public RotaryEncoder(IMachine machine, int stepMicroseconds = 1000)
        {
            Connections = new Dictionary<int, IGPIO> { { 0, new GPIO() }, { 1, new GPIO() } };
            pending = new Queue<int>();
            timer = new LimitTimer(machine.ClockSource, 1000000, this, "steps",
                                   limit: (ulong)stepMicroseconds, enabled: false,
                                   eventEnabled: true, autoUpdate: true);
            timer.LimitReached += Step;
            Reset();
        }

        public IReadOnlyDictionary<int, IGPIO> Connections { get; }

        public long Size => 0x4;

        public void Reset()
        {
            pending.Clear();
            timer.Enabled = false;
            Drive(3);
        }

        public uint ReadDoubleWord(long offset)
        {
            return (uint)position;
        }

        public void WriteDoubleWord(long offset, uint value)
        {
        }

        // Queues `detents` steps (negative = counter-clockwise).
        public void Turn(int detents)
        {
            var sequence = detents > 0 ? Clockwise : CounterClockwise;
            for(var d = 0; d < System.Math.Abs(detents); d++)
            {
                foreach(var state in sequence)
                {
                    pending.Enqueue(state);
                }
            }
            position += detents;
            timer.Enabled = true;
        }

        private void Step()
        {
            if(pending.Count == 0)
            {
                timer.Enabled = false;
                return;
            }
            Drive(pending.Dequeue());
        }

        // State bits: 1 = A (output 0), 2 = B (output 1); 1 = contact open.
        private void Drive(int state)
        {
            // Always propagate (see KeyMatrix): GPIO ports forget input levels on reset.
            Connections[0].Set((state & 1) == 0);
            Connections[0].Set((state & 1) != 0);
            Connections[1].Set((state & 2) == 0);
            Connections[1].Set((state & 2) != 0);
        }

        private readonly Queue<int> pending;
        private readonly LimitTimer timer;
        private int position;

        // A,B: 11 -> 10 -> 00 -> 01 -> 11 (as state = B<<1 | A: 3 -> 1 -> 0 -> 2 -> 3).
        private static readonly int[] Clockwise = { 1, 0, 2, 3 };
        private static readonly int[] CounterClockwise = { 2, 0, 1, 3 };
    }
}
