"""Port of deflate.c (everything except the bit writers, see bitwriter.py).

Functions keep the C order of operations, the C tie-breaking and the C
integer/float conversions. Comments starting with "C:" point at the original
code where the Python form is not obvious.
"""

import sys

from .util import ZOPFLI_NUM_LL, ZOPFLI_NUM_D, ZOPFLI_MASTER_BLOCK_SIZE
from .symbols import (
    get_dist_extra_bits,
    get_dist_extra_bits_value,
    get_dist_symbol,
    LENGTH_SYMBOL,
    LENGTH_EXTRA_BITS,
    LENGTH_EXTRA_BITS_VALUE,
    LENGTH_SYMBOL_EXTRA_BITS,
    DIST_SYMBOL_EXTRA_BITS,
)
from .tree import calculate_bit_lengths, lengths_to_symbols
from .lz77 import (
    LZ77Store,
    BlockState,
    append_lz77_store,
    lz77_get_byte_range,
    lz77_get_histogram,
)
# deflate <-> squeeze / blocksplitter form an import cycle: import the modules
# and look the functions up at call time (see PORTING_SPEC.md, "Import cycles").
from . import squeeze
from . import blocksplitter

_SIZE_T_MASK = 0xFFFFFFFFFFFFFFFF


def patch_distance_codes_for_buggy_decoders(d_lengths):
    """Port of PatchDistanceCodesForBuggyDecoders (deflate.c).

    Ensures there are at least 2 distance codes to support buggy decoders.
    d_lengths (32 entries) is modified in place.
    """
    num_dist_codes = 0  # Amount of non-zero distance codes
    for i in range(30):  # Ignore the two unused codes from the spec
        if d_lengths[i]:
            num_dist_codes += 1
        if num_dist_codes >= 2:
            return  # Two or more codes is fine.

    if num_dist_codes == 0:
        d_lengths[0] = d_lengths[1] = 1
    elif num_dist_codes == 1:
        d_lengths[1 if d_lengths[0] else 0] = 1


# The order in which code length code lengths are encoded as per deflate.
_CLCL_ORDER = (16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15)


