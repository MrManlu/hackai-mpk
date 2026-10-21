//
// MIDI monitor for Renode: listens to the bytes a UART transmits and decodes
// them as MIDI messages.
//
// Part of hackai-mpk. Licensed under GPL-3.0-or-later.
//
// Connections in the .repl:
//   midiOut: Miscellaneous.MidiMonitor @ sysbus <unused address>
//       uart: usart1
//
// Monitor commands (for `midiOut`):
//   Messages 20      last 20 decoded messages, with their virtual time
//   Clear            forget everything
//   Count            number of messages so far
//
using System.Collections.Generic;
using System.Linq;
using System.Text;

using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.UART;

namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    public class MidiMonitor : IDoubleWordPeripheral, IKnownSize
    {
        public MidiMonitor(IMachine machine, IUART uart, int maxMessages = 5000)
        {
            this.machine = machine;
            this.maxMessages = maxMessages;
            messages = new LinkedList<string>();
            current = new List<byte>();
            uart.CharReceived += OnByte;
        }

        public long Size => 0x4;

        public void Reset()
        {
        }

        public uint ReadDoubleWord(long offset)
        {
            return (uint)count;
        }

        public void WriteDoubleWord(long offset, uint value)
        {
        }

        public string Messages(int last = 20)
        {
            lock(messages)
            {
                return string.Join("\n", messages.Skip(System.Math.Max(0, messages.Count - last)));
            }
        }

        public int Count()
        {
            return count;
        }

        public void Clear()
        {
            lock(messages)
            {
                messages.Clear();
                count = 0;
            }
        }

        private void OnByte(byte b)
        {
            if(b >= 0xF8)
            {
                Emit(new[] { b });   // real-time messages can appear anywhere
                return;
            }
            if(b == 0xF7 && current.Count > 0 && current[0] == 0xF0)
            {
                current.Add(b);      // end of SysEx: not a new status byte
                Emit(current.ToArray());
                current.Clear();
                status = 0;
                return;
            }
            if(b >= 0x80)
            {
                status = b;
                current.Clear();
                current.Add(b);
                if(b == 0xF0)
                {
                    return;
                }
            }
            else
            {
                if(status == 0)
                {
                    return;   // data byte without a status: ignore
                }
                if(current.Count == 0)
                {
                    current.Add(status);   // running status
                }
                current.Add(b);
            }
            if(status == 0xF0 || (current.Count > 0 && current[0] == 0xF0))
            {
                if(b == 0xF7)
                {
                    Emit(current.ToArray());
                    current.Clear();
                    status = 0;
                }
                return;
            }
            if(current.Count == Length(status))
            {
                Emit(current.ToArray());
                current.Clear();
            }
        }

        private static int Length(byte status)
        {
            switch(status & 0xF0)
            {
            case 0xC0: case 0xD0: return 2;
            case 0xF0:
                return status == 0xF1 || status == 0xF3 ? 2 : status == 0xF2 ? 3 : 1;
            default: return 3;
            }
        }

        private void Emit(byte[] m)
        {
            var time = machine.LocalTimeSource.ElapsedVirtualTime.TotalSeconds;
            var hex = string.Join(" ", m.Select(x => x.ToString("X2")));
            var text = $"{time,10:F4} s  {hex,-12} {Describe(m)}";
            lock(messages)
            {
                messages.AddLast(text);
                if(messages.Count > maxMessages)
                {
                    messages.RemoveFirst();
                }
                count++;
            }
        }

        private static string Describe(byte[] m)
        {
            var ch = (m[0] & 0x0F) + 1;
            switch(m[0] & 0xF0)
            {
            case 0x80: return $"Note Off  ch{ch} note {m[1]} vel {m[2]}";
            case 0x90: return m[2] == 0 ? $"Note Off  ch{ch} note {m[1]} (vel 0)" : $"Note On   ch{ch} note {m[1]} vel {m[2]}";
            case 0xA0: return $"Poly AT   ch{ch} note {m[1]} {m[2]}";
            case 0xB0: return $"CC        ch{ch} cc {m[1]} = {m[2]}";
            case 0xC0: return $"Program   ch{ch} {m[1]}";
            case 0xD0: return $"Chan AT   ch{ch} {m[1]}";
            case 0xE0: return $"Pitch     ch{ch} {(m[1] | (m[2] << 7)) - 8192}";
            }
            switch(m[0])
            {
            case 0xF0: return $"SysEx     {m.Length} bytes";
            case 0xF8: return "Clock";
            case 0xFA: return "Start";
            case 0xFB: return "Continue";
            case 0xFC: return "Stop";
            case 0xFE: return "Active Sensing";
            default: return "";
            }
        }

        private readonly IMachine machine;
        private readonly int maxMessages;
        private readonly LinkedList<string> messages;
        private readonly List<byte> current;
        private byte status;
        private int count;
    }
}
