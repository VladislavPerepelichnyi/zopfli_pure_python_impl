# Upstream findings

Bugs and questionable behaviour found in the reference C implementation
(google/zopfli @ df1517dd, = zopfli-1.0.3) while porting it.

Format of each entry: number, `file:line`, description, whether it affects output,
and how the Python port handles it (the port reproduces upstream output unless stated).


## squeeze.c / blocksplitter.c (agent C)

Numbered locally for this section; the orchestrator may renumber on merge.

1. **`squeeze.c:486` (`ZopfliLZ77Optimal`): `numiterations <= 0` loses the data.**
   The output store is only written inside the iteration loop (`if (cost < bestcost)
   ZopfliCopyLZ77Store(...)`), so with `numiterations` 0 or negative the store stays
   empty and `ZopfliDeflatePart` emits a block with no symbols. The compressed stream
   decodes to nothing and the zlib/gzip checksum does not match. Reproduced with the
   oracle: `zopfli.zopfli.compress(b"hello world, hello world " * 40, numiterations=0)`
   gives 8 bytes that `zlib.decompress` rejects ("incorrect data check"). Affects output.
   The port reproduces it (the store is left empty).

2. **`squeeze.c:277` (`GetBestLengths`): the literal guard `if (i + 1 <= inend)` is
   always true.** The loop runs while `i < inend`, and the long-repetition shortcut only
   advances `i` when `i + ZOPFLI_MAX_MATCH * 2 + 1 < inend`. Dead check, no effect on
   output. The port drops it.

3. **`squeeze.c:254-270` (`GetBestLengths`, `ZOPFLI_SHORTCUT_LONG_REPETITIONS`): the
   shortcut stores `costs[j + 258]` unconditionally** (no `<` comparison as in the rest
   of the DP), and it skips the literal and match edges of the 258 positions it jumps
   over. The unconditional store is safe: positions processed before the jump reach at
   most `j0 + 257`, so every overwritten entry still holds `ZOPFLI_LARGE_FLOAT`. The
   skipped edges make the "optimal" parse an approximation inside long runs (by design).
   No output difference vs. the intent; the port reproduces it exactly.

4. **`squeeze.c:346,372-378` (`FollowPath`): `total_length_test` is computed and never
   used, and `ZopfliVerifyLenDist` / the `dummy_length` assert are assertion-only.**
   No effect on output. The port omits them.

5. **`squeeze.c:459` (`ZopfliLZ77Optimal`): `beststats` is read uninitialised if no
   iteration improves on `bestcost = ZOPFLI_LARGE_FLOAT`.** Unreachable in practice
   (every block cost is far below 1e30), so no effect on output. The port initialises it
   to zeros.

6. **`blocksplitter.c:204` (`FindLargestSplittableBlock`): the last block ends at
   `lz77size - 1`, not `lz77size`.** The first iteration of `ZopfliBlockSplitLZ77` uses
   `lend = lz77->size`, but every later candidate for the last block stops one symbol
   short, so the final LZ77 symbol is excluded from both the split search and the cost
   estimates of that block (and a last block of exactly 10 symbols counts as 9, ending
   the search). Inconsistent and probably unintended; affects which split points are
   chosen. The port reproduces it.

7. **`blocksplitter.c:251` (`ZopfliBlockSplitLZ77`): `llpos == lend` can never be
   true.** `FindMinimum` only returns indices in `[start, end)`. Dead condition, no
   effect on output. The port keeps it (it is free).

8. **`blocksplitter.c:156` (`PrintBlockSplitPoints`): the verbose split points are
   relative to the start of the LZ77 store (`pos = 0`), whereas `ZopfliBlockSplit`
   converts the same indices starting from `instart`.** When called from
   `ZopfliDeflatePart` with `instart > 0` (e.g. inputs above `ZOPFLI_MASTER_BLOCK_SIZE`),
   the printed positions are offsets within the master block, not file positions. They
   are also printed through `(int)` casts with `%d`/`%x`. Affects verbose output only.
   The port reproduces it.

9. **`blocksplitter.c:225`: `ZopfliBlockSplitLZ77` returns early for stores with fewer
   than 10 symbols, before the verbose print**, so with `verbose` set small blocks print
   no "block split points" line at all. Verbose output only; reproduced.