def encode_tree(ll_lengths, d_lengths, use_16, use_17, use_18, w):
    """Port of EncodeTree (deflate.c).

    Encodes the Huffman tree and returns how many bits its encoding takes. If w
    (the BitWriter standing in for bp/out/outsize) is None, only returns the
    size (C: out == NULL, "size_only").
    """
    size_only = w is None
    rle = []  # Runlength encoded version of lengths of litlen and dist trees.
    rle_bits = []  # Extra bits for rle values 16, 17 and 18.
    hlit = 29  # 286 - 257
    hdist = 29  # 32 - 1, but gzip does not like hdist > 29.
    clcounts = [0] * 19

    # Trim zeros.
    while hlit > 0 and ll_lengths[257 + hlit - 1] == 0:
        hlit -= 1
    while hdist > 0 and d_lengths[1 + hdist - 1] == 0:
        hdist -= 1
    hlit2 = hlit + 257

    lld_total = hlit2 + hdist + 1
    # C reads lengths as (i < hlit2 ? ll_lengths[i] : d_lengths[i - hlit2]);
    # the concatenation below is the same sequence. C stores each value in an
    # unsigned char; code lengths are <= 15 so that cast is the identity.
    lld = list(ll_lengths[:hlit2]) + list(d_lengths[:hdist + 1])

    i = 0
    while i < lld_total:
        # This is an encoding of a huffman tree, so now the length is a symbol
        symbol = lld[i]
        count = 1
        if use_16 or (symbol == 0 and (use_17 or use_18)):
            j = i + 1
            while j < lld_total and symbol == lld[j]:
                count += 1
                j += 1
        i += count - 1

        # Repetitions of zeroes
        if symbol == 0 and count >= 3:
            if use_18:
                while count >= 11:
                    count2 = 138 if count > 138 else count
                    if not size_only:
                        rle.append(18)
                        rle_bits.append(count2 - 11)
                    clcounts[18] += 1
                    count -= count2
            if use_17:
                while count >= 3:
                    count2 = 10 if count > 10 else count
                    if not size_only:
                        rle.append(17)
                        rle_bits.append(count2 - 3)
                    clcounts[17] += 1
                    count -= count2

        # Repetitions of any symbol
        if use_16 and count >= 4:
            count -= 1  # Since the first one is hardcoded.
            clcounts[symbol] += 1
            if not size_only:
                rle.append(symbol)
                rle_bits.append(0)
            while count >= 3:
                count2 = 6 if count > 6 else count
                if not size_only:
                    rle.append(16)
                    rle_bits.append(count2 - 3)
                clcounts[16] += 1
                count -= count2

        # No or insufficient repetition
        clcounts[symbol] += count
        if not size_only:
            while count > 0:
                rle.append(symbol)
                rle_bits.append(0)
                count -= 1
        i += 1

    clcl = [0] * 19  # Code length code lengths.
    calculate_bit_lengths(clcounts, 19, 7, clcl)
    if not size_only:
        clsymbols = [0] * 19
        lengths_to_symbols(clcl, 19, 7, clsymbols)

    hclen = 15
    # Trim zeros.
    while hclen > 0 and clcounts[_CLCL_ORDER[hclen + 4 - 1]] == 0:
        hclen -= 1

    if not size_only:
        add_bits = w.add_bits
        add_huffman_bits = w.add_huffman_bits
        add_bits(hlit, 5)
        add_bits(hdist, 5)
        add_bits(hclen, 4)

        for i in range(hclen + 4):
            add_bits(clcl[_CLCL_ORDER[i]], 3)

        for i in range(len(rle)):
            r = rle[i]
            add_huffman_bits(clsymbols[r], clcl[r])
            # Extra bits.
            if r == 16:
                add_bits(rle_bits[i], 2)
            elif r == 17:
                add_bits(rle_bits[i], 3)
            elif r == 18:
                add_bits(rle_bits[i], 7)

    result_size = 14  # hlit, hdist, hclen bits
    result_size += (hclen + 4) * 3  # clcl bits
    for i in range(19):
        result_size += clcl[i] * clcounts[i]
    # Extra bits.
    result_size += clcounts[16] * 2
    result_size += clcounts[17] * 3
    result_size += clcounts[18] * 7

    return result_size


def add_dynamic_tree(ll_lengths, d_lengths, w):
    """Port of AddDynamicTree (deflate.c)."""
    best = 0
    bestsize = 0

    for i in range(8):
        size = encode_tree(ll_lengths, d_lengths, i & 1, i & 2, i & 4, None)
        if bestsize == 0 or size < bestsize:
            bestsize = size
            best = i

    encode_tree(ll_lengths, d_lengths, best & 1, best & 2, best & 4, w)


def calculate_tree_size(ll_lengths, d_lengths):
    """Port of CalculateTreeSize (deflate.c).

    Gives the exact size of the tree, in bits, as it will be encoded in DEFLATE.
    """
    result = 0

    for i in range(8):
        size = encode_tree(ll_lengths, d_lengths, i & 1, i & 2, i & 4, None)
        if result == 0 or size < result:
            result = size

    return result


def _reversed_codes(symbols, lengths, n):
    """Bit-reverses each Huffman code so it can be emitted LSB-first.

    Helper for the inlined bit writer in add_lz77_data: AddHuffmanBits writes the
    code MSB-first one bit at a time, which is the same bit sequence as writing
    the reversed code LSB-first. Not a C function.
    """
    rev = [0] * n
    for s in range(n):
        code = symbols[s]
        length = lengths[s]
        r = 0
        for _ in range(length):
            r = (r << 1) | (code & 1)
            code >>= 1
        rev[s] = r
    return rev


