//
// Key matrix scanned through a row decoder, for Renode.
//
// Part of hackai-mpk. Licensed under GPL-3.0-or-later.
//
// The firmware puts a row number on `addressBits` GPIO lines (inputs
// 0..addressBits-1 of this model); a decoder (74HC154-style) pulls that row
// low. The firmware then reads the columns (outputs 0..columns-1): a column
// reads low while the key at (selected row, column) is pressed, high otherwise
// (pull-up). Diodes are assumed, so there is no ghosting.
//
// Connections in the .repl (MPK Mini Plus: address PC0-PC3, columns PC8-PC13):
//   gpioPortC:
//       [0-3] -> keys@[0-3]
//   keys:
//       [0-5] -> gpioPortC@[8-13]
//
// The model sits on the system bus at an address the MCU does not use, only
// so that it has a name in the Renode monitor. Reading its register returns
// the row currently selected by the firmware.
//
// Monitor commands (for `keys`):
//   Press 10 2 / Release 10 2    key at row 10, column 2
//   Pressed                      list of pressed keys
//
using System.Collections.Generic;

using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.Bus;

namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    public class KeyMatrix : IGPIOReceiver, INumberedGPIOOutput, IDoubleWordPeripheral, IKnownSize
    {
        public KeyMatrix(IMachine machine, int addressBits = 4, int columns = 6)
        {
            address = new bool[addressBits];
            rows = 1 << addressBits;
            pressed = new bool[rows, columns];
            var connections = new Dictionary<int, IGPIO>();
            for(var c = 0; c < columns; c++)
            {
                connections[c] = new GPIO();
            }
            Connections = connections;
            Reset();
        }

        public IReadOnlyDictionary<int, IGPIO> Connections { get; }

        public long Size => 0x4;

        public int SelectedRow
        {
            get
            {
                var row = 0;
                for(var bit = 0; bit < address.Length; bit++)
                {
                    if(address[bit])
                    {
                        row |= 1 << bit;
                    }
                }
                return row;
            }
        }

        public uint ReadDoubleWord(long offset)
        {
            return (uint)SelectedRow;
        }

        public void WriteDoubleWord(long offset, uint value)
        {
        }

        public void Reset()
        {
            for(var bit = 0; bit < address.Length; bit++)
            {
                address[bit] = false;
            }
            System.Array.Clear(pressed, 0, pressed.Length);
            Update();
        }

        // Address lines from the GPIO port.
        public void OnGPIO(int number, bool value)
        {
            if(number < 0 || number >= address.Length)
            {
                return;
            }
            address[number] = value;
            Update();
        }

        public void Press(int row, int column)
        {
            Set(row, column, true);
        }

        public void Release(int row, int column)
        {
            Set(row, column, false);
        }

        public string Pressed()
        {
            var keys = new List<string>();
            for(var r = 0; r < rows; r++)
            {
                for(var c = 0; c < Connections.Count; c++)
                {
                    if(pressed[r, c])
                    {
                        keys.Add($"{r},{c}");
                    }
                }
            }
            return string.Join(" ", keys);
        }

        private void Set(int row, int column, bool value)
        {
            if(row < 0 || row >= rows || column < 0 || column >= Connections.Count)
            {
                this.Log(LogLevel.Warning, "No key at row {0}, column {1}", row, column);
                return;
            }
            pressed[row, column] = value;
            Update();
        }

        private void Update()
        {
            var row = SelectedRow;
            for(var c = 0; c < Connections.Count; c++)
            {
                var low = pressed[row, c];
                // Always propagate: Renode only forwards changes, and the GPIO
                // port forgets its input levels on reset while this GPIO keeps
                // its state. Both edges happen at the same virtual instant.
                Connections[c].Set(low);
                Connections[c].Set(!low);
            }
        }

        private readonly bool[] address;
        private readonly int rows;
        private readonly bool[,] pressed;
    }
}
