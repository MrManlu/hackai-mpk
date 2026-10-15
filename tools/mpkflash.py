#!/usr/bin/env python3
"""mpkflash: check and flash MPK Mini Plus firmware images.

Speaks the bootloader's USB HID update protocol (docs/bootloader.md):
"UO" + C4 (version), C1 (erase), C2 (write 16 bytes), C3 (finish); the
device answers "UI" + F1-F4, or E2 on a rejected write.

    mpkflash.py check IMAGE            safety checks, no device needed
    mpkflash.py info  --sim | --hid    ask the bootloader for the version (harmless:
                                       the application answers E4 and is left alone)
    mpkflash.py flash IMAGE --sim | --hid

--sim runs the image in the Renode simulator: it boots into update mode
(SHIFT + PROG SELECT held), injects the packets into the bootloader's receive
ring and reads its replies, so the real bootloader code does the flashing.
--hid talks to a real unit in update mode through /dev/hidraw (power it on
holding SHIFT + PROG SELECT; see docs/updater.md for permissions).
"""

import argparse
import glob
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STOCK = ROOT / "baserom" / "firmware.bin"
RENODE = os.environ.get("RENODE", "/opt/renode_1.17.0-portable/renode")

FLASH_BASE = 0x08000000
FLASH_SIZE = 0x40000
PAYLOAD = (0x05000, 0x0A000)       # bootloader update payload
UPDATABLE = (0x05000, 0x3F000)     # written directly by C2
CONFIG = (0x3F800, 0x40000)        # buffered, written when the trailer arrives
MARKER = (0x2E7FE, 0x2E800)        # application-present marker
VID_PID = bytes.fromhex("09e80054")

ERASE, WRITE, FINISH, VERSION = 0xC1, 0xC2, 0xC3, 0xC4
OK = {ERASE: 0xF1, WRITE: 0xF2, FINISH: 0xF3, VERSION: 0xF4}
APP_RUNNING = 0xE4   # the application answers C4 with E4 and ignores the rest


# ---------------------------------------------------------------------------
# Image checks
# ---------------------------------------------------------------------------

def check_image(image, stock):
    """Return (errors, warnings). Errors make flashing unsafe."""
    errors, warnings = [], []
    if len(image) != FLASH_SIZE:
        errors.append(f"size is {len(image)} bytes, expected {FLASH_SIZE}")
        return errors, warnings
    a, b = PAYLOAD
    if image[a:b] != stock[a:b]:
        errors.append("bootloader payload (0x08005000-0x08009FFF) differs from the stock "
                      "one: the application would copy it over the bootloader")
    if any(x == 0xFF for x in image[MARKER[0]:MARKER[1]]):
        errors.append("application-present marker (0x0802E7FE) is 0xFF: the bootloader "
                      "would stay in update mode")
    sp, reset = int.from_bytes(image[0xA000:0xA004], "little"), int.from_bytes(image[0xA004:0xA008], "little")
    if not (0x20000000 <= sp <= 0x20008000) or not (0x0800A000 <= reset < 0x0802E000 and reset & 1):
        errors.append(f"application vector table looks wrong (SP 0x{sp:08X}, reset 0x{reset:08X})")
    if image[0x3FFF0:0x3FFF4] != VID_PID:
        errors.append("trailer does not carry VID/PID 09E8:0054")
    if image[0x3FFF5] != stock[0x3FFF5]:
        warnings.append(f"configuration layout byte is 0x{image[0x3FFF5]:02X} (stock "
                        f"0x{stock[0x3FFF5]:02X}): the bootloader will not keep the calibration")
    if image[:a] != stock[:a]:
        warnings.append("bootloader area differs from stock: ignored, the bootloader "
                        "never overwrites itself over USB")
    return errors, warnings


def version_of(image):
    return f"{image[0x3FFF6]:x}.{image[0x3FFF7]:02x}"


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

