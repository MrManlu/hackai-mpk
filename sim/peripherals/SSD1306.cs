//
// SSD1306 OLED controller (SPI, 4-wire with D/C pin) for Renode.
//
// Part of hackai-mpk. Licensed under GPL-3.0-or-later.
// Structure based on Renode's ST7789 model (MIT, Copyright (c) 2010-2026 Antmicro).
//
// Supports what the MPK Mini Plus firmware uses (see docs/display.md):
// page / horizontal / vertical addressing, column and page ranges, display
// on/off, inversion, entire-display-on and segment/COM remapping. Contrast,
// timing and charge pump commands are accepted and ignored.
//
// Connections in the .repl:
//   oled: Video.SSD1306 @ spi2       (SPI bytes)
//   gpioPortB: 14 -> oled@0          (D/C: low = command, high = data)
//
using System;
using System.Collections.Generic;

using Antmicro.Renode.Backends.Display;
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.SPI;

namespace Antmicro.Renode.Peripherals.Video
{
    public class SSD1306 : AutoRepaintingVideo, ISPIPeripheral, IGPIOReceiver
    {
        public SSD1306(IMachine machine, int width = 128, int height = 32, int scale = 4,
                       uint onColor = 0xFFFFFF, uint offColor = 0x000000) : base(machine)
        {
            panelWidth = width;
            panelHeight = height;
            this.scale = scale;
            on = Rgb(onColor);
            off = Rgb(offColor);
            gddram = new byte[Columns * Pages];
            args = new List<byte>();

            Reconfigure(width: width * scale, height: height * scale, format: PixelFormat.RGB888, autoRepaint: true);
            FramesPerVirtualSecond = 30;
            Reset();
        }

        public void OnGPIO(int number, bool value)
        {
            dataMode = value;
        }

        public override void Reset()
        {
            Array.Clear(gddram, 0, gddram.Length);
            args.Clear();
            pendingCommand = null;
            addressingMode = AddressingMode.Page;
            columnStart = 0;
            columnEnd = Columns - 1;
            pageStart = 0;
            pageEnd = Pages - 1;
            column = 0;
            page = 0;
            displayOn = false;
            inverted = false;
            entireDisplayOn = false;
            segmentRemap = false;
            comRemap = false;
            startLine = 0;
        }

        public byte Transmit(byte data)
        {
            if(dataMode)
            {
                dataBytes++;
                if(data != 0)
                {
                    nonZeroDataBytes++;
                }
                WriteData(data);
            }
            else
            {
                commandBytes++;
                WriteCommand(data);
            }
            return 0;
        }

        // Counters and state, for debugging: `spi2.oled Statistics` in the monitor.
        public string Statistics()
        {
            return $"commands: {commandBytes}, data: {dataBytes} ({nonZeroDataBytes} non-zero), "
                + $"display {(displayOn ? "on" : "off")}, mode {addressingMode}, "
                + $"page {page} column {column}, D/C {(dataMode ? "data" : "command")}";
        }

        public void FinishTransmission()
        {
        }

        protected override void Repaint()
        {
            for(var y = 0; y < panelHeight; y++)
            {
                for(var x = 0; x < panelWidth; x++)
                {
                    var lit = displayOn && (entireDisplayOn || (PixelAt(x, y) ^ inverted));
                    var color = lit ? on : off;
                    for(var dy = 0; dy < scale; dy++)
                    {
                        // Leave a thin dark gap between pixels for an OLED look.
                        var gap = scale >= 3 && dy == scale - 1;
                        var offset = (((y * scale + dy) * panelWidth * scale) + x * scale) * 3;
                        for(var dx = 0; dx < scale; dx++)
                        {
                            var c = gap || (scale >= 3 && dx == scale - 1) ? off : color;
                            buffer[offset++] = c[0];
                            buffer[offset++] = c[1];
                            buffer[offset++] = c[2];
                        }
                    }
                }
            }
        }

        // Text dump of the visible panel, for headless runs and tests:
        // `oled AsciiArt` in the Renode monitor.
        public string AsciiArt()
        {
            var text = new System.Text.StringBuilder();
            for(var y = 0; y < panelHeight; y++)
            {
                for(var x = 0; x < panelWidth; x++)
                {
                    var lit = displayOn && (entireDisplayOn || (PixelAt(x, y) ^ inverted));
                    text.Append(lit ? '#' : '.');
                }
                text.Append('\n');
            }
            return text.ToString();
        }

