//
// AT32F415 USB OTG full-speed controller: minimal stub for Renode.
//
// Part of hackai-mpk. Licensed under GPL-3.0-or-later.
//
// Enough for the firmware's USB initialisation to finish as if no host were
// connected. Registers (and FIFOs) behave as plain storage, except:
//   GRSTCTL: AHBIDL (bit 31) always set; CSFTRST (bit 0), RXFFLSH (bit 4)
//            and TXFFLSH (bit 5) clear themselves at once.
// Same layout as the STM32F105/107 OTG FS (Synopsys DWC2) core.
//
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.Bus;

namespace Antmicro.Renode.Peripherals.USB
{
    public class AT32_OTGFS : IDoubleWordPeripheral, IKnownSize
    {
        public AT32_OTGFS(IMachine machine)
        {
            registers = new uint[Size / 4];
            Reset();
        }

        public void Reset()
        {
            System.Array.Clear(registers, 0, registers.Length);
        }

        public uint ReadDoubleWord(long offset)
        {
            var value = registers[offset / 4];
            if(offset == Grstctl)
            {
                value |= AhbIdle;
            }
            return value;
        }

        public void WriteDoubleWord(long offset, uint value)
        {
            if(offset == Grstctl)
            {
                value &= ~SelfClearing;
            }
            this.Log(LogLevel.Noisy, "Write 0x{0:X8} at offset 0x{1:X4}", value, offset);
            registers[offset / 4] = value;
        }

        public long Size => 0x40000;

        private readonly uint[] registers;

        private const long Grstctl = 0x10;
        private const uint AhbIdle = 1u << 31;
        private const uint SelfClearing = (1u << 0) | (1u << 4) | (1u << 5);
    }
}