def add_lz77_data(lz77, lstart, lend, expected_data_size,
                  ll_symbols, ll_lengths, d_symbols, d_lengths, w):
    """Port of AddLZ77Data (deflate.c).

    Adds all lit/len and dist codes from the lists as huffman symbols. Does not
    add end code 256. expected_data_size is the uncompressed block size, used
    for assert, but you can set it to 0 to not do the assertion.

    The bit writes are inlined: bits are accumulated LSB-first in an integer
    and flushed in whole bytes, which produces exactly the bytes and bit
    pointer the C AddBit/AddBits/AddHuffmanBits sequence produces. The C
    per-symbol asserts (litlen range, non-zero code lengths) are omitted from
    this hot loop; the final testlength assert is kept.
    """
    ll_rev = _reversed_codes(ll_symbols, ll_lengths, ZOPFLI_NUM_LL)
    d_rev = _reversed_codes(d_symbols, d_lengths, ZOPFLI_NUM_D)
    litlens = lz77.litlens
    dists = lz77.dists
    length_symbol = LENGTH_SYMBOL
    length_extra_bits = LENGTH_EXTRA_BITS
    length_extra_bits_value = LENGTH_EXTRA_BITS_VALUE
    dist_symbol = get_dist_symbol
    dist_extra_bits = get_dist_extra_bits
    dist_extra_bits_value = get_dist_extra_bits_value

    out = w.out
    # Take the partially filled last byte (if any) into the accumulator. Its
    # bits at positions >= bp are zero, as the C bit writer guarantees.
    if w.bp:
        acc = out[-1]
        nacc = w.bp
        del out[-1]
    else:
        acc = 0
        nacc = 0

    testlength = 0
    for i in range(lstart, lend):
        dist = dists[i]
        litlen = litlens[i]
        if dist == 0:
            acc |= ll_rev[litlen] << nacc
            nacc += ll_lengths[litlen]
            testlength += 1
        else:
            lls = length_symbol[litlen]
            ds = dist_symbol(dist)
            acc |= ll_rev[lls] << nacc
            nacc += ll_lengths[lls]
            acc |= length_extra_bits_value[litlen] << nacc
            nacc += length_extra_bits[litlen]
            acc |= d_rev[ds] << nacc
            nacc += d_lengths[ds]
            acc |= dist_extra_bits_value(dist) << nacc
            nacc += dist_extra_bits(dist)
            testlength += litlen
        if nacc >= 64:
            out += (acc & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")
            acc >>= 64
            nacc -= 64
    nbytes = (nacc + 7) >> 3
    if nbytes:
        out += acc.to_bytes(nbytes, "little")
    w.bp = nacc & 7
    assert expected_data_size == 0 or testlength == expected_data_size


def get_fixed_tree(ll_lengths, d_lengths):
    """Port of GetFixedTree (deflate.c). Fills both lists in place."""
    for i in range(0, 144):
        ll_lengths[i] = 8
    for i in range(144, 256):
        ll_lengths[i] = 9
    for i in range(256, 280):
        ll_lengths[i] = 7
    for i in range(280, 288):
        ll_lengths[i] = 8
    for i in range(32):
        d_lengths[i] = 5


def calculate_block_symbol_size_small(ll_lengths, d_lengths, lz77, lstart, lend):
    """Port of CalculateBlockSymbolSizeSmall (deflate.c)."""
    result = 0
    litlens = lz77.litlens
    dists = lz77.dists
    length_symbol = LENGTH_SYMBOL
    length_symbol_extra_bits = LENGTH_SYMBOL_EXTRA_BITS
    dist_symbol_extra_bits = DIST_SYMBOL_EXTRA_BITS
    dist_symbol = get_dist_symbol
    for i in range(lstart, lend):
        if dists[i] == 0:
            result += ll_lengths[litlens[i]]
        else:
            ll_symbol = length_symbol[litlens[i]]
            d_symbol = dist_symbol(dists[i])
            result += ll_lengths[ll_symbol]
            result += d_lengths[d_symbol]
            result += length_symbol_extra_bits[ll_symbol - 257]
            result += dist_symbol_extra_bits[d_symbol]
    result += ll_lengths[256]  # end symbol
    return result


def calculate_block_symbol_size_given_counts(ll_counts, d_counts, ll_lengths,
                                             d_lengths, lz77, lstart, lend):
    """Port of CalculateBlockSymbolSizeGivenCounts (deflate.c)."""
    if lstart + ZOPFLI_NUM_LL * 3 > lend:
        return calculate_block_symbol_size_small(
            ll_lengths, d_lengths, lz77, lstart, lend)
    result = 0
    for i in range(256):
        result += ll_lengths[i] * ll_counts[i]
    length_symbol_extra_bits = LENGTH_SYMBOL_EXTRA_BITS
    for i in range(257, 286):
        result += ll_lengths[i] * ll_counts[i]
        result += length_symbol_extra_bits[i - 257] * ll_counts[i]
    dist_symbol_extra_bits = DIST_SYMBOL_EXTRA_BITS
    for i in range(30):
        result += d_lengths[i] * d_counts[i]
        result += dist_symbol_extra_bits[i] * d_counts[i]
    result += ll_lengths[256]  # end symbol
    return result


def calculate_block_symbol_size(ll_lengths, d_lengths, lz77, lstart, lend):
    """Port of CalculateBlockSymbolSize (deflate.c).

    Calculates size of the part after the header and tree of an LZ77 block, in
    bits.
    """
    if lstart + ZOPFLI_NUM_LL * 3 > lend:
        return calculate_block_symbol_size_small(
            ll_lengths, d_lengths, lz77, lstart, lend)
    ll_counts = [0] * ZOPFLI_NUM_LL
    d_counts = [0] * ZOPFLI_NUM_D
    lz77_get_histogram(lz77, lstart, lend, ll_counts, d_counts)
    return calculate_block_symbol_size_given_counts(
        ll_counts, d_counts, ll_lengths, d_lengths, lz77, lstart, lend)


def abs_diff(x, y):
    """Port of AbsDiff (deflate.c). Both arguments are size_t (non-negative)."""
    if x > y:
        return x - y
    return y - x


def optimize_huffman_for_rle(length, counts):
    """Port of OptimizeHuffmanForRle (deflate.c).

    Changes the population counts (a list, modified in place) in a way that the
    consequent Huffman tree compression, especially its rle-part, will be more
    likely to compress this data more efficiently. length contains the size of
    the histogram.
    """
    # 1) We don't want to touch the trailing zeros. We may break the
    # rules of the format by adding more data in the distance codes.
    while length >= 0:
        if length == 0:
            return
        if counts[length - 1] != 0:
            # Now counts[0..length - 1] does not have trailing zeros.
            break
        length -= 1
    # 2) Let's mark all population counts that already can be encoded
    # with an rle code.
    good_for_rle = [0] * length

    # Let's not spoil any of the existing good rle codes.
    # Mark any seq of 0's that is longer than 5 as a good_for_rle.
    # Mark any seq of non-0's that is longer than 7 as a good_for_rle.
    symbol = counts[0]
    stride = 0
    for i in range(length + 1):
        if i == length or counts[i] != symbol:
            if (symbol == 0 and stride >= 5) or (symbol != 0 and stride >= 7):
                for k in range(stride):
                    good_for_rle[i - k - 1] = 1
            stride = 1
            if i != length:
                symbol = counts[i]
        else:
            stride += 1

    # 3) Let's replace those population counts that lead to more rle codes.
    stride = 0
    limit = counts[0]
    sum_ = 0
    for i in range(length + 1):
        if (i == length or good_for_rle[i]
                # Heuristic for selecting the stride ranges to collapse.
                or abs_diff(counts[i], limit) >= 4):
            if stride >= 4 or (stride >= 3 and sum_ == 0):
                # The stride must end, collapse what we have, if we have
                # enough (4). C: int count = (size_t)(sum + stride / 2) / stride;
                # all operands are non-negative, so // is C's division.
                count = (sum_ + stride // 2) // stride
                if count < 1:
                    count = 1
                if sum_ == 0:
                    # Don't make an all zeros stride to be upgraded to ones.
                    count = 0
                for k in range(stride):
                    # We don't want to change value at counts[i],
                    # that is already belonging to the next stride. Thus - 1.
                    counts[i - k - 1] = count
            stride = 0
            sum_ = 0
            if i < length - 3:
                # All interesting strides have a count of at least 4,
                # at least when non-zeros.
                limit = (counts[i] + counts[i + 1]
                         + counts[i + 2] + counts[i + 3] + 2) // 4
            elif i < length:
                limit = counts[i]
            else:
                limit = 0
        stride += 1
        if i != length:
            sum_ += counts[i]


def try_optimize_huffman_for_rle(lz77, lstart, lend, ll_counts, d_counts,
                                 ll_lengths, d_lengths):
    """Port of TryOptimizeHuffmanForRle (deflate.c).

    Tries out OptimizeHuffmanForRle for this block, if the result is smaller,
    uses it, otherwise keeps the original. Returns size of encoded tree and data
    in bits, not including the 3-bit block header. ll_lengths and d_lengths are
    updated in place when the optimized version wins.
    """
    # C: the size_t results are converted to double on assignment.
    treesize = float(calculate_tree_size(ll_lengths, d_lengths))
    datasize = float(calculate_block_symbol_size_given_counts(
        ll_counts, d_counts, ll_lengths, d_lengths, lz77, lstart, lend))

    ll_counts2 = list(ll_counts)
    d_counts2 = list(d_counts)
    optimize_huffman_for_rle(ZOPFLI_NUM_LL, ll_counts2)
    optimize_huffman_for_rle(ZOPFLI_NUM_D, d_counts2)
    ll_lengths2 = [0] * ZOPFLI_NUM_LL
    d_lengths2 = [0] * ZOPFLI_NUM_D
    calculate_bit_lengths(ll_counts2, ZOPFLI_NUM_LL, 15, ll_lengths2)
    calculate_bit_lengths(d_counts2, ZOPFLI_NUM_D, 15, d_lengths2)
    patch_distance_codes_for_buggy_decoders(d_lengths2)

    treesize2 = float(calculate_tree_size(ll_lengths2, d_lengths2))
    datasize2 = float(calculate_block_symbol_size_given_counts(
        ll_counts, d_counts, ll_lengths2, d_lengths2, lz77, lstart, lend))

    if treesize2 + datasize2 < treesize + datasize:
        ll_lengths[:] = ll_lengths2
        d_lengths[:] = d_lengths2
        return treesize2 + datasize2
    return treesize + datasize


def get_dynamic_lengths(lz77, lstart, lend, ll_lengths, d_lengths):
    """Port of GetDynamicLengths (deflate.c).

    Calculates the bit lengths for the symbols for dynamic blocks (filled in
    place). Returns size of encoded tree and data in bits, not including the
    3-bit block header.
    """
    ll_counts = [0] * ZOPFLI_NUM_LL
    d_counts = [0] * ZOPFLI_NUM_D

    lz77_get_histogram(lz77, lstart, lend, ll_counts, d_counts)
    ll_counts[256] = 1  # End symbol.
    calculate_bit_lengths(ll_counts, ZOPFLI_NUM_LL, 15, ll_lengths)
    calculate_bit_lengths(d_counts, ZOPFLI_NUM_D, 15, d_lengths)
    patch_distance_codes_for_buggy_decoders(d_lengths)
    return try_optimize_huffman_for_rle(
        lz77, lstart, lend, ll_counts, d_counts, ll_lengths, d_lengths)


def calculate_block_size(lz77, lstart, lend, btype):
    """Port of ZopfliCalculateBlockSize (deflate.c). Returns a float (C double)."""
    result = 3.0  # bfinal and btype bits

    if btype == 0:
        length = lz77_get_byte_range(lz77, lstart, lend)
        rem = length % 65535
        blocks = length // 65535 + (1 if rem else 0)
        # An uncompressed block must actually be split into multiple blocks if
        # it's larger than 65535 bytes long. Eeach block header is 5 bytes: 3
        # bits, padding, LEN and NLEN (potential less padding for first one
        # ignored). C: computed in size_t, then converted to double.
        return float(blocks * 5 * 8 + length * 8)
    ll_lengths = [0] * ZOPFLI_NUM_LL
    d_lengths = [0] * ZOPFLI_NUM_D
    if btype == 1:
        get_fixed_tree(ll_lengths, d_lengths)
        result += float(calculate_block_symbol_size(
            ll_lengths, d_lengths, lz77, lstart, lend))
    else:
        result += get_dynamic_lengths(lz77, lstart, lend, ll_lengths, d_lengths)

    return result


def calculate_block_size_auto_type(lz77, lstart, lend):
    """Port of ZopfliCalculateBlockSizeAutoType (deflate.c)."""
    uncompressedcost = calculate_block_size(lz77, lstart, lend, 0)
    # Don't do the expensive fixed cost calculation for larger blocks that are
    # unlikely to use it.
    fixedcost = (uncompressedcost if lz77.size > 1000
                 else calculate_block_size(lz77, lstart, lend, 1))
    dyncost = calculate_block_size(lz77, lstart, lend, 2)
    if uncompressedcost < fixedcost and uncompressedcost < dyncost:
        return uncompressedcost
    return fixedcost if fixedcost < dyncost else dyncost


def add_non_compressed_block(options, final, in_, instart, inend, w):
    """Port of AddNonCompressedBlock (deflate.c).

    Since an uncompressed block can be max 65535 in size, it actually adds
    multible blocks if needed.
    """
    pos = instart
    while True:
        blocksize = 65535  # C: unsigned short
        if pos + blocksize > inend:
            blocksize = (inend - pos) & 0xFFFF
        currentfinal = pos + blocksize >= inend

        nlen = (~blocksize) & 0xFFFF  # C: unsigned short nlen = ~blocksize;

        w.add_bit(1 if (final and currentfinal) else 0)
        # BTYPE 00
        w.add_bit(0)
        w.add_bit(0)

        # Any bits of input up to the next byte boundary are ignored.
        w.bp = 0

        out = w.out
        out.append(blocksize % 256)
        out.append((blocksize // 256) % 256)
        out.append(nlen % 256)
        out.append((nlen // 256) % 256)

        out += bytes(in_[pos:pos + blocksize])

        if currentfinal:
            break
        pos += blocksize


def add_lz77_block(options, btype, final, lz77, lstart, lend,
                   expected_data_size, w):
    """Port of AddLZ77Block (deflate.c).

    Adds a deflate block with the given LZ77 data to the output (BitWriter w).
    """
    if btype == 0:
        length = lz77_get_byte_range(lz77, lstart, lend)
        pos = 0 if lstart == lend else lz77.pos[lstart]
        end = pos + length
        add_non_compressed_block(options, final, lz77.data, pos, end, w)
        return

    w.add_bit(final)
    w.add_bit(btype & 1)
    w.add_bit((btype & 2) >> 1)

    ll_lengths = [0] * ZOPFLI_NUM_LL
    d_lengths = [0] * ZOPFLI_NUM_D
    if btype == 1:
        # Fixed block.
        get_fixed_tree(ll_lengths, d_lengths)
    else:
        # Dynamic block.
        assert btype == 2

        get_dynamic_lengths(lz77, lstart, lend, ll_lengths, d_lengths)

        detect_tree_size = len(w.out)
        add_dynamic_tree(ll_lengths, d_lengths, w)
        if options.verbose:
            sys.stderr.write("treesize: %d\n"
                             % _c_int(len(w.out) - detect_tree_size))

    ll_symbols = [0] * ZOPFLI_NUM_LL
    d_symbols = [0] * ZOPFLI_NUM_D
    lengths_to_symbols(ll_lengths, ZOPFLI_NUM_LL, 15, ll_symbols)
    lengths_to_symbols(d_lengths, ZOPFLI_NUM_D, 15, d_symbols)

    detect_block_size = len(w.out)
    add_lz77_data(lz77, lstart, lend, expected_data_size,
                  ll_symbols, ll_lengths, d_symbols, d_lengths, w)
    # End symbol.
    w.add_huffman_bits(ll_symbols[256], ll_lengths[256])

    uncompressed_size = 0
    litlens = lz77.litlens
    dists = lz77.dists
    for i in range(lstart, lend):
        uncompressed_size += 1 if dists[i] == 0 else litlens[i]
    if options.verbose:
        compressed_size = len(w.out) - detect_block_size
        sys.stderr.write("compressed block size: %d (%dk) (unc: %d)\n" % (
            _c_int(compressed_size), _c_int(compressed_size // 1024),
            _c_int(uncompressed_size)))


def add_lz77_block_auto_type(options, final, lz77, lstart, lend,
                             expected_data_size, w):
    """Port of AddLZ77BlockAutoType (deflate.c)."""
    uncompressedcost = calculate_block_size(lz77, lstart, lend, 0)
    fixedcost = calculate_block_size(lz77, lstart, lend, 1)
    dyncost = calculate_block_size(lz77, lstart, lend, 2)

    # Whether to perform the expensive calculation of creating an optimal block
    # with fixed huffman tree to check if smaller. Only do this for small blocks
    # or blocks which already are pretty good with fixed huffman tree.
    expensivefixed = (lz77.size < 1000) or fixedcost <= dyncost * 1.1

    if lstart == lend:
        # Smallest empty block is represented by fixed block
        w.add_bits(final, 1)
        w.add_bits(1, 2)  # btype 01
        w.add_bits(0, 7)  # end symbol has code 0000000
        return
    fixedstore = LZ77Store(lz77.data)
    if expensivefixed:
        # Recalculate the LZ77 with ZopfliLZ77OptimalFixed
        instart = lz77.pos[lstart]
        inend = instart + lz77_get_byte_range(lz77, lstart, lend)

        s = BlockState(options, instart, inend, 1)
        squeeze.lz77_optimal_fixed(s, lz77.data, instart, inend, fixedstore)
        fixedcost = calculate_block_size(fixedstore, 0, fixedstore.size, 1)

    if uncompressedcost < fixedcost and uncompressedcost < dyncost:
        add_lz77_block(options, 0, final, lz77, lstart, lend,
                       expected_data_size, w)
    elif fixedcost < dyncost:
        if expensivefixed:
            add_lz77_block(options, 1, final, fixedstore, 0, fixedstore.size,
                           expected_data_size, w)
        else:
            add_lz77_block(options, 1, final, lz77, lstart, lend,
                           expected_data_size, w)
    else:
        add_lz77_block(options, 2, final, lz77, lstart, lend,
                       expected_data_size, w)


def deflate_part(options, btype, final, in_, instart, inend, w):
    """Port of ZopfliDeflatePart (deflate.c).

    Deflate a part, to allow deflate() to use multiple master blocks if needed.
    If instart is larger than 0, then previous bytes are used as the initial
    dictionary for LZ77. If final is 1, then the final bit will be set on the
    last block.
    """
    # byte coordinates rather than lz77 index
    splitpoints_uncompressed = []
    npoints = 0
    splitpoints = []
    totalcost = 0.0

    # If btype=2 is specified, it tries all block types. If a lesser btype is
    # given, then however it forces that one. Neither of the lesser types needs
    # block splitting as they have no dynamic huffman trees.
    if btype == 0:
        add_non_compressed_block(options, final, in_, instart, inend, w)
        return
    elif btype == 1:
        store = LZ77Store(in_)
        s = BlockState(options, instart, inend, 1)

        squeeze.lz77_optimal_fixed(s, in_, instart, inend, store)
        add_lz77_block(options, btype, final, store, 0, store.size, 0, w)
        return

    if options.blocksplitting:
        # C: the int blocksplittingmax is converted to the size_t maxblocks
        # parameter, so a negative value becomes huge (= no limit).
        splitpoints_uncompressed = blocksplitter.block_split(
            options, in_, instart, inend,
            options.blocksplittingmax & _SIZE_T_MASK)
        npoints = len(splitpoints_uncompressed)
        splitpoints = [0] * npoints

    lz77 = LZ77Store(in_)

    for i in range(npoints + 1):
        start = instart if i == 0 else splitpoints_uncompressed[i - 1]
        end = inend if i == npoints else splitpoints_uncompressed[i]
        store = LZ77Store(in_)
        s = BlockState(options, start, end, 1)
        squeeze.lz77_optimal(s, in_, start, end, options.numiterations, store)
        totalcost += calculate_block_size_auto_type(store, 0, store.size)

        append_lz77_store(store, lz77)
        if i < npoints:
            splitpoints[i] = lz77.size

    # Second block splitting attempt
    if options.blocksplitting and npoints > 1:
        totalcost2 = 0.0

        splitpoints2 = blocksplitter.block_split_lz77(
            options, lz77, options.blocksplittingmax & _SIZE_T_MASK)
        npoints2 = len(splitpoints2)

        for i in range(npoints2 + 1):
            start = 0 if i == 0 else splitpoints2[i - 1]
            end = lz77.size if i == npoints2 else splitpoints2[i]
            totalcost2 += calculate_block_size_auto_type(lz77, start, end)

        if totalcost2 < totalcost:
            splitpoints = splitpoints2
            npoints = npoints2

    for i in range(npoints + 1):
        start = 0 if i == 0 else splitpoints[i - 1]
        end = lz77.size if i == npoints else splitpoints[i]
        add_lz77_block_auto_type(options, 1 if (i == npoints and final) else 0,
                                 lz77, start, end, 0, w)


def deflate(options, btype, final, in_, insize, w):
    """Port of ZopfliDeflate (deflate.c), with ZOPFLI_MASTER_BLOCK_SIZE != 0.

    Compresses in_[0:insize] and appends the deflate stream to the BitWriter w
    (C: bp, out, outsize).
    """
    offset = len(w.out)
    i = 0
    while True:  # C: do { ... } while (i < insize);
        masterfinal = i + ZOPFLI_MASTER_BLOCK_SIZE >= insize
        final2 = 1 if (final and masterfinal) else 0
        size = insize - i if masterfinal else ZOPFLI_MASTER_BLOCK_SIZE
        deflate_part(options, btype, final2, in_, i, i + size, w)
        i += size
        if not i < insize:
            break
    if options.verbose:
        outsize = len(w.out) - offset
        # C: 100.0 * (double)(insize - (*outsize - offset)) / (double)insize,
        # with size_t (wrapping) subtraction.
        removed = _c_div(100.0 * float((insize - outsize) & _SIZE_T_MASK),
                         float(insize))
        sys.stderr.write(
            "Original Size: %d, Deflate: %d, Compression: %s%% Removed\n"
            % (insize & _SIZE_T_MASK, outsize & _SIZE_T_MASK,
               _c_percent_f(removed)))


def _c_int(x):
    """C (int) cast of a size_t value (two's complement truncation to 32 bits).

    Helper for the verbose messages. Not a C function.
    """
    x &= 0xFFFFFFFF
    return x - 0x100000000 if x & 0x80000000 else x


def _c_div(a, b):
    """C double division a / b, including IEEE results for b == 0.

    Helper for the verbose messages. Not a C function.
    """
    if b == 0.0:
        if a != a or a == 0.0:
            return float("nan")
        return float("inf") if a > 0 else float("-inf")
    return a / b


def _c_percent_f(x):
    """Formats a double like C printf("%f"). Not a C function.

    glibc prints the x86 default NaN (0.0/0.0) as "-nan".
    """
    if x != x:
        return "-nan"
    return "%f" % x
