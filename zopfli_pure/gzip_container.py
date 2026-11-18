"""Port of gzip_container.c (ZopfliGzipCompress and its table-based CRC32)."""

import sys

from .bitwriter import BitWriter
from . import deflate as _deflate


def _make_crc32_table():
    """Builds the 256-entry table for CRC polynomial 0xedb88320.

    The C has the table as a literal (crc32_table); this generates the same
    values (checked against the C literal in tests/test_containers.py).
    """
    table = []
    for n in range(256):
        c = n
        for _ in range(8):
            if c & 1:
                c = 0xEDB88320 ^ (c >> 1)
            else:
                c >>= 1
        table.append(c)
    return table


CRC32_TABLE = _make_crc32_table()


def crc(data, size):
    """Port of CRC (gzip_container.c). Returns the CRC32 of data[0:size]."""
    table = CRC32_TABLE
    result = 0xFFFFFFFF
    for b in bytes(data[:size]):
        result = table[(result ^ b) & 0xFF] ^ (result >> 8)
    return result ^ 0xFFFFFFFF


def gzip_compress(options, in_):
    """Port of ZopfliGzipCompress (gzip_container.c). Returns the gzip stream.

    Compresses the data according to the gzip specification, RFC 1952.
    """
    insize = len(in_)
    crcvalue = crc(in_, insize)

    w = BitWriter(bytearray(), 0)
    out = w.out
    out.append(31)  # ID1
    out.append(139)  # ID2
    out.append(8)  # CM
    out.append(0)  # FLG
    # MTIME
    out.append(0)
    out.append(0)
    out.append(0)
    out.append(0)

    out.append(2)  # XFL, 2 indicates best compression.
    out.append(3)  # OS follows Unix conventions.

    _deflate.deflate(options, 2, 1, in_, insize, w)  # Dynamic block, final

    out = w.out
    # CRC
    out.append(crcvalue % 256)
    out.append((crcvalue >> 8) % 256)
    out.append((crcvalue >> 16) % 256)
    out.append((crcvalue >> 24) % 256)

    # ISIZE
    out.append(insize % 256)
    out.append((insize >> 8) % 256)
    out.append((insize >> 16) % 256)
    out.append((insize >> 24) % 256)

    if options.verbose:
        outsize = len(out)
        removed = _deflate._c_div(
            100.0 * float((insize - outsize) & 0xFFFFFFFFFFFFFFFF), float(insize))
        sys.stderr.write(
            "Original Size: %d, Gzip: %d, Compression: %s%% Removed\n"
            % (_deflate._c_int(insize), _deflate._c_int(outsize),
               _deflate._c_percent_f(removed)))
    return bytes(out)
