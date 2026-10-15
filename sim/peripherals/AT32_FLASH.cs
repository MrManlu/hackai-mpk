//
// AT32F415 flash controller, minimal model for Renode.
//
// Part of hackai-mpk. Licensed under GPL-3.0-or-later.
//
// Same layout as the STM32F1 FLASH interface:
//   0x04 UNLOCK  write 0x45670123 then 0xCDEF89AB to clear OPLK
//   0x0C STS     BSY (bit 0) never set; PRGMERR (2), EPPERR (4), ODF (5)
//                cleared by writing 1
//   0x10 CTRL    FPRGM (0), SECERS (1), BANKERS (2), ERSTR (6), OPLK (7)
//   0x14 ADDR    sector address for SECERS
//
// Programming: with FPRGM set the firmware writes words straight to flash
// addresses, which Renode's MappedMemory accepts as they are. Erasing: ERSTR
// with SECERS fills the `sectorSize` sector containing ADDR with 0xFF; with
// BANKERS it fills the whole flash. Every operation completes at once and
// sets ODF.
//
// Connections in the .repl:
//   flashCtrl: Miscellaneous.AT32_FLASH @ sysbus 0x40022000
//       flashBase: 0x08000000
//       flashSize: 0x40000
//
using System.Linq;

using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.Bus;

namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    public class AT32_FLASH : IDoubleWordPeripheral, IKnownSize
    {
        public AT32_FLASH(IMachine machine, ulong flashBase = 0x08000000, ulong flashSize = 0x40000,
                          ulong sectorSize = 0x800)
        {
            this.machine = machine;
            this.flashBase = flashBase;
            this.flashSize = flashSize;
            this.sectorSize = sectorSize;
            registers = new uint[Size / 4];
            Reset();
        }

        public long Size => 0x400;

        public void Reset()
        {
            System.Array.Clear(registers, 0, registers.Length);
            registers[Ctrl / 4] = Oplk;
            keyStep = 0;
        }

        public uint ReadDoubleWord(long offset)
        {
            return offset / 4 < registers.Length ? registers[offset / 4] : 0;
        }

        public void WriteDoubleWord(long offset, uint value)
        {
            switch(offset)
            {
            case Unlock:
                if(keyStep == 0 && value == Key1)
                {
                    keyStep = 1;
                }
                else if(keyStep == 1 && value == Key2)
                {
                    registers[Ctrl / 4] &= ~Oplk;
                    keyStep = 0;
                }
                else
                {
                    keyStep = 0;
                }
                return;
            case Sts:
                registers[Sts / 4] &= ~(value & (PrgmErr | EppErr | Odf));
                return;
            case Ctrl:
                if((registers[Ctrl / 4] & Oplk) != 0 && (value & Oplk) == 0)
                {
                    this.Log(LogLevel.Warning, "CTRL write while locked: 0x{0:X}", value);
                    return;
                }
                if((value & ErStr) != 0)
                {
                    if((value & BankErs) != 0)
                    {
                        Erase(flashBase, flashSize);
                    }
                    else if((value & SecErs) != 0)
                    {
                        var address = registers[Addr / 4] & ~(uint)(sectorSize - 1);
                        Erase(address, sectorSize);
                    }
                    value &= ~ErStr;
                    registers[Sts / 4] |= Odf;
                }
                registers[Ctrl / 4] = value;
                return;
            default:
                if(offset / 4 < registers.Length)
                {
                    registers[offset / 4] = value;
                }
                return;
            }
        }

        private void Erase(ulong address, ulong length)
        {
            if(address < flashBase || address + length > flashBase + flashSize)
            {
                this.Log(LogLevel.Warning, "Erase outside flash: 0x{0:X} + 0x{1:X}", address, length);
                registers[Sts / 4] |= EppErr;
                return;
            }
            this.Log(LogLevel.Info, "Erase 0x{0:X8} - 0x{1:X8}", address, address + length - 1);
            machine.SystemBus.WriteBytes(Enumerable.Repeat((byte)0xFF, (int)length).ToArray(), address);
        }

        private readonly IMachine machine;
        private readonly ulong flashBase;
        private readonly ulong flashSize;
        private readonly ulong sectorSize;
        private readonly uint[] registers;
        private int keyStep;

        private const long Unlock = 0x04;
        private const long Sts = 0x0C;
        private const long Ctrl = 0x10;
        private const long Addr = 0x14;

        private const uint Key1 = 0x45670123;
        private const uint Key2 = 0xCDEF89AB;

        private const uint PrgmErr = 1u << 2;
        private const uint EppErr = 1u << 4;
        private const uint Odf = 1u << 5;
        private const uint SecErs = 1u << 1;
        private const uint BankErs = 1u << 2;
        private const uint ErStr = 1u << 6;
        private const uint Oplk = 1u << 7;
    }
}
