//
// SPI recorder for Renode: stores every byte sent to it, with its virtual
// time, to reverse-engineer what the firmware sends on a bus.
//
// Part of hackai-mpk. Licensed under GPL-3.0-or-later.
//
// Bytes are grouped into bursts: a gap longer than `burstGapUs` virtual
// microseconds starts a new burst. Monitor commands (for `spi1.recorder`):
//   Bursts 10        last 10 bursts: start time, length and hex bytes
//   Summary          number of bursts, bytes, and the burst lengths seen
//   Clear            forget everything recorded so far
//
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;

using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.SPI;

namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    public class SpiRecorder : ISPIPeripheral
    {
        public SpiRecorder(IMachine machine, double burstGapUs = 20, int maxBursts = 2000)
        {
            this.machine = machine;
            this.burstGapUs = burstGapUs;
            this.maxBursts = maxBursts;
            bursts = new LinkedList<Burst>();
        }

        public byte Transmit(byte data)
        {
            var now = machine.LocalTimeSource.ElapsedVirtualTime.TotalSeconds * 1e6;
            if(current == null || now - lastByteUs > burstGapUs)
            {
                current = new Burst { StartUs = now };
                bursts.AddLast(current);
                if(bursts.Count > maxBursts)
                {
                    bursts.RemoveFirst();
                }
            }
            current.Bytes.Add(data);
            lastByteUs = now;
            totalBytes++;
            return 0;
        }

        public void FinishTransmission()
        {
        }

        public void Reset()
        {
            Clear();
        }

        public void Clear()
        {
            bursts.Clear();
            current = null;
            totalBytes = 0;
        }

        public string Bursts(int count = 10)
        {
            var text = new StringBuilder();
            foreach(var burst in bursts.Skip(Math.Max(0, bursts.Count - count)))
            {
                text.AppendFormat("{0,12:F1} us  {1,4} B  ", burst.StartUs, burst.Bytes.Count);
                text.AppendLine(string.Join(" ", burst.Bytes.Select(b => b.ToString("X2"))));
            }
            return text.ToString();
        }

        public string Summary()
        {
            var lengths = bursts.GroupBy(b => b.Bytes.Count)
                .OrderBy(g => g.Key)
                .Select(g => $"{g.Key} B x{g.Count()}");
            var span = bursts.Count > 1 ? bursts.Last.Value.StartUs - bursts.First.Value.StartUs : 0;
            return $"{bursts.Count} bursts kept, {totalBytes} bytes in total, "
                + $"{span / Math.Max(1, bursts.Count - 1):F1} us between bursts on average\n"
                + "burst lengths: " + string.Join(", ", lengths);
        }

        private readonly IMachine machine;
        private readonly double burstGapUs;
        private readonly int maxBursts;
        private readonly LinkedList<Burst> bursts;
        private Burst current;
        private double lastByteUs;
        private ulong totalBytes;

        private class Burst
        {
            public double StartUs;
            public List<byte> Bytes = new List<byte>();
        }
    }
}
