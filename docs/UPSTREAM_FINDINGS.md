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