def packet(command, address=0, data=b""):
    p = bytearray(32)
    p[0:2] = b"UO"
    p[2] = command
    if command == WRITE:
        p[3:7] = (FLASH_BASE + address).to_bytes(4, "big")
        p[9:25] = data
        p[30:32] = (sum(data) & 0xFFFF).to_bytes(2, "big")
    return bytes(p)


def write_plan(image):
    """Offsets of the 16-byte chunks to send, in order: the updatable area
    (skipping chunks that are all 0xFF, already erased by C1), then the whole
    configuration sector, whose last chunk (the trailer) commits it."""
    plan = [o for o in range(UPDATABLE[0], UPDATABLE[1], 16)
            if image[o:o + 16] != b"\xff" * 16]
    plan += list(range(CONFIG[0], CONFIG[1], 16))
    return plan


class Updater:
    def __init__(self, transport, log=print):
        self.t = transport
        self.log = log

    def command(self, command, address=0, data=b""):
        return self.check(command, address, self.t.exchange(packet(command, address, data)))

    @staticmethod
    def check(command, address, reply):
        if reply[:2] != b"UI":
            raise RuntimeError(f"no valid reply to 0x{command:02X}: {reply[:8].hex(' ')}")
        if command == VERSION and reply[2] == APP_RUNNING:
            raise RuntimeError("the application is running, not the bootloader: power the "
                               "unit on while holding SHIFT + PROG SELECT (update mode)")
        if reply[2] != OK[command]:
            raise RuntimeError(f"command 0x{command:02X} at 0x{FLASH_BASE + address:08X} "
                               f"answered 0x{reply[2]:02X}")
        return reply

    def version(self):
        reply = self.command(VERSION)
        return f"{reply[3]:x}.{reply[4]:02x}"

    def flash(self, image):
        plan = write_plan(image)
        self.log(f"device firmware {self.version()}, image {version_of(image)}, "
                 f"{len(plan)} packets")
        self.command(ERASE)
        self.log("erased 0x08005000-0x0803EFFF")
        start, done, batch = time.time(), 0, self.t.batch
        for i in range(0, len(plan), batch):
            offsets = plan[i:i + batch]
            replies = self.t.exchange_many([packet(WRITE, o, image[o:o + 16]) for o in offsets])
            for offset, reply in zip(offsets, replies):
                self.check(WRITE, offset, reply)
            done += len(offsets)
            if done // 1000 != (done - len(offsets)) // 1000 or done == len(plan):
                rate = done / max(time.time() - start, 1e-6)
                self.log(f"  {done}/{len(plan)} packets ({rate:.0f}/s)")
        self.command(FINISH)
        self.log("finished: the device resets into the new firmware")


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------

