//
// AT32F415 ADC1 with external analog multiplexers, minimal model for Renode.
//
// Part of hackai-mpk. Licensed under GPL-3.0-or-later.
//
// Same register layout as the STM32F1 ADC. Supported: software-started
// regular sequences (OSQ1-OSQ3), scan and continuous modes, DMA requests
// (one per conversion, `DMARequest` output), calibration bits that clear at
// once. Conversions take `conversionMicroseconds` of virtual time each.
//
// The board puts 8:1 analog multiplexers (74HC4051-style) in front of the
// ADC inputs, with shared select lines on GPIO inputs 0-2 of this model. The
// value converted for a channel is input[channel, select]. Inputs are set
// from the monitor (`adc1 SetInput 2 5 4095`) or a front end.
//
// Connections in the .repl:
//   adc1: Analog.AT32_ADC @ sysbus 0x40012400
//       DMARequest -> dma1@1
//   gpioPortB:
//       [0-2] -> adc1@[0-2]            (multiplexer select, MPK Mini Plus)
//
using System;
using System.Text;

using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;

namespace Antmicro.Renode.Peripherals.Analog
{
    public class AT32_ADC : IDoubleWordPeripheral, IWordPeripheral, IKnownSize, IGPIOReceiver
    {
        public AT32_ADC(IMachine machine, int channels = 18, int muxInputs = 8,
                        int conversionMicroseconds = 10, int defaultValue = 0)
        {
            registers = new uint[Size / 4];
            inputs = new ushort[channels, muxInputs];
            select = new bool[3];
            DMARequest = new GPIO();
            for(var c = 0; c < channels; c++)
            {
                for(var m = 0; m < muxInputs; m++)
                {
                    inputs[c, m] = (ushort)defaultValue;
                }
            }
            timer = new LimitTimer(machine.ClockSource, 1000000, this, "conversion",
                                   limit: (ulong)conversionMicroseconds, enabled: false,
                                   eventEnabled: true, autoUpdate: true);
            timer.LimitReached += Convert;
            Reset();
        }

        public GPIO DMARequest { get; }

        public long Size => 0x50;

        public void Reset()
        {
            Array.Clear(registers, 0, registers.Length);
            timer.Enabled = false;
            position = 0;
        }

        public uint ReadDoubleWord(long offset)
        {
            var value = registers[offset / 4];
            if(offset == Odt)
            {
                registers[Sts / 4] &= ~Eoc;
            }
            return value;
        }

        public void WriteDoubleWord(long offset, uint value)
        {
            if(offset == Ctrl2)
            {
                value &= ~(Cal | RstCal);   // calibration is instantaneous
                var start = (value & SwStart) != 0;
                value &= ~SwStart;
                registers[offset / 4] = value;
                if((value & AdOn) == 0)
                {
                    timer.Enabled = false;
                }
                else if(start)
                {
                    position = 0;
                    registers[Sts / 4] |= Strt;
                    timer.Value = 0;
                    timer.Enabled = true;
                }
                return;
            }
            if(offset == Sts)
            {
                registers[Sts / 4] &= value;   // flags are cleared by writing 0
                return;
            }
            registers[offset / 4] = value;
        }

        // 16-bit accesses: the DMA reads ODT as half-words.
        public ushort ReadWord(long offset)
        {
            return (ushort)(ReadDoubleWord(offset & ~3) >> (int)((offset & 2) * 8));
        }

        public void WriteWord(long offset, ushort value)
        {
            var aligned = offset & ~3;
            var shift = (int)((offset & 2) * 8);
            var current = registers[aligned / 4] & ~(0xFFFFu << shift);
            WriteDoubleWord(aligned, current | ((uint)value << shift));
        }

        // Multiplexer select lines.
        public void OnGPIO(int number, bool value)
        {
            if(number >= 0 && number < select.Length)
            {
                select[number] = value;
            }
        }

        public int Select => (select[0] ? 1 : 0) | (select[1] ? 2 : 0) | (select[2] ? 4 : 0);

        public void SetInput(int channel, int mux, int value)
        {
            inputs[channel, mux] = (ushort)Math.Max(0, Math.Min(4095, value));
        }

        // All multiplexer inputs of a channel at once.
        public void SetChannel(int channel, int value)
        {
            for(var m = 0; m < inputs.GetLength(1); m++)
            {
                SetInput(channel, m, value);
            }
        }

        public string Inputs()
        {
            var text = new StringBuilder();
            for(var c = 0; c < inputs.GetLength(0); c++)
            {
                text.AppendFormat("ch{0,-2}", c);
                for(var m = 0; m < inputs.GetLength(1); m++)
                {
                    text.AppendFormat(" {0,4}", inputs[c, m]);
                }
                text.AppendLine();
            }
            return text.ToString();
        }

        private void Convert()
        {
            var length = (int)((registers[Osq1 / 4] >> 20) & 0xF) + 1;
            var scan = (registers[Ctrl1 / 4] & Scan) != 0;
            if(!scan)
            {
                length = 1;
            }
            var channel = SequenceChannel(position);
            var value = channel < inputs.GetLength(0) ? inputs[channel, Select] : (ushort)0;
            registers[Odt / 4] = value;
            registers[Sts / 4] |= Eoc;
            if((registers[Ctrl2 / 4] & Dma) != 0)
            {
                DMARequest.Blink();
            }

            position++;
            if(position >= length)
            {
                position = 0;
                if((registers[Ctrl2 / 4] & Cont) == 0)
                {
                    timer.Enabled = false;
                    registers[Sts / 4] &= ~Strt;
                }
            }
        }

        // Channel of the n-th conversion (0-based) of the regular sequence.
        private int SequenceChannel(int n)
        {
            long offset = n < 6 ? Osq3 : n < 12 ? Osq2 : Osq1;
            var shift = 5 * (n % 6);
            return (int)((registers[offset / 4] >> shift) & 0x1F);
        }

        private readonly uint[] registers;
        private readonly ushort[,] inputs;
        private readonly bool[] select;
        private readonly LimitTimer timer;
        private int position;

        private const long Sts = 0x00;
        private const long Ctrl1 = 0x04;
        private const long Ctrl2 = 0x08;
        private const long Osq1 = 0x2C;
        private const long Osq2 = 0x30;
        private const long Osq3 = 0x34;
        private const long Odt = 0x4C;

        private const uint Eoc = 1u << 1;
        private const uint Strt = 1u << 4;
        private const uint Scan = 1u << 8;
        private const uint AdOn = 1u << 0;
        private const uint Cont = 1u << 1;
        private const uint Cal = 1u << 2;
        private const uint RstCal = 1u << 3;
        private const uint Dma = 1u << 8;
        private const uint SwStart = 1u << 22;
    }
}
