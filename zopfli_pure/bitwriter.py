"""Port of the bit writers AddBit, AddBits, AddHuffmanBits (deflate.c).

C threads ``unsigned char* bp`` (bit pointer, always in 0..7) and a growing
``out`` buffer through these functions. Here both live in one object.

As in C, a new zero byte is appended only when a bit is written while
``bp == 0``; so the number of bits represented is
``len(out) * 8`` if ``bp == 0`` else ``(len(out) - 1) * 8 + bp``.

The C functions write one bit per loop iteration; these ports write whole
groups of bits at once with the identical resulting byte layout.
"""

# _REV8[b] is the byte b with its 8 bits reversed.
_REV8 = [int("{:08b}".format(b)[::-1], 2) for b in range(256)]


def _reverse_bits(symbol, length):
    """Returns the low `length` bits of symbol in reversed order."""
    if length <= 16:
        v = symbol & 0xFFFF
        return ((_REV8[v & 0xFF] << 8) | _REV8[v >> 8]) >> (16 - length)
    r = 0
    for i in range(length):
        r = (r << 1) | ((symbol >> i) & 1)
    return r


class BitWriter(object):
    """Bit output buffer: ``out`` (bytearray) plus bit pointer ``bp`` (0..7)."""

    __slots__ = ("out", "bp")

    def __init__(self, out=None, bp=0):
        self.out = bytearray() if out is None else out
        self.bp = bp

    def add_bit(self, bit):
        """Port of AddBit (deflate.c)."""
        bp = self.bp
        if bp == 0:
            self.out.append(0)
        # C: (*out)[*outsize - 1] |= bit << *bp; the store truncates to 8 bits.
        self.out[-1] |= (bit << bp) & 0xFF
        self.bp = (bp + 1) & 7

    def add_bits(self, symbol, length):
        """Port of AddBits (deflate.c): the low `length` bits, LSB first."""
        if length <= 0:
            return
        bits = symbol & ((1 << length) - 1)
        out = self.out
        bp = self.bp
        if bp:
            # Fill the current partial byte.
            out[-1] |= (bits << bp) & 0xFF
            room = 8 - bp
            if length < room:
                self.bp = bp + length
                return
            bits >>= room
            length -= room
        # bp is now 0: every further bit starts a new byte when written.
        while length >= 8:
            out.append(bits & 0xFF)
            bits >>= 8
            length -= 8
        if length:
            out.append(bits)
        self.bp = length

    def add_huffman_bits(self, symbol, length):
        """Port of AddHuffmanBits (deflate.c): the low `length` bits, MSB first."""
        if length <= 0:
            return
        if length <= 16:
            v = symbol & 0xFFFF
            bits = ((_REV8[v & 0xFF] << 8) | _REV8[v >> 8]) >> (16 - length)
        else:
            bits = _reverse_bits(symbol, length)
        out = self.out
        bp = self.bp
        if bp:
            out[-1] |= (bits << bp) & 0xFF
            room = 8 - bp
            if length < room:
                self.bp = bp + length
                return
            bits >>= room
            length -= room
        while length >= 8:
            out.append(bits & 0xFF)
            bits >>= 8
            length -= 8
        if length:
            out.append(bits)
        self.bp = length