class SimTransport:
    """The Renode simulator, booted into update mode. Packets are written into
    the bootloader's receive ring (4 x 32 bytes at 0x20001630, read index at
    0x2000173C, write index at 0x2000173E); the reply is read from its
    transmit buffer at 0x200016F0."""

    RING, READ, WRITE, REPLY = 0x20001630, 0x2000173C, 0x2000173E, 0x200016F0
    PROMPT = b"(mpk) "

    def __init__(self, port=4370, image=None):
        script = "include @sim/mpk.resc; include @sim/quiet.resc"
        if image:
            script = f"$firmware=@{Path(image).resolve()}; " + script
        self.renode = subprocess.Popen(
            [RENODE, "--disable-gui", "--plain", "--port", str(port), "-e", script],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        # Power on with SHIFT + PROG SELECT held: update mode.
        self.run("keys Press 11 3; keys Press 11 5; emulation RunFor \"1\"; "
                 "keys Release 11 3; keys Release 11 5")
        self.slot = int(self.run(f"sysbus ReadWord 0x{self.WRITE:08X}").split()[-1], 16)

    def _read(self):
        self.sock.settimeout(120)
        while self.PROMPT not in self.buffer:
            data = self.sock.recv(65536)
            if not data:
                break
            self.buffer += data
        head, _, self.buffer = self.buffer.partition(self.PROMPT)
        return re.sub(rb"\xff[\xfb-\xfe].", b"", head).decode(errors="replace").replace("\r", "")

    def run(self, line):
        self.sock.sendall(line.encode() + b"\n")
        return self._read()

    def _send(self, data):
        """Monitor commands that queue one packet and let the bootloader take it."""
        address = self.RING + self.slot
        self.slot = (self.slot + 0x20) & 0x7F
        words = "; ".join(f"sysbus WriteDoubleWord 0x{address + i:08X} "
                          f"0x{int.from_bytes(data[i:i + 4], 'little'):08X}" for i in range(0, 32, 4))
        return (f"sysbus WriteDoubleWord 0x{self.REPLY:08X} 0; {words}; "
                f"sysbus WriteWord 0x{self.WRITE:08X} 0x{self.slot:04X}; emulation RunFor \"0.002\"")

    @staticmethod
    def _values(output):
        return [int(l, 16) for l in output.split("\n") if re.fullmatch(r"0x[0-9A-Fa-f]+", l.strip())]

    def exchange(self, data):
        # Done when the bootloader has taken the packet or has replied (C3
        # replies and then resets, before moving the read index).
        poll = f"sysbus ReadWord 0x{self.READ:08X}; sysbus ReadDoubleWord 0x{self.REPLY:08X}"
        out = self.run(self._send(data) + "; " + poll)
        for _ in range(1000):   # erasing takes longer
            index, word = self._values(out)[-2:]
            if index == self.slot or (word & 0xFFFF00 and word & 0xFFFF == 0x4955):
                break
            out = self.run('emulation RunFor "0.01"; ' + poll)
        else:
            raise RuntimeError("the simulated bootloader does not take packets")
        reply = self.run(f"sysbus ReadBytes 0x{self.REPLY:08X} 32")
        values = reply[reply.index("["):]   # skip the echoed command
        return bytes(int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})\b", values))

    # Every monitor round trip costs ~0.1 s, so writes go in batches: one
    # monitor line per batch, reading back the read index and the first reply
    # word ("UI" + status) after each packet.
    batch = 256

    def exchange_many(self, packets):
        commands, slots = [], []
        for data in packets:
            commands.append(self._send(data) + f"; sysbus ReadWord 0x{self.READ:08X}; "
                            f"sysbus ReadDoubleWord 0x{self.REPLY:08X}")
            slots.append(self.slot)
        values = self._values(self.run("; ".join(commands)))
        replies = []
        for n, slot in enumerate(slots):
            index, word = values[2 * n], values[2 * n + 1]
            if index != slot:
                raise RuntimeError("the simulated bootloader fell behind (packet not taken in 2 ms)")
            replies.append(word.to_bytes(4, "little"))
        return replies

    def read_flash(self, start=0, end=FLASH_SIZE, step=0x1000):
        data = bytearray()
        for a in range(start, end, step):
            out = self.run(f"sysbus ReadBytes 0x{FLASH_BASE + a:08X} {step}")
            out = out[out.index("["):]
            data += bytes(int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})\b", out))
        return bytes(data)

    def boot_screen(self, seconds=4):
        self.run(f'emulation RunFor "{seconds}"')
        rows = [l for l in self.run("spi2.oled AsciiArt").splitlines() if re.fullmatch(r"[.#]+", l)]
        return rows

    def close(self):
        try:
            self.run("quit")
        except OSError:
            pass
        self.renode.terminate()
        self.renode.wait(10)


