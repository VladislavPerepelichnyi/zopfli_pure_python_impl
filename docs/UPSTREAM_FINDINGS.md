# Upstream findings

Bugs and questionable behaviour found in the reference C implementation
(google/zopfli @ df1517dd, = zopfli-1.0.3) while porting it.

Format of each entry: number, `file:line`, description, whether it affects output,
and how the Python port handles it (the port reproduces upstream output unless stated).


## 1. `katajainen.c:169` LeafComparator truncates a `size_t` difference to `int`

`LeafComparator` returns `((const Node*)a)->weight - ((const Node*)b)->weight`:
a `size_t` subtraction (mod 2^64) converted to `int` (gcc: the low 32 bits). The
weights being compared are the packed keys `(weight << 9) | symbol`, so as soon
as two used symbols' counts differ by about 2^22 (4,194,304) or more, the sign
of the comparison can be wrong and `qsort` receives an inconsistent comparator.
The leaf order (and so the code lengths) then depends on the libc's `qsort`
algorithm and can be suboptimal. Example, with glibc 2.39:
`ZopfliLengthLimitedCodeLengths({1, 1, 1 << 23, 1}, 4, 15, ...)` gives lengths
`2, 2, 2, 2` instead of the optimal `3, 3, 1, 2`.

**Affects output:** no. Zopfli only calls this (via `ZopfliCalculateBitLengths`
from `deflate.c`) with histogram counts of one LZ77 range inside a single
`ZOPFLI_MASTER_BLOCK_SIZE` (1,000,000 bytes) master block, so every count is at
most ~1,000,001 < 2^22, and code-length-code counts are at most 320.

**Port:** sorts by the exact packed key (correct order); the truncation is not
reproduced. `tests/test_tree.py::test_length_limited_comparator_truncation`
checks that C and Python only ever diverge when the counts are >= 2^22 apart.
(Note that the `weight << 9` shift itself cannot overflow: weights >= 2^55 are
rejected with return value 1 just before it, which the port reproduces.)

## 2. `katajainen.c:144`, `:157`, `:202` undefined behaviour for `maxbits` >= 16

`ExtractBitLengths` stores one count per list in `int counts[16]` and walks it
with `unsigned ptr`/`end`. When the effective number of lists
(`min(maxbits, numsymbols - 1)`) is 16, `end` reaches 0, `ptr >= end` is always
true and `counts[ptr - 1]` reads `counts[UINT_MAX]`; with 17 or more lists
`counts[--end]` writes before the array. Separately, `(1 << maxbits)` at line
202 is an `int` shift, undefined for `maxbits >= 31`.

**Affects output:** no. Zopfli only uses `maxbits` 15 and 7.

**Port:** raises `ValueError` when the effective `maxbits` exceeds 15 (instead
of undefined behaviour).

## 3. `tree.c:73` ZopfliCalculateEntropy sums `size_t` counts into an `unsigned`

`unsigned sum` (32-bit) accumulates `size_t` counts, so a total >= 2^32 wraps,
which would give negative "bit lengths" (and trip the `assert`). The loop index
is also `unsigned` while `n` is `size_t`.

**Affects output:** no. The only callers (`squeeze.c:393-394`) pass
`SymbolStats` counts of one master block: fresh histograms (<= 1,000,001 per
symbol), `AddWeighedStatFreqs(stats, 1.0, laststats, 0.5)` (keeps every entry
<= ~2,000,002) and `RandomizeFreqs` (copies existing entries). So the sum is at
most 288 * ~2,000,002 < 2^30.

**Port:** uses the exact (unbounded) sum; the wrap is not reproduced.

## 4. `deflate.c:760,786-792` AddLZ77BlockAutoType: the non-expensive fixed branch is dead code

`expensivefixed = (lz77->size < 1000) || fixedcost <= dyncost * 1.1`. When
`expensivefixed` is false, `fixedcost > dyncost * 1.1 >= dyncost` (costs are
positive), so `fixedcost < dyncost` is false and
`AddLZ77Block(options, 1, final, lz77, lstart, lend, ...)` (fixed tree on the
original store) can never run.

**Affects output:** no.

**Port:** keeps the branch as written.

## 5. `deflate.c:615,760` "small block" thresholds use the size of the whole store

`ZopfliCalculateBlockSizeAutoType` skips the fixed-tree cost when
`lz77->size > 1000`, and `AddLZ77BlockAutoType` forces the expensive fixed
recomputation when `lz77->size < 1000`. Both test the size of the whole store,
not of the block `[lstart, lend)`: in `ZopfliDeflatePart` that store is the
concatenation of every block of the master block, and in the block splitter it
is the whole store being split. So a tiny block inside a large input is never
considered "small", and the two thresholds disagree at exactly 1000 symbols
(`> 1000` vs `< 1000`). The comments ("for larger blocks", "Only do this for
small blocks") suggest the block size was meant.

**Affects output:** yes (it is the reference behaviour).

**Port:** reproduced exactly (`lz77.size`, same comparisons).

## 6. `deflate.c:598` ZopfliCalculateBlockSize(btype 0) of an empty range is 0 bits

For `lstart == lend`, `length == 0` gives `blocks == 0` and a cost of 0, less
than the 3 header bits any real block needs (fixed and dynamic costs include
them). `ZopfliCalculateBlockSizeAutoType` therefore returns 0 for empty ranges.

**Affects output:** no in practice: `AddLZ77BlockAutoType` special-cases
`lstart == lend` before using the costs, and the block splitter does not
evaluate empty ranges.

**Port:** reproduced.

## 7. Verbose statistics: `size_t` wrap and division by zero

`deflate.c:929`, `zlib_container.c:78`, `gzip_container.c:87` compute
`100.0 * (double)(insize - outsize) / (double)insize` with `size_t` operands,
so an output larger than the input prints a huge positive percentage (for
example `108510259257115017216.000000% Removed`), and an empty input prints
`inf`. The containers also print sizes with `%d` after `(int)` casts.

**Affects output:** only the `verbose` text on stderr.

**Port:** reproduces the text exactly (64-bit wrap, IEEE division by zero,
`(int)` truncation); checked against py-zopfli's stderr.

## 8. `zlib_container.c:55` adler32 gets `(unsigned)insize`

`adler32(in, (unsigned)insize)` truncates the length to 32 bits, so inputs of
4 GiB or more would get a checksum of a prefix only. (The adler32 itself never
overflows: its `5550`-byte chunks keep `s2` below 2^32.)

**Affects output:** only for inputs >= 4 GiB.

**Port:** reproduces the truncation (`insize & 0xFFFFFFFF`).
