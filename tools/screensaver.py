#!/usr/bin/env python3
"""screensaver: replace the "AKAI Professional" screensaver bitmap.

    screensaver.py extract OUT.png              the bitmap of a firmware image as PNG
    screensaver.py preview IN.png               how IN.png will look on the OLED (text)
    screensaver.py patch IN.png OUT.bin         firmware image with IN.png as screensaver

The screensaver (FUN_08017d98) draws a 128 x 32 bitmap at 0x080248CC after
5 minutes without touching any control, then swaps it between normal and
inverted every 5 s. The factory display test (FUN_0801fe1a) uses the same
bitmap. Format (draw routine FUN_0801fd2e): two header bytes, width and
height, then one 32-bit column after another (4 bytes per column, least
significant bit = top pixel). See docs/screensaver.md.

The input image is converted to 128 x 32 black and white: scaled to fit
(keeping the aspect ratio, centred), then thresholded or dithered. White
pixels light up. Needs Pillow (Debian: python3-pil).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mpkflash  # noqa: E402

BITMAP = 0x248CC          # file offset of the header (address 0x080248CC)
WIDTH, HEIGHT = 128, 32
SIZE = WIDTH * HEIGHT // 8


def need_pillow():
    try:
        from PIL import Image
        return Image
    except ImportError:
        sys.exit("error: needs Pillow (Debian: sudo apt install python3-pil; pip: pillow)")


def read_bitmap(firmware):
    if firmware[BITMAP:BITMAP + 2] != bytes([WIDTH, HEIGHT]):
        raise RuntimeError(f"no {WIDTH}x{HEIGHT} bitmap header at 0x{0x08000000 + BITMAP:08X}: "
                           "is this a v1.13 image?")
    data = firmware[BITMAP + 2:BITMAP + 2 + SIZE]
    return [[(data[x * 4 + y // 8] >> (y % 8)) & 1 for x in range(WIDTH)] for y in range(HEIGHT)]


def encode(pixels):
    data = bytearray(SIZE)
    for y in range(HEIGHT):
        for x in range(WIDTH):
            if pixels[y][x]:
                data[x * 4 + y // 8] |= 1 << (y % 8)
    return bytes(data)


def load_image(path, threshold, dither, invert):
    Image = need_pillow()
    src = Image.open(path)
    if src.mode in ("RGBA", "LA", "P"):
        src = src.convert("RGBA")
        background = Image.new("RGBA", src.size, (0, 0, 0, 255))
        src = Image.alpha_composite(background, src)   # transparent = off
    src = src.convert("L")
    if src.size != (WIDTH, HEIGHT):
        scale = min(WIDTH / src.width, HEIGHT / src.height)
        size = (max(1, round(src.width * scale)), max(1, round(src.height * scale)))
        src = src.resize(size, Image.LANCZOS)
        canvas = Image.new("L", (WIDTH, HEIGHT), 0)
        canvas.paste(src, ((WIDTH - size[0]) // 2, (HEIGHT - size[1]) // 2))
        src = canvas
    if dither:
        bw = src.convert("1")                          # Floyd-Steinberg
    else:
        bw = src.point(lambda v: 255 if v >= threshold else 0).convert("1")
    pixels = [[1 if bw.getpixel((x, y)) else 0 for x in range(WIDTH)] for y in range(HEIGHT)]
    if invert:
        pixels = [[1 - p for p in row] for row in pixels]
    return pixels


def save_png(pixels, path, scale=1):
    Image = need_pillow()
    img = Image.new("1", (WIDTH, HEIGHT))
    for y in range(HEIGHT):
        for x in range(WIDTH):
            img.putpixel((x, y), pixels[y][x])
    if scale > 1:
        img = img.resize((WIDTH * scale, HEIGHT * scale), Image.NEAREST)
    img.save(path)


def text(pixels):
    out = []
    for y in range(0, HEIGHT, 2):
        out.append("".join({(1, 1): "█", (1, 0): "▀", (0, 1): "▄"}.get((a, b), " ")
                           for a, b in zip(pixels[y], pixels[y + 1])).rstrip())
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--firmware", default=str(mpkflash.STOCK),
                        help="firmware image to read or patch (default: baserom/firmware.bin)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("extract")
    p.add_argument("png")
    p.add_argument("--scale", type=int, default=1, help="enlarge the PNG (nearest neighbour)")
    for name in ("preview", "patch"):
        p = sub.add_parser(name)
        p.add_argument("png")
        if name == "patch":
            p.add_argument("out")
        p.add_argument("--threshold", type=int, default=128, help="0-255, brighter = lit")
        p.add_argument("--dither", action="store_true", help="Floyd-Steinberg instead of a threshold")
        p.add_argument("--invert", action="store_true", help="dark pixels light up")
    args = parser.parse_args()

    firmware = Path(args.firmware).read_bytes()
    if args.cmd == "extract":
        save_png(read_bitmap(firmware), args.png, args.scale)
        print(f"wrote {args.png}")
        return

    pixels = load_image(args.png, args.threshold, args.dither, args.invert)
    print(text(pixels))
    lit = sum(map(sum, pixels))
    print(f"{lit} of {WIDTH * HEIGHT} pixels lit")
    if args.cmd == "preview":
        return

    read_bitmap(firmware)                    # checks the header
    patched = bytearray(firmware)
    patched[BITMAP + 2:BITMAP + 2 + SIZE] = encode(pixels)
    errors, warnings = mpkflash.check_image(bytes(patched), Path(mpkflash.STOCK).read_bytes())
    for w in warnings:
        print("warning:", w)
    if errors:
        for e in errors:
            print("ERROR:", e)
        sys.exit("the patched image is not safe to flash")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_bytes(patched)
    print(f"wrote {args.out} (passes the mpkflash checks)")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as e:
        sys.exit(f"error: {e}")
