//
// Key matrix with active-low rows and columns, for Renode.
//
// Part of hackai-mpk. Licensed under GPL-3.0-or-later.
//
// The firmware drives the rows (GPIO inputs 0..rows-1 of this model) and
// reads the columns (outputs 0..columns-1). A column reads low while any
// pressed key on it sits on a row that is driven low; otherwise it reads high
// (pull-up). Diodes are assumed, so there is no ghosting.
//
// Connections in the .repl (MPK Mini Plus: rows PC0-PC3, columns PC8-PC13):
//   gpioPortC:
//       [0-3] -> keys@[0-3]
//   keys:
//       [0-5] -> gpioPortC@[8-13]
//
// The model sits on the system bus at an address the MCU does not use, only
// so that it has a name in the Renode monitor. Reading its single register
// returns a bitmap of pressed keys (bit = row * columns + column).
//
// Monitor commands (for `keys`):
//   Press 1 2 / Release 1 2      key at row 1, column 2
//   Pressed                      list of pressed keys
//
using System.Collections.Generic;
using System.Linq;

using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.Bus;

namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    public class KeyMatrix : IGPIOReceiver, INumberedGPIOOutput, IDoubleWordPeripheral, IKnownSize
    {
        public KeyMatrix(IMachine machine, int rows = 4, int columns = 6)
        {
            rowLow = new bool[rows];
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

        public uint ReadDoubleWord(long offset)
        {
            var bitmap = 0u;
            for(var r = 0; r < rowLow.Length; r++)
            {
                for(var c = 0; c < Connections.Count; c++)
                {
                    if(pressed[r, c])
                    {
                        bitmap |= 1u << (r * Connections.Count + c);
                    }
                }
            }
            return bitmap;
        }

        public void WriteDoubleWord(long offset, uint value)
        {
        }

        public void Reset()
        {
            for(var r = 0; r < rowLow.Length; r++)
            {
                rowLow[r] = false;
            }
            System.Array.Clear(pressed, 0, pressed.Length);
            Update();
        }

        // Row inputs from the GPIO port: low = row selected.
        public void OnGPIO(int number, bool value)
        {
            if(number < 0 || number >= rowLow.Length)
            {
                return;
            }
            rowLow[number] = !value;
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
            for(var r = 0; r < rowLow.Length; r++)
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
            if(row < 0 || row >= rowLow.Length || column < 0 || column >= Connections.Count)
            {
                this.Log(LogLevel.Warning, "No key at row {0}, column {1}", row, column);
                return;
            }
            pressed[row, column] = value;
            Update();
        }

        private void Update()
        {
            for(var c = 0; c < Connections.Count; c++)
            {
                var low = Enumerable.Range(0, rowLow.Length).Any(r => rowLow[r] && pressed[r, c]);
                Connections[c].Set(!low);
            }
        }

        private readonly bool[] rowLow;
        private readonly bool[,] pressed;
    }
}
