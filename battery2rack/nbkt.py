"""Reader for Battery 4 kits (.nbkt).

Format (reverse engineered):
  - Native Instruments 'hsin'/'DSIN' container (same as Kontakt 5+).
  - A FastLZ level 2 compressed block holds the kit state:
      * 128 near fixed-size cells (8x16 grid) with UTF-16 names.
      * A Kontakt-style zone list (sample, key/velocity range, owning cell).
      * A file pool with paths relative to the .nbkt file.
"""
from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass, field


def fastlz_decompress(src: bytes) -> bytes:
    """FastLZ decompressor (levels 1 and 2; NI uses level 2)."""
    level = (src[0] >> 5) + 1
    ip, out, n = 1, bytearray(), len(src)
    ctrl = src[0] & 31
    while True:
        if ctrl >= 32:
            ln = (ctrl >> 5) - 1
            ofs = (ctrl & 31) << 8
            ref = len(out) - ofs - 1
            if ln == 6:
                if level == 1:
                    ln += src[ip]; ip += 1
                else:
                    while True:
                        c = src[ip]; ip += 1; ln += c
                        if c != 255:
                            break
            c = src[ip]; ip += 1
            ref -= c
            ln += 3
            if level == 2 and c == 255 and ofs == (31 << 8):
                ofs = (src[ip] << 8) | src[ip + 1]; ip += 2
                ref = len(out) - ofs - 8191 - 1
            if ref < 0:
                raise ValueError("FastLZ: back-reference out of range")
            dist = len(out) - ref
            if dist >= ln:
                out += out[ref:ref + ln]
            else:  # overlapping: the pattern repeats
                chunk = out[ref:]
                out += (chunk * (ln // dist + 1))[:ln]
        else:
            ctrl += 1
            out += src[ip:ip + ctrl]; ip += ctrl
        if ip >= n:
            break
        ctrl = src[ip]; ip += 1
    return bytes(out)


def extract_payload(raw: bytes) -> bytes:
    """Find the [u32 decompressed size][u32 compressed size][FastLZ...] block.

    The decompressed stream starts by repeating its own size, so the first
    FastLZ literal (4 bytes) matches the size field.
    """
    for o in range(0, min(len(raw) - 13, 0x4000)):
        if raw[o + 8] == 0x23 and raw[o + 9:o + 13] == raw[o:o + 4]:
            dec, comp = struct.unpack_from("<II", raw, o)
            if o + 8 + comp <= len(raw) and comp < dec:
                out = fastlz_decompress(raw[o + 8:o + 8 + comp])
                if len(out) == dec:
                    return out
    raise ValueError("Compressed kit block not found (is this a Battery 4 kit?)")


@dataclass
class Zone:
    index: int
    cell: int
    sample: int            # index into the file pool
    vel_lo: int
    vel_hi: int
    key_lo: int
    key_hi: int
    root_key: int
    start: int             # sample start frame
    sample_rate: int
    channels: int
    frames: int

    @property
    def pad_note(self) -> int:
        """MIDI note of the pad: the zone's 'own' key.

        Battery usually stretches the first cell downwards (0-36) and melodic
        cells upwards (51-127).
        """
        if self.key_lo == self.key_hi or self.key_lo == 0:
            return self.key_hi
        return self.key_lo


@dataclass
class Cell:
    index: int             # 0..127, row = index // 16, column = index % 16
    name: str
    zones: list[Zone] = field(default_factory=list)
    volume: float = 1.0    # linear gain (4.0 = +12 dB)
    pan: float = 0.0       # -1..1
    tune: float = 1.0      # pitch ratio (2.0 = +12 semitones)
    choke: int = -1        # -1 = none; 0..n = group (choke or bus? unconfirmed)


@dataclass
class Kit:
    path: str
    name: str
    cells: list[Cell]
    files: list[str]       # paths as stored in the kit (relative to the .nbkt)

    def resolve(self, i: int) -> str:
        p = self.files[i]
        if os.path.isabs(p):
            return p
        return os.path.normpath(os.path.join(os.path.dirname(self.path), p))


_CELL_MARK = bytes.fromhex("ffffffff000001000000000000000000ffffffff")
# Zone record: [u32 index][u32 length (0x4c old, 0x52 new)][u32 start][u32]
#                   [ffffffff][u16 vel_lo][u16 vel_hi][u16 key_lo][u16 key_hi]...
_ZONE_MARK = re.compile(
    rb"[\x4c\x52]\x00\x00\x00.{8}\xff\xff\xff\xff"
    rb"[\x00-\x7f]\x00[\x00-\x7f]\x00[\x00-\x7f]\x00[\x00-\x7f]\x00", re.S)
# Right before each zone: [u32 cell][01 xx 00 yy 00 00 00 ffffffff]
_ZONE_CELL = re.compile(rb"(.)\x00\x00\x00\x01[\x80-\xff]\x00[\x40-\x7f]\x00\x00\x00\xff\xff\xff\xff", re.S)


def _parse_cells(d: bytes) -> list[Cell]:
    cells = []
    for i, m in enumerate(re.finditer(re.escape(_CELL_MARK), d)):
        q = m.end()
        ln = struct.unpack_from("<I", d, q + 4)[0]
        e = q + 8 + 2 * ln  # main parameters right after the name
        vol, pan, tune = struct.unpack_from("<fff", d, e)
        choke = struct.unpack_from("<i", d, e + 0x16)[0]
        cells.append(Cell(i, d[q + 8:e].decode("utf-16le"), [], vol, pan, tune, choke))
    return cells


def _parse_zones(d: bytes) -> list[Zone]:
    zones = []
    for m in _ZONE_MARK.finditer(d):
        z = m.start() - 4
        idx, reclen, start = struct.unpack_from("<III", d, z)
        hdr = list(_ZONE_CELL.finditer(d, max(0, z - 140), z))
        if not hdr:
            continue
        cell = hdr[-1].group(1)[0]
        vl, vh, kl, kh = struct.unpack_from("<4H", d, z + 20)
        root = struct.unpack_from("<H", d, z + 36)[0]
        o = z + 50 + (reclen - 0x4C)
        smp, _bps, sr = struct.unpack_from("<III", d, o)
        ch = d[o + 12]
        frames = struct.unpack_from("<I", d, o + 13)[0]
        zones.append(Zone(idx, cell, smp, vl, vh, kl, kh, root, start, sr, ch, frames))
    return zones


def _parse_pool(d: bytes, nzones_hint: int) -> tuple[list[str], int]:
    """The pool follows the last zone: [u32 n] + n segmented paths.

    Segment type: 1 = root/volume, 2 = folder, 3 = '..', 4 = file.
    """
    def entry(o):
        n = struct.unpack_from("<I", d, o)[0]; o += 4
        if not 0 < n < 64:
            raise ValueError
        segs, absolute = [], False
        for _ in range(n):
            t = d[o]; o += 1
            if t in (1, 2, 4):
                ln = struct.unpack_from("<I", d, o)[0]; o += 4
                if ln > 1024:
                    raise ValueError
                s = d[o:o + 2 * ln].decode("utf-16le"); o += 2 * ln
                if t == 1:
                    absolute = True
                segs.append(s)
            elif t == 3:
                segs.append("..")
            else:
                raise ValueError(f"unknown path segment {t}")
        p = "/".join(segs)
        return ("/" + p if absolute else p), o

    # Find the first valid start after the last zone.
    for m in re.finditer(rb"[\x01-\x40]\x00\x00\x00[\x01-\x04]", d):
        o = m.start() - 4
        if o < 0:
            continue
        cnt = struct.unpack_from("<I", d, o)[0]
        if not 0 < cnt <= 4096:
            continue
        try:
            files, p = [], o + 4
            for _ in range(cnt):
                f, p = entry(p)
                files.append(f)
        except (ValueError, UnicodeDecodeError, struct.error):
            continue
        if files and all("." in f.rsplit("/", 1)[-1] for f in files):
            return files, o
    return [], -1


def read_kit(path: str) -> Kit:
    with open(path, "rb") as f:
        raw = f.read()
    d = extract_payload(raw)
    cells = _parse_cells(d)
    zones = _parse_zones(d)
    last_zone = max((m.start() for m in _ZONE_MARK.finditer(d)), default=0)
    files, _ = _parse_pool(d[last_zone:], len(zones))
    for z in zones:
        if z.cell < len(cells):
            cells[z.cell].zones.append(z)
    name = os.path.splitext(os.path.basename(path))[0]
    return Kit(path, name, cells, files)
