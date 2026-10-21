#!/usr/bin/env python3
"""Show the screensaver of a firmware image in the simulator, without waiting.

Boots the image, then moves the screensaver's "last activity" time stamp
(64-bit tick counter at 0x20004BF0, ticks of 20 us) 5 minutes into the past, so
the firmware believes nobody touched a control for 5 minutes. Prints the
screen before, at the screensaver, and 5 s later (inverted).

    python3 sim/scripts/screensaver_check.py [IMAGE]
"""

import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import mpkflash  # noqa: E402

NOW, LAST = 0x20004CB8, 0x20004BF0
STATE = 0x20004DA6                 # 1 = temporary screen (boot), 2 = normal, 3 = screensaver
IDLE = 15_000_001 + 100            # screensaver timeout in ticks, plus a margin


class Sim(mpkflash.SimTransport):
    def __init__(self, image, port=4373):
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


def main():
    image = sys.argv[1] if len(sys.argv) > 1 else str(mpkflash.STOCK)
    sim = Sim(image)
    try:
        print("--- after boot")
        print(sim.screen(3))
        for _ in range(60):        # the boot screen ends with last activity = now
            state = sim._values(sim.run(f"sysbus ReadByte 0x{STATE:08X}"))[-1]
            if state == 2:
                break
            sim.run('emulation RunFor "0.5"')
        else:
            raise RuntimeError(f"the UI never reached the normal state (state {state})")
        sim.set_u64(LAST, sim.u64(NOW) - IDLE)
        print("--- screensaver")
        print(sim.screen(0.5))
        print("--- 5 s later")
        print(sim.screen(5.2))
    finally:
        sim.close()


if __name__ == "__main__":
    main()