class HidTransport:
    """A real unit in update mode, through Linux hidraw (no extra packages)."""

    def __init__(self, path=None):
        self.path = path or self.find()
        self.fd = os.open(self.path, os.O_RDWR)

    @staticmethod
    def find():
        for dev in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
            uevent = Path(dev, "device", "uevent").read_text()
            if "HID_ID=0003:000009E8:00000054" in uevent.upper():
                return "/dev/" + Path(dev).name
        raise RuntimeError("no MPK Mini Plus found (VID 09E8, PID 0054). Is it connected "
                           "and in update mode? See docs/updater.md")

    def exchange(self, data, timeout=15.0):   # C1 erases ~120 sectors
        os.write(self.fd, b"\x00" + data)   # report ID 0 (the device uses none)
        import select
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            raise RuntimeError("timeout waiting for the device")
        return os.read(self.fd, 64)

    batch = 1

    def exchange_many(self, packets):
        return [self.exchange(p) for p in packets]

    def close(self):
        os.close(self.fd)


def verify(flash, image, stock):
    """Compare the simulated flash with what the update should leave."""
    expected = bytearray(image)
    expected[:PAYLOAD[0]] = stock[:PAYLOAD[0]]                        # never written over USB
    expected[UPDATABLE[1]:CONFIG[0]] = flash[UPDATABLE[1]:CONFIG[0]]  # ignored by C2
    diff = [a for a in range(0, FLASH_SIZE, 16) if flash[a:a + 16] != expected[a:a + 16]]
    for a in diff[:20]:
        print(f"  0x{FLASH_BASE + a:08X}: flash {flash[a:a + 16].hex(' ')}")
        print(f"  {'':10}  image {expected[a:a + 16].hex(' ')}")
    print("verify:", "flash matches the image" if not diff else f"{len(diff)} chunks differ")


def text_screen(rows):
    """OLED rows as text, two pixel rows per line."""
    out = []
    for y in range(0, len(rows) - 1, 2):
        out.append("".join({("#", "#"): "█", ("#", "."): "▀", (".", "#"): "▄"}.get(p, " ")
                           for p in zip(rows[y], rows[y + 1])).rstrip())
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load(path):
    return Path(path).read_bytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check", help="safety checks on an image")
    p.add_argument("image")
    for name in ("info", "flash"):
        p = sub.add_parser(name)
        if name == "flash":
            p.add_argument("image")
        target = p.add_mutually_exclusive_group(required=True)
        target.add_argument("--sim", action="store_true", help="the Renode simulator")
        target.add_argument("--hid", nargs="?", const="auto", metavar="DEVICE",
                            help="a real unit in update mode (/dev/hidrawN, default: find it)")
        if name == "flash":
            p.add_argument("--sim-start-image", metavar="IMAGE",
                           help="--sim: firmware the simulator starts from (default: stock)")
            p.add_argument("--yes", action="store_true", help="--hid: do not ask for confirmation")
    args = parser.parse_args()

    stock = load(STOCK)
    if args.cmd == "check":
        image = load(args.image)
        errors, warnings = check_image(image, stock)
        for w in warnings:
            print("warning:", w)
        for e in errors:
            print("ERROR:", e)
        print("OK" if not errors else "NOT SAFE TO FLASH", f"(firmware {version_of(image)}, "
              f"{len(write_plan(image))} packets)")
        sys.exit(1 if errors else 0)

    image = None
    if args.cmd == "flash":
        image = load(args.image)
        errors, warnings = check_image(image, stock)
        for w in warnings:
            print("warning:", w)
        if errors:
            for e in errors:
                print("ERROR:", e)
            sys.exit("refusing to flash an unsafe image")

    if args.sim:
        transport = SimTransport(image=getattr(args, "sim_start_image", None))
    else:
        transport = HidTransport(None if args.hid == "auto" else args.hid)
        if args.cmd == "flash" and not args.yes:
            answer = input(f"Flash {args.image} to the device on {transport.path}? [y/N] ")
            if answer.strip().lower() != "y":
                sys.exit("cancelled")
    try:
        updater = Updater(transport)
        if args.cmd == "info":
            print("bootloader reports firmware", updater.version())
        else:
            updater.flash(image)
            if args.sim:
                verify(transport.read_flash(), image, stock)
                print("\n".join(text_screen(transport.boot_screen())))
    finally:
        transport.close()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as e:
        sys.exit(f"error: {e}")
