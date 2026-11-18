"""Port of symbols.h: utilities for the lz77 symbols of the deflate spec.

The reference is built with gcc, so the ``ZOPFLI_HAS_BUILTIN_CLZ`` variants of
the distance functions are the ones that run; ``31 ^ __builtin_clz(x)`` is
``x.bit_length() - 1`` for ``x > 0``. For every valid distance (1..32768) they
agree with the table-based variants.

Besides the functions, the lookup tables are exported as module-level lists so
hot loops can index them directly:

* ``LENGTH_SYMBOL``, ``LENGTH_EXTRA_BITS``, ``LENGTH_EXTRA_BITS_VALUE``:
  indexed by length 0..258 (the C ``static const int table[259]``).
* ``LENGTH_SYMBOL_EXTRA_BITS``: indexed by ``s - 257`` (29 entries).
* ``DIST_SYMBOL_EXTRA_BITS``: indexed by distance symbol (30 entries).
* ``DIST_SYMBOL``, ``DIST_EXTRA_BITS``, ``DIST_EXTRA_BITS_VALUE``: indexed by
  distance 0..32768 (precomputed from the functions; index 0 holds what the C
  returns for dist 0: symbol -1, 0 extra bits, value 0).
"""

LENGTH_EXTRA_BITS = [
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1,
    2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
    3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3,
    3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3,
    4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4,
    4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4,
    4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4,
    4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4,
    5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
    5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
    5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
    5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
    5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
    5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
    5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
    5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 0
]

LENGTH_EXTRA_BITS_VALUE = [
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 2, 3, 0,
    1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 2, 3, 4, 5,
    6, 7, 0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 2, 3, 4, 5, 6,
    7, 8, 9, 10, 11, 12, 13, 14, 15, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12,
    13, 14, 15, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 0, 1, 2,
    3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9,
    10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28,
    29, 30, 31, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17,
    18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 0, 1, 2, 3, 4, 5, 6,
    7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26,
    27, 28, 29, 30, 31, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
    16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 0
]

LENGTH_SYMBOL = [
    0, 0, 0, 257, 258, 259, 260, 261, 262, 263, 264,
    265, 265, 266, 266, 267, 267, 268, 268,
    269, 269, 269, 269, 270, 270, 270, 270,
    271, 271, 271, 271, 272, 272, 272, 272,
    273, 273, 273, 273, 273, 273, 273, 273,
    274, 274, 274, 274, 274, 274, 274, 274,
    275, 275, 275, 275, 275, 275, 275, 275,
    276, 276, 276, 276, 276, 276, 276, 276,
    277, 277, 277, 277, 277, 277, 277, 277,
    277, 277, 277, 277, 277, 277, 277, 277,
    278, 278, 278, 278, 278, 278, 278, 278,
    278, 278, 278, 278, 278, 278, 278, 278,
    279, 279, 279, 279, 279, 279, 279, 279,
    279, 279, 279, 279, 279, 279, 279, 279,
    280, 280, 280, 280, 280, 280, 280, 280,
    280, 280, 280, 280, 280, 280, 280, 280,
    281, 281, 281, 281, 281, 281, 281, 281,
    281, 281, 281, 281, 281, 281, 281, 281,
    281, 281, 281, 281, 281, 281, 281, 281,
    281, 281, 281, 281, 281, 281, 281, 281,
    282, 282, 282, 282, 282, 282, 282, 282,
    282, 282, 282, 282, 282, 282, 282, 282,
    282, 282, 282, 282, 282, 282, 282, 282,
    282, 282, 282, 282, 282, 282, 282, 282,
    283, 283, 283, 283, 283, 283, 283, 283,
    283, 283, 283, 283, 283, 283, 283, 283,
    283, 283, 283, 283, 283, 283, 283, 283,
    283, 283, 283, 283, 283, 283, 283, 283,
    284, 284, 284, 284, 284, 284, 284, 284,
    284, 284, 284, 284, 284, 284, 284, 284,
    284, 284, 284, 284, 284, 284, 284, 284,
    284, 284, 284, 284, 284, 284, 284, 285
]

# Index s - 257.
LENGTH_SYMBOL_EXTRA_BITS = [
    0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2,
    3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0
]

DIST_SYMBOL_EXTRA_BITS = [
    0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8,
    9, 9, 10, 10, 11, 11, 12, 12, 13, 13
]


def get_dist_extra_bits(dist):
    """Port of ZopfliGetDistExtraBits (symbols.h)."""
    if dist < 5:
        return 0
    return (dist - 1).bit_length() - 2  # log2(dist - 1) - 1


def get_dist_extra_bits_value(dist):
    """Port of ZopfliGetDistExtraBitsValue (symbols.h)."""
    if dist < 5:
        return 0
    l = (dist - 1).bit_length() - 1  # log2(dist - 1)
    return (dist - (1 + (1 << l))) & ((1 << (l - 1)) - 1)


def _get_dist_symbol_computed(dist):
    """Port of ZopfliGetDistSymbol (symbols.h), computed form."""
    if dist < 5:
        return dist - 1
    l = (dist - 1).bit_length() - 1  # log2(dist - 1)
    r = ((dist - 1) >> (l - 1)) & 1
    return l * 2 + r


# Lookup tables indexed by distance 0..32768 (ZOPFLI_WINDOW_SIZE).
DIST_SYMBOL = [_get_dist_symbol_computed(d) for d in range(32769)]
DIST_EXTRA_BITS = [get_dist_extra_bits(d) for d in range(32769)]
DIST_EXTRA_BITS_VALUE = [get_dist_extra_bits_value(d) for d in range(32769)]


def get_dist_symbol(dist, _table=DIST_SYMBOL):
    """Port of ZopfliGetDistSymbol (symbols.h). Table lookup for 0..32768."""
    if 0 <= dist <= 32768:
        return _table[dist]
    return _get_dist_symbol_computed(dist)


def get_length_extra_bits(l):
    """Port of ZopfliGetLengthExtraBits (symbols.h)."""
    return LENGTH_EXTRA_BITS[l]


def get_length_extra_bits_value(l):
    """Port of ZopfliGetLengthExtraBitsValue (symbols.h)."""
    return LENGTH_EXTRA_BITS_VALUE[l]


def get_length_symbol(l):
    """Port of ZopfliGetLengthSymbol (symbols.h). Returns 257..285."""
    return LENGTH_SYMBOL[l]


def get_length_symbol_extra_bits(s):
    """Port of ZopfliGetLengthSymbolExtraBits (symbols.h)."""
    return LENGTH_SYMBOL_EXTRA_BITS[s - 257]


def get_dist_symbol_extra_bits(s):
    """Port of ZopfliGetDistSymbolExtraBits (symbols.h)."""
    return DIST_SYMBOL_EXTRA_BITS[s]