        private bool PixelAt(int x, int y)
        {
            var col = segmentRemap ? Columns - 1 - x : x;
            var row = (comRemap ? panelHeight - 1 - y : y) + startLine;
            row %= Pages * 8;
            return (gddram[(row / 8) * Columns + col] & (1 << (row % 8))) != 0;
        }

        private void WriteData(byte data)
        {
            gddram[page * Columns + column] = data;
            switch(addressingMode)
            {
            case AddressingMode.Horizontal:
                if(++column > columnEnd)
                {
                    column = columnStart;
                    page = page >= pageEnd ? pageStart : page + 1;
                }
                break;
            case AddressingMode.Vertical:
                if(++page > pageEnd)
                {
                    page = pageStart;
                    column = column >= columnEnd ? columnStart : column + 1;
                }
                break;
            default: // page addressing: wrap within the page
                column = (column + 1) % Columns;
                break;
            }
        }

        private void WriteCommand(byte data)
        {
            if(pendingCommand.HasValue)
            {
                args.Add(data);
                if(args.Count < ArgumentCount(pendingCommand.Value))
                {
                    return;
                }
                ExecuteWithArguments(pendingCommand.Value);
                pendingCommand = null;
                args.Clear();
                return;
            }

            if(ArgumentCount(data) > 0)
            {
                pendingCommand = data;
                return;
            }

            if(data <= 0x0F)
            {
                column = (column & 0xF0) | (data & 0x0F);
            }
            else if(data <= 0x1F)
            {
                column = ((data & 0x07) << 4) | (column & 0x0F);
            }
            else if(data >= 0x40 && data <= 0x7F)
            {
                startLine = data & 0x3F;
            }
            else if(data >= 0xB0 && data <= 0xB7)
            {
                page = data & 0x07;
            }
            else
            {
                switch(data)
                {
                case 0xA0: segmentRemap = false; break;
                case 0xA1: segmentRemap = true; break;
                case 0xA4: entireDisplayOn = false; break;
                case 0xA5: entireDisplayOn = true; break;
                case 0xA6: inverted = false; break;
                case 0xA7: inverted = true; break;
                case 0xAE: displayOn = false; break;
                case 0xAF: displayOn = true; break;
                case 0xC0: comRemap = false; break;
                case 0xC8: comRemap = true; break;
                case 0xE3: break; // NOP
                default:
                    this.Log(LogLevel.Warning, "Unsupported command 0x{0:X2}", data);
                    break;
                }
            }
        }

        private void ExecuteWithArguments(byte command)
        {
            switch(command)
            {
            case 0x20:
                addressingMode = (AddressingMode)(args[0] & 0x03);
                break;
            case 0x21:
                columnStart = args[0] & 0x7F;
                columnEnd = args[1] & 0x7F;
                column = columnStart;
                break;
            case 0x22:
                pageStart = args[0] & 0x07;
                pageEnd = args[1] & 0x07;
                page = pageStart;
                break;
            default:
                // Contrast, multiplex, offset, clock, pre-charge, COM pins,
                // VCOMH, charge pump: no visible effect in this model.
                this.Log(LogLevel.Debug, "Ignored command 0x{0:X2} {1}", command, BitConverter.ToString(args.ToArray()));
                break;
            }
        }

        private static int ArgumentCount(byte command)
        {
            switch(command)
            {
            case 0x20: case 0x81: case 0x8D: case 0xA8: case 0xD3:
            case 0xD5: case 0xD9: case 0xDA: case 0xDB:
                return 1;
            case 0x21: case 0x22:
                return 2;
            default:
                return 0;
            }
        }

        private static byte[] Rgb(uint color)
        {
            return new[] { (byte)(color >> 16), (byte)(color >> 8), (byte)color };
        }

        private readonly int panelWidth;
        private readonly int panelHeight;
        private readonly int scale;
        private readonly byte[] on;
        private readonly byte[] off;
        private readonly byte[] gddram;
        private readonly List<byte> args;

        private bool dataMode;
        private ulong commandBytes, dataBytes, nonZeroDataBytes;
        private byte? pendingCommand;
        private AddressingMode addressingMode;
        private int columnStart, columnEnd, pageStart, pageEnd;
        private int column, page, startLine;
        private bool displayOn, inverted, entireDisplayOn, segmentRemap, comRemap;

        private const int Columns = 128;
        private const int Pages = 8;

        private enum AddressingMode
        {
            Horizontal = 0,
            Vertical = 1,
            Page = 2,
        }
    }
}
