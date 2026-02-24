"""Atari 8-bit .xex (binary load file) loader.

Format: one or more segments, each with start/end address and data.
First segment must begin with $FFFF header.
Special addresses: $02E0 = RUN vector, $02E2 = INIT vector.
"""

import struct
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class XexSegment:
    start: int
    end: int
    data: bytes


@dataclass
class XexFile:
    segments: List[XexSegment] = field(default_factory=list)
    run_addr: Optional[int] = None
    init_addrs: List[int] = field(default_factory=list)


def load_xex(path: str) -> XexFile:
    """Parse .xex file, return segments and run address."""
    with open(path, 'rb') as f:
        data = f.read()
    return parse_xex(data)


def parse_xex(data: bytes) -> XexFile:
    """Parse .xex binary data."""
    xex = XexFile()
    pos = 0
    first = True

    while pos < len(data):
        # Check for $FFFF header
        if pos + 1 < len(data):
            marker = struct.unpack_from('<H', data, pos)[0]
            if marker == 0xFFFF:
                pos += 2
                if pos >= len(data):
                    break
            elif first:
                raise ValueError("XEX file must start with $FFFF header")

        first = False

        if pos + 3 >= len(data):
            break

        start = struct.unpack_from('<H', data, pos)[0]
        end = struct.unpack_from('<H', data, pos + 2)[0]
        pos += 4

        if end < start:
            break

        length = end - start + 1
        if pos + length > len(data):
            seg_data = data[pos:]
            pos = len(data)
        else:
            seg_data = data[pos:pos + length]
            pos += length

        seg = XexSegment(start=start, end=end, data=seg_data)
        xex.segments.append(seg)

        # Check for RUN ($02E0) and INIT ($02E2) vectors
        if start <= 0x02E0 <= end:
            offset = 0x02E0 - start
            if offset + 1 < len(seg_data):
                xex.run_addr = seg_data[offset] | (seg_data[offset + 1] << 8)

        if start <= 0x02E2 <= end:
            offset = 0x02E2 - start
            if offset + 1 < len(seg_data):
                init = seg_data[offset] | (seg_data[offset + 1] << 8)
                xex.init_addrs.append(init)

    return xex


def load_into_memory(memory, xex: XexFile):
    """Load XEX segments into memory (list or ObservableMemory).

    Returns run_addr or None.
    """
    for seg in xex.segments:
        for i, b in enumerate(seg.data):
            addr = seg.start + i
            if addr <= 0xFFFF:
                memory[addr] = b

    return xex.run_addr
