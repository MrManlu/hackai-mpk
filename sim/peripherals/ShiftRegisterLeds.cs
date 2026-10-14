//
// Chain of 74HC595-style shift registers driving LEDs, for Renode.
//
// Part of hackai-mpk. Licensed under GPL-3.0-or-later.
//
// SPI bytes are shifted into the chain. On the rising edge of the latch
// input (GPIO 0), the chain is copied to the outputs. The firmware does
// software PWM by latching different patterns many times per second, so the
// model integrates each output over virtual time and reports its average
// brightness, as an eye would see it.
//
// Output numbering: output k is bit (7 - k % 8) of byte k / 8, counting the
// bytes in the order they are sent in one transfer. `activeLow`: a 0 bit
// lights the LED.
//
// Connections in the .repl:
//   leds: Miscellaneous.ShiftRegisterLeds @ spi1
//   gpioPortB: 4 -> leds@0            (latch, rising edge)
//
// Monitor commands (for `spi1.leds`):
//   Brightness       one value per output, 0-100 %
//   Show             outputs grouped by byte, as a small text bar chart
//
using System;
using System.Linq;
using System.Text;

using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.SPI;

namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    public class ShiftRegisterLeds : ISPIPeripheral, IGPIOReceiver
    {
        public ShiftRegisterLeds(IMachine machine, int bytes = 7, bool activeLow = true, double windowMs = 20)
        {
            this.machine = machine;
            this.activeLow = activeLow;
            windowSeconds = windowMs / 1000;
            chain = new byte[bytes];
            latched = new byte[bytes];
            onTime = new double[bytes * 8];
            brightness = new double[bytes * 8];
            Reset();
        }

        public int Outputs => chain.Length * 8;

        public byte Transmit(byte data)
        {
            // Shift one byte in: the oldest byte falls off the far end.
            Array.Copy(chain, 1, chain, 0, chain.Length - 1);
            chain[chain.Length - 1] = data;
            return 0;
        }

        public void FinishTransmission()
        {
        }

        public void OnGPIO(int number, bool value)
        {
            if(number == 0 && value && !latch)
            {
                Accumulate();
                Array.Copy(chain, latched, chain.Length);
            }
            if(number == 0)
            {
                latch = value;
            }
        }

        public void Reset()
        {
            Array.Clear(chain, 0, chain.Length);
            Array.Clear(onTime, 0, onTime.Length);
            Array.Clear(brightness, 0, brightness.Length);
            for(var i = 0; i < latched.Length; i++)
            {
                latched[i] = activeLow ? (byte)0xFF : (byte)0x00;
            }
            latch = false;
            windowStart = lastLatch = Now;
        }

        // Average brightness (0.0-1.0) of each output over the last window.
        public double[] GetBrightness()
        {
            Accumulate();
            return (double[])brightness.Clone();
        }

        public string Brightness()
        {
            return string.Join(" ", GetBrightness().Select(b => ((int)Math.Round(b * 100)).ToString()));
        }

        public string Show()
        {
            var values = GetBrightness();
            var text = new StringBuilder();
            for(var b = 0; b < chain.Length; b++)
            {
                text.AppendFormat("byte {0}  outputs {1,2}-{2,2}  ", b, b * 8, b * 8 + 7);
                for(var bit = 0; bit < 8; bit++)
                {
                    text.Append(Bar(values[b * 8 + bit])).Append(' ');
                }
                text.AppendLine();
            }
            return text.ToString();
        }

        private static string Bar(double value)
        {
            const string levels = " .:-=+*#%@";
            return levels[(int)Math.Round(value * (levels.Length - 1))].ToString();
        }

        private double Now => machine.LocalTimeSource.ElapsedVirtualTime.TotalSeconds;

        // Adds the time since the last latch to every output that was lit,
        // and closes the averaging window when it is full.
        private void Accumulate()
        {
            var now = Now;
            var elapsed = now - lastLatch;
            for(var k = 0; k < onTime.Length; k++)
            {
                var bit = (latched[k / 8] >> (7 - k % 8)) & 1;
                if((bit == 0) == activeLow)
                {
                    onTime[k] += elapsed;
                }
            }
            lastLatch = now;

            var window = now - windowStart;
            if(window >= windowSeconds)
            {
                for(var k = 0; k < onTime.Length; k++)
                {
                    brightness[k] = onTime[k] / window;
                    onTime[k] = 0;
                }
                windowStart = now;
            }
        }

        private readonly IMachine machine;
        private readonly bool activeLow;
        private readonly double windowSeconds;
        private readonly byte[] chain;
        private readonly byte[] latched;
        private readonly double[] onTime;
        private readonly double[] brightness;
        private bool latch;
        private double windowStart;
        private double lastLatch;
    }
}
