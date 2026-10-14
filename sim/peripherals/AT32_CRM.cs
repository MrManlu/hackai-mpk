//
// AT32F415 clock and reset manager (CRM), minimal model for Renode.
//
// Part of hackai-mpk. Licensed under GPL-3.0-or-later.
//
// Registers behave as plain storage, except:
//   CTRL: every enabled clock is reported stable at once
//         (HICKEN -> HICKSTBL, HEXTEN -> HEXTSTBL, PLLEN -> PLLSTBL).
//   CFG:  SCLKSTS (bits 3:2) follows SCLKSEL (bits 1:0).
// Same bit positions as the STM32F1 RCC.
//
// When CFG changes, the system clock (SCLK / AHB divider) is computed and
// given to the NVIC, so SysTick runs at the speed the firmware configured.
//
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.IRQControllers;

namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    public class AT32_CRM : IDoubleWordPeripheral, IKnownSize
    {
        public AT32_CRM(IMachine machine, NVIC nvic = null, ulong hextFrequency = 8000000)
        {
            this.nvic = nvic;
            this.hextFrequency = hextFrequency;
            registers = new uint[Size / 4];
            Reset();
        }

        public void Reset()
        {
            System.Array.Clear(registers, 0, registers.Length);
            registers[Ctrl / 4] = HickEnable | HickStable;
            UpdateClock();
        }

        public uint ReadDoubleWord(long offset)
        {
            var value = registers[offset / 4];
            switch(offset)
            {
            case Ctrl:
                if((value & HickEnable) != 0) value |= HickStable;
                if((value & HextEnable) != 0) value |= HextStable;
                if((value & PllEnable) != 0) value |= PllStable;
                break;
            case Cfg:
                value = (value & ~0xCu) | ((value & 0x3u) << 2);
                break;
            }
            return value;
        }

        public void WriteDoubleWord(long offset, uint value)
        {
            this.Log(LogLevel.Noisy, "Write 0x{0:X8} at offset 0x{1:X2}", value, offset);
            registers[offset / 4] = value;
            if(offset == Cfg)
            {
                UpdateClock();
            }
        }

        // Current AHB clock (HCLK) in Hz, as configured by the firmware.
        public ulong SystemClock
        {
            get
            {
                var cfg = registers[Cfg / 4];
                ulong sclk;
                switch(cfg & 0x3)
                {
                case 1:
                    sclk = hextFrequency;
                    break;
                case 2:
                    sclk = PllClock(cfg);
                    break;
                default:
                    sclk = HickFrequency;
                    break;
                }
                var ahbdiv = (cfg >> 4) & 0xF;
                return (ahbdiv & 0x8) == 0 ? sclk : sclk >> AhbShift[ahbdiv & 0x7];
            }
        }

        public long Size => 0x400;

        private ulong PllClock(uint cfg)
        {
            // PLLRCS (bit 16): 0 = HICK / 2, 1 = HEXT (divided by 2 if PLLHEXTDIV, bit 17).
            ulong source;
            if((cfg & (1u << 16)) == 0)
            {
                source = HickFrequency / 2;
            }
            else
            {
                source = (cfg & (1u << 17)) != 0 ? hextFrequency / 2 : hextFrequency;
            }
            // PLLMULT: bits 21:18 (low) and 30:29 (high). 0-14 -> x2..x16, 15 and up -> x(value + 1).
            var mult = ((cfg >> 18) & 0xF) | (((cfg >> 29) & 0x3) << 4);
            return source * (mult < 15 ? mult + 2 : mult + 1);
        }

        private void UpdateClock()
        {
            var clock = SystemClock;
            if(clock == currentClock)
            {
                return;
            }
            currentClock = clock;
            this.Log(LogLevel.Info, "System clock: {0} MHz", clock / 1000000.0);
            if(nvic != null)
            {
                nvic.Frequency = clock;
            }
        }

        private readonly NVIC nvic;
        private readonly ulong hextFrequency;
        private readonly uint[] registers;
        private ulong currentClock;

        private static readonly int[] AhbShift = { 1, 2, 3, 4, 6, 7, 8, 9 };

        private const ulong HickFrequency = 8000000;
        private const long Ctrl = 0x00;
        private const long Cfg = 0x04;
        private const uint HickEnable = 1u << 0;
        private const uint HickStable = 1u << 1;
        private const uint HextEnable = 1u << 16;
        private const uint HextStable = 1u << 17;
        private const uint PllEnable = 1u << 24;
        private const uint PllStable = 1u << 25;
    }
}
