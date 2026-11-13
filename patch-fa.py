#!/usr/bin/env python3
"""All-in-one patcher for Jane's Fighters Anthology (FA.EXE, 1998 release).

Run on the retail FA.EXE (or on one already patched by an earlier version of
this script) and it applies, in place and keeping a .orig backup:

1. Wine compatibility.  The game was built for Windows 9x, which emulates the
   privileged CLI/STI instructions for ring-3 code; Wine does not, so the game
   dies with "Unhandled privileged instruction" in its timer code.  The 27
   known CLI/STI instructions are replaced with NOPs.

2. HD video modes.  The two largest legacy modes in the Pref > Screen
   resolution menu are replaced:
       800x600x256   -> 1280x720x256   (720p)
       1024x768x256  -> 1920x1080x256  (1080p)
   640x480 is kept as the default and fall-back mode.  This covers DirectDraw
   mode enumeration and refresh-rate matching, DirectDraw dimensions and the
   game's internal screen dimensions.

3. Renderer fixes needed above 1024 columns / 1036 rows:
   - Span loops with 8-bit counters.  The Gouraud span filler (horizon haze
     gradient) and three affine texture span fillers divide the span length by
     four and loop on `dec cl`, so only `length mod 1024` pixels were written,
     leaving everything right of x = width - 1024 unpainted (black gap /
     hall-of-mirrors trails).  The loops now count with CX.  In every patched
     loop the low word of ECX is otherwise unused (the high word is a 16.16
     accumulator whose step values have a zero low word).
   - Dirty-scanline table overflow.  The per-scanline table at 0x510288 only
     has room for 1036 rows before it runs into texture-mapper state.  All 47
     relocation-backed references move to a new zero-filled section .fadirty.

4. Resolution menu.  The menu text lives in CHOOSEM.MNU inside FA_2.LIB.  A
   small position-independent routine in a new code section (.fahd) runs when
   a menu file is loaded and, only if it finds the stock four entries, rewrites
   them in place as: (blank), "640 x 480", "1280 x 720", "1920 x 1080".  The
   blank entry (formerly 320x200) is always greyed out.  No game data files
   are modified.

5. Focus-loss (alt-tab / notification) recovery.  When the game loses focus,
   DirectDraw minimizes its exclusive full-screen window and the game
   suspends its worker threads.  Two things then went wrong:
   - In a mission the WM_ACTIVATEAPP handler called ExitProcess() instead of
     suspending; that branch is bypassed.
   - The handler only resumes if GetForegroundWindow() is already the game
     window when WM_ACTIVATEAPP arrives.  Under Wine (and whenever the window
     is re-activated while still minimized) it is not, so the game stayed
     suspended forever: black screen, sound still playing, no input.
   A small routine in a new code section (.fafocus) now also handles
   WM_ACTIVATE: if the window is activated while minimized it is restored,
   and if the game is still suspended it runs the game's own resume path
   (restore surfaces, redraw, resume threads) after the default handling.

Every original byte is verified before it is changed, and the result must
match a known SHA-256 or nothing is written.  Running it again on a patched
executable does nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import struct
import sys
from pathlib import Path

IMAGE_BASE = 0x400000
FILE_ALIGNMENT = 0x200
SECTION_ALIGNMENT = 0x1000

RETAIL_SHA256 = "d1bc58d59be68bc538b9ebd9842e78797697824a4aa243449e56679d6d49cf7b"
WINE_ONLY_SHA256 = "849a53223a847a460dfdb5fd6185c879efd79e38ece7500db88e1d6767dde30b"
PATCHED_SHA256 = "fb3fb5b8099c980db7ece042626f855f80cfff6d618b4417bf50a83f5dfd0bf0"

# --- 1. Wine: timer routines that bracket critical sections with CLI/STI ---
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
NOP, CLI, STI = 0x90, 0xFA, 0xFB

# --- 2. Video modes: (VA, original bytes, new bytes, description) ---
MODE_720_PATCHES = (
    (0x41DAC4, "3d20030000", "3d00050000", "refresh lookup width 800 -> 1280"),
    (0x41E1AB, "3d20030000", "3d00050000", "mode enum width 800 -> 1280"),
    (0x41E1B2, "81f958020000", "81f9d0020000", "mode enum height 600 -> 720"),
    (0x41E1F4, "3d20030000", "3d00050000", "refresh record width 800 -> 1280"),
    (0x45DC38, "6858020000", "68d0020000", "DirectDraw height 600 -> 720"),
    (0x45DC3D, "6820030000", "6800050000", "DirectDraw width 800 -> 1280"),
    (0x45DD89, "66c7056ac055002003", "66c7056ac055000005", "screen width 800 -> 1280"),
    (0x45DD92, "66c7056cc055005802", "66c7056cc05500d002", "screen height 600 -> 720"),
)
MODE_1080_PATCHES = (
    (0x41DACB, "3d00040000", "3d80070000", "refresh lookup width 1024 -> 1920"),
    (0x41E1C1, "3d00040000", "3d80070000", "mode enum width 1024 -> 1920"),
    (0x41E1C8, "81f900030000", "81f938040000", "mode enum height 768 -> 1080"),
    (0x41E1FB, "3d00040000", "3d80070000", "refresh record width 1024 -> 1920"),
    (0x45DC46, "6800030000", "6838040000", "DirectDraw height 768 -> 1080"),
    (0x45DC4B, "6800040000", "6880070000", "DirectDraw width 1024 -> 1920"),
    (0x45DDCA, "66c7056ac055000004", "66c7056ac055008007", "screen width 1024 -> 1920"),
    (0x45DDD3, "66c7056cc055000003", "66c7056cc055003804", "screen height 768 -> 1080"),
)

# --- 3. Renderer span loops ---
SPAN_PATCHES = (
    # Gouraud span filler (0x4C77D0): mov cx,[len]; sar cx,2; ... dec cl
    (0x4C7C3C, "fec9", "6649", "Gouraud span: dec cl -> dec cx"),
    # Affine texture span fillers: shr eax,2; mov cl,al; ... dec cl
    (0x4C9D6B, "8ac8", "0bc8", "texture span A: mov cl,al -> or ecx,eax"),
    (0x4C9DD1, "fec9", "6649", "texture span A: dec cl -> dec cx"),
    (0x4CA67F, "8ac8", "0bc8", "texture span B: mov cl,al -> or ecx,eax"),
    (0x4CA6E5, "fec9", "6649", "texture span B: dec cl -> dec cx"),
    (0x4CABAD, "8ac8", "0bc8", "texture span C: mov cl,al -> or ecx,eax"),
    (0x4CAC13, "fec9", "6649", "texture span C: dec cl -> dec cx"),
)

# --- 5. Focus loss: WM_ACTIVATEAPP takes the suspend path instead of
# ExitProcess() when the game state is nonzero (in a mission).
FOCUS_LOSS_PATCHES = (
    (0x476385, "740d", "eb0d", "bypass ExitProcess on deactivation"),
)

# WM_ACTIVATE recovery routine (section .fafocus), entered by a jmp that
# replaces `cmp esi,2; je 0x476270` in the window procedure's message switch
# (esi = message, ebp = window procedure frame).  Data and imports are
# addressed relative to the call/pop anchor and branches are rel32, so it is
# position independent.  ebx is saved/restored by the window procedure.
# Assembled with GNU as --32 (Intel syntax) at 0x5AE000.
FOCUS_SECTION_VA = 0x5AE000
FOCUS_HOOK_VA = 0x4761AC
FOCUS_HOOK_ORIGINAL = "83fe020f84bb000000"  # cmp esi,2; je 0x476270
FOCUS_STUB_CODE = bytes.fromhex("".join((
    "83fe02"                # 000  cmp esi,0x2                 WM_DESTROY
    "0f846782ecff"          # 003  je 0x476270                 (original case)
    "83fe06"                # 009  cmp esi,0x6                 WM_ACTIVATE
    "0f854682ecff"          # 00c  jne 0x476258                DefWindowProcA
    "e800000000"            # 012  call 17
    "5b"                    # 017  pop ebx                     anchor
    "8b4510"                # 018  mov eax,[ebp+0x10]          wParam
    "6685c0"                # 01b  test ax,ax                  WA_INACTIVE?
    "0f843482ecff"          # 01e  je 0x476258
    "c1e810"                # 024  shr eax,0x10                minimized?
    "740b"                  # 027  je 34
    "6a09"                  # 029  push 0x9                    SW_RESTORE
    "ff7508"                # 02b  push [ebp+0x8]              hwnd
    "ff93cd56feff"          # 02e  call [ebx-0x1a933]          ShowWindow
    "83bbd59ef4ff00"        # 034  cmp [ebx-0xb612b],0         suspended flag
    "0f841782ecff"          # 03b  je 0x476258                 (ds:0x4F7EEC)
    "ff7514"                # 041  push [ebp+0x14]
    "ff7510"                # 044  push [ebp+0x10]
    "56"                    # 047  push esi
    "ff7508"                # 048  push [ebp+0x8]
    "ff93fd56feff"          # 04b  call [ebx-0x1a903]          DefWindowProcA
    "be01000000"            # 051  mov esi,0x1                 "activated"
    "e97a82ecff"            # 056  jmp 0x4762d5                game's resume path
)))
FOCUS_STUB_ANCHOR = 0x017
FOCUS_STUB_BRANCHES = (     # (offset of rel32, target VA)
    (0x005, 0x476270), (0x00E, 0x476258), (0x020, 0x476258),
    (0x03D, 0x476258), (0x057, 0x4762D5),
)
FOCUS_STUB_DATA = (         # (offset of disp32, target VA)
    (0x030, 0x5936E4),      # IAT: USER32!ShowWindow
    (0x036, 0x4F7EEC),      # WM_ACTIVATEAPP "suspended / restore needed" flag
    (0x04D, 0x593714),      # IAT: USER32!DefWindowProcA
)

# Dirty-scanline table relocation
OLD_DIRTY = 0x510288
NEW_DIRTY = 0x5AC000
DIRTY_SECTION_SIZE = 0x1000
EXPECTED_DIRTY_REFERENCES = 47

# Mode name strings (_grMode label; informational only)
LABEL_1024_VA = 0x4F6C50
OLD_LABEL_1024 = b"1024x768x256\0\0\0\0"
NEW_LABEL_1024 = b"1920x1080x256\0\0\0"
MODE_800_STR_PTR_VA = 0x4F6C98   # ?MODE_800x600x256_STR, points at 0x4F6C60
OLD_LABEL_800_VA = 0x4F6C60
OLD_LABEL_800 = b"800x600x256\0"

# --- 4. Resolution menu ---
HD_SECTION_VA = 0x5AD000
MENU_HOOK_VA = 0x40BDB1          # MenuStartUp, after firstMenu = RMAccess(...)
MENU_HOOK_ORIGINAL = "8b44243c83f8ff"   # mov eax,[esp+0x3c]; cmp eax,-1
MENU_GREY_PATCH = (
    0x4A0FF3, "7407", "eb07", "always grey out the blank (ex-320x200) entry")

# Packed menu items: next(4) submenu(4) rect(8) flags(2) mark(1) text...
MENU_ITEM_HEADER = 0x13
MENU_OLD_TEXT = (b"320 x 200", b"640 x 480", b"800 x 600", b"1024 x 768")
MENU_NEW_TEXT = (b"", b"640 x 480", b"1280 x 720", b"1920 x 1080")
LABEL_720 = b"1280x720x256"

# Position-independent stub, called from MENU_HOOK_VA with eax = firstMenu.
# It walks every menu -> item -> submenu and, for a submenu whose first four
# items are exactly the packed stock resolution entries, rewrites them in
# place (the new layout is 7 bytes shorter, so it never grows).  It then
# performs the two replaced instructions and returns; all other registers and
# EFLAGS.DF are preserved.  Assembled with GNU as --32 (Intel syntax).
MENU_STUB_CODE = bytes.fromhex("".join((
    "9c"                    # 000  pushf
    "60"                    # 001  pusha
    "e800000000"            # 002  call 7
    "5d"                    # 007  pop ebp
    "89c7"                  # 008  mov edi,eax
    "85ff"                  # 00a  test edi,edi
    "7422"                  # 00c  je 30
    "8b7704"                # 00e  mov esi,DWORD PTR [edi+0x4]
    "85f6"                  # 011  test esi,esi
    "7417"                  # 013  je 2c
    "8b5e04"                # 015  mov ebx,DWORD PTR [esi+0x4]
    "85db"                  # 018  test ebx,ebx
    "740c"                  # 01a  je 28
    "8b5b04"                # 01c  mov ebx,DWORD PTR [ebx+0x4]
    "85db"                  # 01f  test ebx,ebx
    "7405"                  # 021  je 28
    "e812000000"            # 023  call 3a
    "8b36"                  # 028  mov esi,DWORD PTR [esi]
    "ebe5"                  # 02a  jmp 11
    "8b3f"                  # 02c  mov edi,DWORD PTR [edi]
    "ebda"                  # 02e  jmp a
    "61"                    # 030  popa
    "9d"                    # 031  popf
    "8b442440"              # 032  mov eax,DWORD PTR [esp+0x40]
    "83f8ff"                # 036  cmp eax,0xffffffff
    "c3"                    # 039  ret
    "56"                    # 03a  push esi
    "57"                    # 03b  push edi
    "8d95e9000000"          # 03c  lea edx,[ebp+0xe9]
    "31c9"                  # 042  xor ecx,ecx
    "8b04ca"                # 044  mov eax,DWORD PTR [edx+ecx*8]
    "8d3c03"                # 047  lea edi,[ebx+eax*1]
    "8b44ca08"              # 04a  mov eax,DWORD PTR [edx+ecx*8+0x8]
    "85c0"                  # 04e  test eax,eax
    "7402"                  # 050  je 54
    "01d8"                  # 052  add eax,ebx
    "3907"                  # 054  cmp DWORD PTR [edi],eax
    "0f8590000000"          # 056  jne ec
    "837f0400"              # 05c  cmp DWORD PTR [edi+0x4],0x0
    "0f8586000000"          # 060  jne ec
    "51"                    # 066  push ecx
    "8db539010000"          # 067  lea esi,[ebp+0x139]
    "8b44ca04"              # 06d  mov eax,DWORD PTR [edx+ecx*8+0x4]
    "01c6"                  # 071  add esi,eax
    "83c713"                # 073  add edi,0x13
    "8a06"                  # 076  mov al,BYTE PTR [esi]
    "3a07"                  # 078  cmp al,BYTE PTR [edi]
    "7506"                  # 07a  jne 82
    "46"                    # 07c  inc esi
    "47"                    # 07d  inc edi
    "84c0"                  # 07e  test al,al
    "75f4"                  # 080  jne 76
    "59"                    # 082  pop ecx
    "7567"                  # 083  jne ec
    "41"                    # 085  inc ecx
    "83f904"                # 086  cmp ecx,0x4
    "72b9"                  # 089  jb 44
    "fc"                    # 08b  cld
    "31c9"                  # 08c  xor ecx,ecx
    "51"                    # 08e  push ecx
    "8d9511010000"          # 08f  lea edx,[ebp+0x111]
    "8b04ca"                # 095  mov eax,DWORD PTR [edx+ecx*8]
    "8d3c03"                # 098  lea edi,[ebx+eax*1]
    "8d95e9000000"          # 09b  lea edx,[ebp+0xe9]
    "8b04ca"                # 0a1  mov eax,DWORD PTR [edx+ecx*8]
    "8d3403"                # 0a4  lea esi,[ebx+eax*1]
    "57"                    # 0a7  push edi
    "b913000000"            # 0a8  mov ecx,0x13
    "f3a4"                  # 0ad  rep movs BYTE PTR es:[edi],BYTE PTR ds:[esi]
    "8b4c2404"              # 0af  mov ecx,DWORD PTR [esp+0x4]
    "8d9511010000"          # 0b3  lea edx,[ebp+0x111]
    "8db562010000"          # 0b9  lea esi,[ebp+0x162]
    "0374ca04"              # 0bf  add esi,DWORD PTR [edx+ecx*8+0x4]
    "ac"                    # 0c3  lods al,BYTE PTR ds:[esi]
    "aa"                    # 0c4  stos BYTE PTR es:[edi],al
    "84c0"                  # 0c5  test al,al
    "75fa"                  # 0c7  jne c3
    "5f"                    # 0c9  pop edi
    "8b44ca08"              # 0ca  mov eax,DWORD PTR [edx+ecx*8+0x8]
    "85c0"                  # 0ce  test eax,eax
    "7402"                  # 0d0  je d4
    "01d8"                  # 0d2  add eax,ebx
    "8907"                  # 0d4  mov DWORD PTR [edi],eax
    "59"                    # 0d6  pop ecx
    "41"                    # 0d7  inc ecx
    "83f904"                # 0d8  cmp ecx,0x4
    "72b1"                  # 0db  jb 8e
    "8dbb6e000000"          # 0dd  lea edi,[ebx+0x6e]
    "b907000000"            # 0e3  mov ecx,0x7
    "31c0"                  # 0e8  xor eax,eax
    "f3aa"                  # 0ea  rep stos BYTE PTR es:[edi],al
    "5f"                    # 0ec  pop edi
    "5e"                    # 0ed  pop esi
    "c3"                    # 0ee  ret
    "90"                    # 0ef  nop
)))
STUB_ANCHOR = 0x007               # address popped into ebp
STUB_TABLE = 0x0F0                # (old item offset, old text offset) * 4, 0
STUB_NEW_TABLE = 0x118            # (new item offset, new text offset) * 4, 0
STUB_OLD_TEXT = 0x140
STUB_NEW_TEXT = 0x169
STUB_LABEL_720 = 0x18B


class PatchError(Exception):
    pass


class Image:
    def __init__(self, data: bytes) -> None:
        self.data = bytearray(data)
        d = self.data
        if len(d) < 0x40 or d[:2] != b"MZ":
            raise PatchError("not a DOS executable")
        self.pe = struct.unpack_from("<I", d, 0x3C)[0]
        if self.pe + 0x18 > len(d) or d[self.pe:self.pe + 4] != b"PE\0\0":
            raise PatchError("not a PE executable")
        self.opt = self.pe + 24
        if self.u16(self.opt) != 0x10B:
            raise PatchError("not a 32-bit PE image")
        if self.u32(self.opt + 28) != IMAGE_BASE:
            raise PatchError("unexpected image base")
        if (self.u32(self.opt + 32) != SECTION_ALIGNMENT
                or self.u32(self.opt + 36) != FILE_ALIGNMENT):
            raise PatchError("unexpected section or file alignment")
        self.sections_start = self.opt + self.u16(self.pe + 20)

    def u16(self, offset: int) -> int:
        return struct.unpack_from("<H", self.data, offset)[0]

    def u32(self, offset: int) -> int:
        return struct.unpack_from("<I", self.data, offset)[0]

    @property
    def section_count(self) -> int:
        return self.u16(self.pe + 6)

    def sections(self):
        for i in range(self.section_count):
            header = self.sections_start + i * 40
            name = bytes(self.data[header:header + 8]).rstrip(b"\0").decode("latin1")
            vsize, rva, raw_size, raw_offset = struct.unpack_from(
                "<IIII", self.data, header + 8)
            yield name, vsize, rva, raw_size, raw_offset

    def rva_to_offset(self, rva: int, length: int = 1) -> int:
        for _name, _vsize, start, raw_size, raw_offset in self.sections():
            if start <= rva and rva + length <= start + raw_size:
                return raw_offset + rva - start
        raise PatchError(f"RVA {rva:#x} is not backed by file data")

    def va_to_offset(self, va: int, length: int = 1) -> int:
        return self.rva_to_offset(va - IMAGE_BASE, length)

    def replace(self, va: int, old: bytes, new: bytes, description: str) -> bool:
        """Swap old for new at va; return True if changed, False if already new."""
        offset = self.va_to_offset(va, len(old))
        current = bytes(self.data[offset:offset + len(old)])
        if current == new:
            return False
        if current != old:
            raise PatchError(
                f"unexpected bytes at 0x{va:08x} ({description}); "
                "this file is not the expected FA.EXE build")
        self.data[offset:offset + len(old)] = new
        return True

    def add_section(self, name: bytes, vsize: int, rva: int, raw: bytes,
                    characteristics: int) -> None:
        count = self.section_count
        header = self.sections_start + count * 40
        if header + 40 > self.u32(self.opt + 60):
            raise PatchError("no space for another section header")
        if any(self.data[header:header + 40]):
            raise PatchError("section header space is not empty")
        if rva != self.u32(self.opt + 56):
            raise PatchError("new section does not follow the image")
        raw_offset = 0
        if raw:
            raw_offset = len(self.data)
            if raw_offset % FILE_ALIGNMENT:
                raise PatchError("file size is not aligned")
            padded = raw + bytes(-len(raw) % FILE_ALIGNMENT)
            self.data += padded
        struct.pack_into(
            "<8sIIIIIIHHI", self.data, header, name, vsize, rva,
            len(raw) + (-len(raw) % FILE_ALIGNMENT) if raw else 0,
            raw_offset, 0, 0, 0, 0, characteristics)
        struct.pack_into("<H", self.data, self.pe + 6, count + 1)
        size = vsize + (-vsize % SECTION_ALIGNMENT)
        struct.pack_into("<I", self.data, self.opt + 56, rva + size)

    def absolute_references(self, start: int, end: int) -> list[tuple[int, int]]:
        """File offsets of HIGHLOW relocations whose target is in [start, end)."""
        reloc_rva, reloc_size = struct.unpack_from("<II", self.data, self.opt + 96 + 5 * 8)
        cursor = self.rva_to_offset(reloc_rva, reloc_size)
        stop = cursor + reloc_size
        found = []
        while cursor < stop:
            page, block_size = struct.unpack_from("<II", self.data, cursor)
            if block_size == 0:
                break
            if block_size < 8 or block_size % 2 or cursor + block_size > stop:
                raise PatchError("invalid relocation block")
            for entry_offset in range(cursor + 8, cursor + block_size, 2):
                entry = self.u16(entry_offset)
                if entry >> 12 != 3:
                    continue
                location = self.rva_to_offset(page + (entry & 0xFFF), 4)
                target = self.u32(location)
                if start <= target < end:
                    found.append((location, target))
            cursor += block_size
        return found


def build_menu_stub() -> bytes:
    def table(offsets, texts):
        entries, text_offset = [], 0
        for item_offset, text in zip(offsets, texts):
            entries.append(struct.pack("<II", item_offset, text_offset))
            text_offset += len(text) + 1
        return b"".join(entries) + struct.pack("<II", 0, 0)

    def packed_offsets(texts):
        offsets, position = [], 0
        for text in texts:
            offsets.append(position)
            position += MENU_ITEM_HEADER + len(text) + 1
        return offsets, position

    old_offsets, old_end = packed_offsets(MENU_OLD_TEXT)
    new_offsets, new_end = packed_offsets(MENU_NEW_TEXT)
    stub = bytearray(MENU_STUB_CODE)
    stub += bytes(-len(stub) % 4)
    layout = (
        (STUB_TABLE, table(old_offsets, MENU_OLD_TEXT)),
        (STUB_NEW_TABLE, table(new_offsets, MENU_NEW_TEXT)),
        (STUB_OLD_TEXT, b"".join(t + b"\0" for t in MENU_OLD_TEXT)),
        (STUB_NEW_TEXT, b"".join(t + b"\0" for t in MENU_NEW_TEXT)),
        (STUB_LABEL_720, LABEL_720 + b"\0"),
    )
    for offset, blob in layout:
        if len(stub) != offset:
            raise PatchError("internal error: menu stub layout mismatch")
        stub += blob
    # constants baked into the code: lea edi,[ebx+NEW_END]; mov ecx,OLD_END-NEW_END
    if (stub[0xDF:0xE3] != struct.pack("<I", new_end)
            or stub[0xE4:0xE8] != struct.pack("<I", old_end - new_end)):
        raise PatchError("internal error: menu stub constants mismatch")
    return bytes(stub)


def build_focus_stub() -> bytes:
    """Return FOCUS_STUB_CODE after checking its baked-in branch/data targets."""
    stub = FOCUS_STUB_CODE
    for offset, target in FOCUS_STUB_BRANCHES:
        if FOCUS_SECTION_VA + offset + 4 + struct.unpack_from("<i", stub, offset)[0] != target:
            raise PatchError("internal error: focus stub branch mismatch")
    for offset, target in FOCUS_STUB_DATA:
        if (FOCUS_SECTION_VA + FOCUS_STUB_ANCHOR
                + struct.unpack_from("<i", stub, offset)[0] != target):
            raise PatchError("internal error: focus stub data reference mismatch")
    return stub


def patch(data: bytes) -> tuple[bytes, list[str]]:
    """Return the fully patched image and a list of the steps applied."""
    image = Image(data)
    applied: list[str] = []

    # 1. Wine CLI/STI
    replaced = 0
    for sites, original in ((CLI_SITES, CLI), (STI_SITES, STI)):
        for va in sites:
            if image.replace(va, bytes([original]), bytes([NOP]), "CLI/STI"):
                replaced += 1
    if replaced:
        applied.append(f"Wine: replaced {replaced} privileged CLI/STI instructions")

    # 2./3. code patches
    groups = (
        ("720p mode (replaces 800x600)", MODE_720_PATCHES),
        ("1080p mode (replaces 1024x768)", MODE_1080_PATCHES),
        ("renderer span-length fixes", SPAN_PATCHES),
        ("focus-loss ExitProcess bypass", FOCUS_LOSS_PATCHES),
        ("resolution menu greying", (MENU_GREY_PATCH,)),
    )
    for title, patches in groups:
        changed = sum(
            image.replace(va, bytes.fromhex(old), bytes.fromhex(new), desc)
            for va, old, new, desc in patches)
        if changed:
            applied.append(f"{title}: {changed} change(s)")

    if image.replace(LABEL_1024_VA, OLD_LABEL_1024, NEW_LABEL_1024, "1024 mode label"):
        applied.append("1080p mode label")

    # dirty-scanline table
    names = [name for name, *_ in image.sections()]
    if names[:6] != [".text", ".rdata", ".data", ".idata", ".rsrc", ".reloc"]:
        raise PatchError("unexpected PE section layout")
    extra = names[6:]
    if extra not in ([], [".fadirty"], [".fadirty", ".fahd"],
                     [".fadirty", ".fahd", ".fafocus"]):
        raise PatchError(f"unexpected extra PE sections {extra}; "
                         "this is not a file produced by this patcher")
    if not extra:
        if image.u32(image.opt + 56) != NEW_DIRTY - IMAGE_BASE:
            raise PatchError("unexpected image size")
        references = image.absolute_references(OLD_DIRTY, OLD_DIRTY + 0x400)
        if len(references) != EXPECTED_DIRTY_REFERENCES:
            raise PatchError(f"expected {EXPECTED_DIRTY_REFERENCES} dirty-table "
                             f"references, found {len(references)}")
        if {target for _, target in references} != {OLD_DIRTY, OLD_DIRTY + 1}:
            raise PatchError("unexpected dirty-table offsets")
        for location, target in references:
            struct.pack_into("<I", image.data, location, NEW_DIRTY + target - OLD_DIRTY)
        # uninitialized (zero-filled), readable and writable data
        image.add_section(b".fadirty", DIRTY_SECTION_SIZE, NEW_DIRTY - IMAGE_BASE,
                          b"", 0xC0000080)
        struct.pack_into("<I", image.data, image.opt + 12,
                         image.u32(image.opt + 12) + DIRTY_SECTION_SIZE)
        applied.append(f"relocated {len(references)} dirty-scanline table references")
    elif (len(image.absolute_references(OLD_DIRTY, OLD_DIRTY + 0x400)) != 0
          or len(image.absolute_references(NEW_DIRTY, NEW_DIRTY + 2))
          != EXPECTED_DIRTY_REFERENCES):
        raise PatchError("dirty-scanline table is only partially relocated")

    # resolution menu stub
    stub = build_menu_stub()
    if ".fahd" not in extra:
        image.add_section(b".fahd", len(stub), HD_SECTION_VA - IMAGE_BASE, stub,
                          0x60000020)  # code, execute, read
        struct.pack_into("<I", image.data, image.opt + 4,
                         image.u32(image.opt + 4) + len(stub) + (-len(stub) % FILE_ALIGNMENT))
        applied.append("added resolution menu routine")
    else:
        offset = image.va_to_offset(HD_SECTION_VA, len(stub))
        if image.data[offset:offset + len(stub)] != stub:
            raise PatchError("unexpected contents in the .fahd section")

    call = HD_SECTION_VA - (MENU_HOOK_VA + 5)
    hook = b"\xe8" + struct.pack("<i", call) + b"\x90\x90"
    if image.replace(MENU_HOOK_VA, bytes.fromhex(MENU_HOOK_ORIGINAL), hook,
                     "resolution menu hook"):
        applied.append("hooked resolution menu loading")

    label = struct.pack("<I", HD_SECTION_VA + STUB_LABEL_720)
    old_label_offset = image.va_to_offset(OLD_LABEL_800_VA, len(OLD_LABEL_800))
    if image.data[old_label_offset:old_label_offset + len(OLD_LABEL_800)] != OLD_LABEL_800:
        raise PatchError("unexpected 800x600 mode label")
    if image.replace(MODE_800_STR_PTR_VA, struct.pack("<I", OLD_LABEL_800_VA), label,
                     "800 mode label pointer"):
        applied.append("720p mode label")

    # focus-loss recovery routine
    focus_stub = build_focus_stub()
    if ".fafocus" not in extra:
        image.add_section(b".fafocus", len(focus_stub), FOCUS_SECTION_VA - IMAGE_BASE,
                          focus_stub, 0x60000020)  # code, execute, read
        struct.pack_into("<I", image.data, image.opt + 4,
                         image.u32(image.opt + 4) + len(focus_stub)
                         + (-len(focus_stub) % FILE_ALIGNMENT))
        applied.append("added focus-loss recovery routine")
    else:
        offset = image.va_to_offset(FOCUS_SECTION_VA, len(focus_stub))
        if image.data[offset:offset + len(focus_stub)] != focus_stub:
            raise PatchError("unexpected contents in the .fafocus section")

    jump = FOCUS_SECTION_VA - (FOCUS_HOOK_VA + 5)
    hook = b"\xe9" + struct.pack("<i", jump) + b"\x90" * 4
    if image.replace(FOCUS_HOOK_VA, bytes.fromhex(FOCUS_HOOK_ORIGINAL), hook,
                     "WM_ACTIVATE recovery hook"):
        applied.append("hooked WM_ACTIVATE for focus-loss recovery")

    return bytes(image.data), applied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Patch FA.EXE for Wine, focus-loss (alt-tab) recovery and "
                    "720p/1080p video modes.")
    parser.add_argument(
        "executables", nargs="*", type=Path, default=None,
        help="executables to patch in place (default: FA.EXE beside this script)")
    parser.add_argument(
        "--no-backup", action="store_true",
        help="overwrite in place without keeping a .orig copy")
    parser.add_argument(
        "--check", action="store_true",
        help="only report whether the executables are patched; change nothing")
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
        if hashlib.sha256(original).hexdigest() == PATCHED_SHA256:
            print(f"{target}: already patched, nothing to do")
            continue

        try:
            patched, applied = patch(original)
        except PatchError as error:
            print(f"{target}: {error}", file=sys.stderr)
            status = 1
            continue

        digest = hashlib.sha256(patched).hexdigest()
        if digest != PATCHED_SHA256:
            print(f"{target}: patched result has unexpected SHA-256 {digest}; "
                  "refusing to write it", file=sys.stderr)
            status = 1
            continue

        if args.check:
            print(f"{target}: not fully patched; would apply: " + "; ".join(applied))
            status = 1
            continue

        if not args.no_backup:
            backup = target.with_suffix(target.suffix + ".orig")
            if not backup.exists():
                shutil.copy2(target, backup)
                print(f"{target}: backup written to {backup.name}")

        target.write_bytes(patched)
        for step in applied:
            print(f"{target}: {step}")
        print(f"{target}: patched (Wine + focus-loss recovery + 720p/1080p)")

    return status


if __name__ == "__main__":
    raise SystemExit(main())
