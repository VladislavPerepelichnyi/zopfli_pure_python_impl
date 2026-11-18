"""Port of zlib_container.c (ZopfliZlibCompress and its adler32)."""

import sys

from .bitwriter import BitWriter
from . import deflate as _deflate


def adler32(data, size):
    """Port of adler32 (zlib_container.c).

    Calculates the adler32 checksum of data[0:size]. Like the C, the sums are
    reduced modulo 65521 only every 5550 bytes; 5550 is small enough that the
    32-bit unsigned sums cannot overflow, so plain Python ints give the C
    result. Each chunk is summed with a tight loop over a bytes slice.
    """
    sums_overflow = 5550
    s1 = 1
    s2 = 1 >> 16
    pos = 0

    while size > 0:
        amount = sums_overflow if size > sums_overflow else size
        size -= amount
        for b in bytes(data[pos:pos + amount]):
            s1 += b
            s2 += s1
        pos += amount
        s1 %= 65521
        s2 %= 65521

    return ((s2 << 16) | s1) & 0xFFFFFFFF


def zlib_compress(options, in_):
    """Port of ZopfliZlibCompress (zlib_container.c). Returns the zlib stream."""
    insize = len(in_)
    # C: adler32(in, (unsigned)insize)
    checksum = adler32(in_, insize & 0xFFFFFFFF)
    cmf = 120  # CM 8, CINFO 7. See zlib spec.
    flevel = 3
    fdict = 0
    cmfflg = 256 * cmf + fdict * 32 + flevel * 64
    fcheck = 31 - cmfflg % 31
    cmfflg += fcheck

    w = BitWriter(bytearray(), 0)
    w.out.append(cmfflg // 256)
    w.out.append(cmfflg % 256)

    _deflate.deflate(options, 2, 1, in_, insize, w)  # dynamic block, final

    out = w.out
    out.append((checksum >> 24) % 256)
    out.append((checksum >> 16) % 256)
    out.append((checksum >> 8) % 256)
    out.append(checksum % 256)

    if options.verbose:
        outsize = len(out)
        removed = _deflate._c_div(
            100.0 * float((insize - outsize) & 0xFFFFFFFFFFFFFFFF), float(insize))
        sys.stderr.write(
            "Original Size: %d, Zlib: %d, Compression: %s%% Removed\n"
            % (_deflate._c_int(insize), _deflate._c_int(outsize),
               _deflate._c_percent_f(removed)))
    return bytes(out)
