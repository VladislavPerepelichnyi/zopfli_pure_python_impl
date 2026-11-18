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

## 4. `squeeze.c:486` ZopfliLZ77Optimal with `numiterations <= 0` loses the data

The output store is only written inside the iteration loop (`if (cost < bestcost)
ZopfliCopyLZ77Store(...)`), so with `numiterations` 0 or negative the store stays empty
and `ZopfliDeflatePart` emits a block with no symbols. The stream decodes to nothing and
the zlib/gzip checksum does not match. Reproduced with the oracle:
`zopfli.zopfli.compress(b"hello world, hello world " * 40, numiterations=0)` gives 8
bytes that `zlib.decompress` rejects ("incorrect data check"). **Affects output.** The
port reproduces it (the store is left empty).

## 5. `squeeze.c:277` GetBestLengths: the literal guard `i + 1 <= inend` is always true

The loop runs while `i < inend`, and the long-repetition shortcut only advances `i` when
`i + ZOPFLI_MAX_MATCH * 2 + 1 < inend`. Dead check, no effect on output. The port drops it.

## 6. `squeeze.c:254-270` GetBestLengths: the long-repetition shortcut stores unconditionally

The `ZOPFLI_SHORTCUT_LONG_REPETITIONS` branch stores `costs[j + 258]` without the `<`
comparison used everywhere else in the DP, and skips the literal and match edges of the
258 positions it jumps over. The unconditional store is safe: positions processed before
the jump reach at most `j0 + 257`, so every overwritten entry still holds
`ZOPFLI_LARGE_FLOAT`. The skipped edges make the parse inside long runs an approximation
(by design). No effect on output; reproduced exactly.

## 7. `squeeze.c:346`, `:372-378` FollowPath: dead and assertion-only code

`total_length_test` is computed and never used; `ZopfliVerifyLenDist` and the
`dummy_length` assert only assert. No effect on output. The port omits them.

## 8. `squeeze.c:459` ZopfliLZ77Optimal: `beststats` may be read uninitialised

`beststats` is only written when an iteration improves on `bestcost =
ZOPFLI_LARGE_FLOAT`. Unreachable in practice (block costs are far below 1e30), so no
effect on output. The port initialises it to zeros.

## 9. `blocksplitter.c:204` FindLargestSplittableBlock: the last block ends at `lz77size - 1`

The first iteration of `ZopfliBlockSplitLZ77` uses `lend = lz77->size`, but every later
candidate for the last block stops one symbol short, so the final LZ77 symbol is excluded
from both the split search and the cost estimates of that block (and a last block of
exactly 10 symbols counts as 9, ending the search). Inconsistent and probably
unintended. **Affects which split points are chosen.** The port reproduces it.

## 10. `blocksplitter.c:251` ZopfliBlockSplitLZ77: `llpos == lend` can never be true

`FindMinimum` only returns indices in `[start, end)`. Dead condition, no effect on
output. The port keeps it (it is free).

## 11. `blocksplitter.c:156` PrintBlockSplitPoints: positions relative to the store start

The verbose split points are computed from `pos = 0`, whereas `ZopfliBlockSplit`
converts the same indices starting from `instart`. When called from `ZopfliDeflatePart`
with `instart > 0` (inputs above `ZOPFLI_MASTER_BLOCK_SIZE`), the printed positions are
offsets within the master block, not file positions. They are also printed through
`(int)` casts with `%d`/`%x`. Verbose output only; reproduced.

## 12. `blocksplitter.c:225` ZopfliBlockSplitLZ77: no verbose line for tiny stores

The early return for stores with fewer than 10 symbols comes before the verbose print,
so with `verbose` set such blocks print no "block split points" line. Verbose output
only; reproduced.
