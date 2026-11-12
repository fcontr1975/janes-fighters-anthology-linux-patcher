#!/usr/bin/env python3
"""Make Fighters Anthology's FA.EXE runnable under Wine on Linux.

The 1998 release was built for Windows 9x, where the kernel emulates the
privileged CLI/STI instructions for ring-3 code. Wine does not, so the game
dies with "Unhandled privileged instruction" the first time its timer code
disables interrupts. Patch those instructions out with NOPs.

The game's generic "Not enough memory" error can also mean it could not load
the .SMS data file matching the executable's name (FA.EXE needs FA.SMS).

The only executable changes made here are replacing those 27 privileged
instructions with NOPs.
"""

from __future__ import annotations

import argparse
import shutil
import struct
import sys
from pathlib import Path

IMAGE_BASE = 0x400000
TEXT_RVA = 0x1000
TEXT_RAW = 0x400

# timer routines that bracket critical sections with CLI/STI
CLI_SITES = (
    0x0046B590, 0x0046B600, 0x0046B6E6, 0x0046B728, 0x0046B748, 0x0046B76D,
    0x0046B76F, 0x0046B7BF, 0x0046B98F, 0x0046B9EB, 0x0046BA45, 0x0046BA81,
    0x0046BC21,
)
STI_SITES = (
    0x0046B5E3, 0x0046B657, 0x0046B712, 0x0046B740, 0x0046B75D, 0x0046B764,
    0x0046B76E, 0x0046B79E, 0x0046B7C0, 0x0046B9BB, 0x0046BA17, 0x0046BA71,
    0x0046BAAD, 0x0046BC4D,
)

NOP = 0x90
CLI = 0xFA
STI = 0xFB


class PatchError(Exception):
    pass


def va_to_offset(va: int) -> int:
    return va - IMAGE_BASE - TEXT_RVA + TEXT_RAW


def validate_pe(data: bytes) -> None:
    """Verify this is a well-formed 32-bit PE image."""
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise PatchError("not a DOS executable")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if pe_offset + 26 > len(data):
        raise PatchError("truncated PE header")
    if data[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise PatchError("not a PE executable")
    optional_header = pe_offset + 24
    magic = struct.unpack_from("<H", data, optional_header)[0]
    if magic != 0x10B:
        raise PatchError(f"expected a 32-bit PE image, got magic 0x{magic:04x}")


def patch(data: bytes) -> tuple[bytes, bool, int]:
    """Replace the known CLI/STI instructions with NOPs.

    Returns the patched image, whether it was already patched, and how many
    privileged instructions were replaced.
    """
    image = bytearray(data)
    validate_pe(image)

    replaced = 0
    already_patched = True
    for sites, original in ((CLI_SITES, CLI), (STI_SITES, STI)):
        for va in sites:
            offset = va_to_offset(va)
            byte = image[offset]
            if byte == original:
                image[offset] = NOP
                replaced += 1
                already_patched = False
            elif byte != NOP:
                raise PatchError(
                    f"unexpected byte 0x{byte:02x} at 0x{va:08x}; "
                    "this file is not the expected FA.EXE build"
                )

    return bytes(image), already_patched, replaced


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Patch FA.EXE so the game runs under Wine.")
    parser.add_argument(
        "executables", nargs="*", type=Path, default=None,
        help="executables to patch (default: FA.EXE beside this script)")
    parser.add_argument(
        "--no-backup", action="store_true",
        help="overwrite in place without keeping a .orig copy")
    args = parser.parse_args(argv)

    targets = args.executables or [Path(__file__).resolve().parent / "FA.EXE"]

    status = 0
    for target in targets:
        if not target.is_file():
            print(f"{target}: not found", file=sys.stderr)
            status = 1
            continue

        resource = target.with_suffix(".SMS")
        if not resource.is_file():
            print(
                f"{target}: warning: matching game data file {resource.name} "
                "is missing; the game may report a misleading "
                "'Not enough memory' error",
                file=sys.stderr,
            )

        original = target.read_bytes()
        try:
            patched, already_patched, replaced = patch(original)
        except PatchError as error:
            print(f"{target}: {error}", file=sys.stderr)
            status = 1
            continue

        if already_patched:
            print(f"{target}: already patched, nothing to do")
            continue

        if not args.no_backup:
            backup = target.with_suffix(target.suffix + ".orig")
            if not backup.exists():
                shutil.copy2(target, backup)
                print(f"{target}: backup written to {backup.name}")

        target.write_bytes(patched)
        print(f"{target}: patched {replaced} privileged instructions")

    return status


if __name__ == "__main__":
    raise SystemExit(main())
