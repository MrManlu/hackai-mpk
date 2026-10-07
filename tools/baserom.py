#!/usr/bin/env python3
"""Find the reference stock firmware and copy it to baserom/firmware.bin.

SRC can be the raw firmware file, a directory, or the official Windows
updater (any archive 7z can open). Every candidate file is hashed and the
one matching config/baserom.sha256 is used.
"""

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HASH_FILE = ROOT / "config" / "baserom.sha256"
FLASH_SIZE = 256 * 1024


def reference():
    digest, name = HASH_FILE.read_text().split()
    return digest, ROOT / name


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidates(directory):
    for path in directory.rglob("*"):
        if path.is_file() and path.stat().st_size == FLASH_SIZE:
            yield path


def find_in(directory, digest):
    return next((p for p in candidates(directory) if sha256(p) == digest), None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("src", nargs="?", type=Path,
                        help="firmware file, directory or updater archive")
    parser.add_argument("--check", action="store_true",
                        help="only verify the existing baserom")
    args = parser.parse_args()
    digest, dest = reference()

    if args.check or args.src is None:
        if not dest.exists():
            sys.exit(f"missing {dest.relative_to(ROOT)}: run `make baserom SRC=...`")
        if sha256(dest) != digest:
            sys.exit(f"{dest.relative_to(ROOT)} does not match {HASH_FILE.name}")
        print(f"{dest.relative_to(ROOT)}: OK")
        return

    src = args.src
    if src.is_dir():
        found = find_in(src, digest)
    elif src.is_file() and sha256(src) == digest:
        found = src
    else:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(["7z", "x", "-y", f"-o{tmp}", str(src)],
                                    capture_output=True, text=True)
            if result.returncode != 0:
                sys.exit(f"7z could not extract {src}:\n{result.stderr}")
            found = find_in(Path(tmp), digest)
            if found:
                shutil.copyfile(found, dest)
                print(f"{found.name} (from {src.name}) -> {dest.relative_to(ROOT)}: OK")
                return

    if not found:
        sys.exit(f"no file matching {HASH_FILE.name} found in {src}")
    shutil.copyfile(found, dest)
    print(f"{found} -> {dest.relative_to(ROOT)}: OK")


if __name__ == "__main__":
    main()
