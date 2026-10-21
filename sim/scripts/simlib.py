"""Drive the simulator from Python scripts: start Renode with a firmware image
and talk to its monitor. Used by the sim/scripts/*_check.py scripts.

Part of hackai-mpk. Licensed under GPL-3.0-or-later.
"""

import re
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import mpkflash  # noqa: E402


class Sim(mpkflash.SimTransport):
    """A simulated MPK Mini Plus running `image`, driven through the Renode monitor."""

    def __init__(self, image, port=4373):
        """Starts Renode headless with `image` loaded as the flash."""
        script = f"$firmware=@{Path(image).resolve()}; include @sim/mpk.resc; include @sim/quiet.resc"
        self.renode = subprocess.Popen([mpkflash.RENODE, "--disable-gui", "--plain", "--port", str(port),
                                        "-e", script], cwd=ROOT,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(300):
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("could not connect to Renode")
        self.buffer = b""
        self._read()

    def u64(self, address):
        lo, hi = self._values(self.run(f"sysbus ReadDoubleWord 0x{address:08X}; "
                                       f"sysbus ReadDoubleWord 0x{address + 4:08X}"))[-2:]
        return hi << 32 | lo

    def set_u64(self, address, value):
        value &= (1 << 64) - 1
        self.run(f"sysbus WriteDoubleWord 0x{address:08X} 0x{value & 0xFFFFFFFF:08X}; "
                 f"sysbus WriteDoubleWord 0x{address + 4:08X} 0x{value >> 32:08X}")

    def screen(self, seconds):
        return "\n".join(mpkflash.text_screen(self.boot_screen(seconds)))

    def press(self, row, column, hold=0.2):
        """Presses and releases a button of the key matrix."""
        self.run(f"keys Press {row} {column}")
        self.run(f'emulation RunFor "{hold}"')
        self.run(f"keys Release {row} {column}")

    def combo(self, held, pressed, hold=0.2):
        """Holds one button while pressing another (SHIFT + ...)."""
        self.run(f"keys Press {held[0]} {held[1]}")
        self.run(f'emulation RunFor "{hold}"')
        self.press(*pressed, hold=hold)
        self.run(f"keys Release {held[0]} {held[1]}")

    def turn(self, detents):
        self.run(f"encoder Turn {detents}")

    def read(self, address, length):
        out = self.run(f"sysbus ReadBytes 0x{address:08X} {length}")
        out = out[out.index("["):]
        return bytes(int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})\b", out))
