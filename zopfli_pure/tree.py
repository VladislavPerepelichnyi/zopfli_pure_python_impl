"""Port of tree.c: Huffman tree utilities (canonical codes, entropy)."""

from math import log as _log

from .katajainen import length_limited_code_lengths


def lengths_to_symbols(lengths, n, maxbits, symbols):
    """Port of ZopfliLengthsToSymbols (tree.c).

    Converts a series of Huffman tree bitlengths to the canonical bit values
    of the symbols (deflate, RFC 1951 3.2.2). symbols (pre-sized list of at
    least n ints) is filled in place.

    No 32-bit masking of ``code``: with maxbits <= 15 and n <= 288 (the only
    values zopfli uses) the codes stay far below 2**32.
    """
    for i in range(n):
        symbols[i] = 0

    # 1) Count the number of codes for each code length. Let bl_count[N] be
    # the number of codes of length N, N >= 1.
    bl_count = [0] * (maxbits + 1)
    for i in range(n):
        # C: assert(lengths[i] <= maxbits). An out-of-range length raises
        # IndexError here instead of writing out of bounds.
        bl_count[lengths[i]] += 1
    # 2) Find the numerical value of the smallest code for each code length.
    next_code = [0] * (maxbits + 1)
    code = 0
    bl_count[0] = 0
    for bits in range(1, maxbits + 1):
        code = (code + bl_count[bits - 1]) << 1
        next_code[bits] = code
    # 3) Assign numerical values to all codes, using consecutive values for
    # all codes of the same length with the base values determined at step 2.
    for i in range(n):
        length = lengths[i]
        if length != 0:
            symbols[i] = next_code[length]
            next_code[length] += 1


def calculate_entropy(count, n, bitlengths):
    """Port of ZopfliCalculateEntropy (tree.c).

    Calculates the entropy of each symbol, based on the counts of each
    symbol. The result is similar to the result of calculate_bit_lengths, but
    with the actual theoretical bit lengths according to the entropy. Since
    the resulting values are fractional, they cannot be used to encode the
    tree specified by DEFLATE. bitlengths (pre-sized list of at least n
    floats) is filled in place.

    C accumulates the sum in a 32-bit ``unsigned``; that wrap is not
    reproduced because zopfli's counts never sum to 2**32 (see
    docs/notes/tree.md).
    """
    kInvLog2 = 1.4426950408889  # 1.0 / log(2.0)
    log = _log
    if len(count) == n:
        total = sum(count)
    else:
        total = sum(count[:n])
    if total == 0:
        # C: log(n), which is -inf for n == 0 (then the loop does not run).
        log2sum = (log(n) if n else float("-inf")) * kInvLog2
    else:
        log2sum = log(total) * kInvLog2
    for i in range(n):
        c = count[i]
        # When the count of the symbol is 0, but its cost is requested anyway,
        # it means the symbol will appear at least once anyway, so give it the
        # cost as if its count is 1.
        if c == 0:
            b = log2sum
        else:
            b = log2sum - log(c) * kInvLog2
            # Depending on compiler and architecture, the above subtraction of
            # two floating point numbers may give a negative result very close
            # to zero instead of zero. Clamp it to zero.
            if b < 0 and b > -1e-5:
                b = 0.0
        bitlengths[i] = b


def calculate_bit_lengths(count, n, maxbits, bitlengths):
    """Port of ZopfliCalculateBitLengths (tree.c).

    Calculates the bitlengths for the Huffman tree, based on the counts of
    each symbol. bitlengths is filled in place.
    """
    error = length_limited_code_lengths(count, n, maxbits, bitlengths)
    if error:
        # C: assert(!error).
        raise AssertionError("ZopfliLengthLimitedCodeLengths failed")
