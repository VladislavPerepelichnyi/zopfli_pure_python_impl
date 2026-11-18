# Porting notes: squeeze.c and blocksplitter.c

Modules: `zopfli_pure/squeeze.py`, `zopfli_pure/blocksplitter.py`.
Tests: `tests/test_squeeze.py`, `tests/test_blocksplitter.py` (helpers in
`tests/_squeeze_harness.py`). C oracle: `tools/harness/squeeze/harness.c`, built by
`tools/harness/squeeze/build.py` into `tools/build/squeeze_harness`.

## Interfaces

Public functions follow PORTING_SPEC.md. Static helpers keep their C names in
snake_case. Where the C uses out-parameters or dynamic arrays:

| C | Python |
|---|---|
| `SymbolStats`, `RanState` structs | classes `SymbolStats`, `RanState` (`__init__` = `InitStats` / `InitRanState`) |
| `GetBestLengths(..., length_array, h, costs)` | same order; `length_array` is a list, `costs` an `array('f')`, both filled in place; returns the cost |
| `TraceBackwards(size, length_array, &path, &pathsize)` | `trace_backwards(size, length_array, path)`; `path` is a list, appended to then reversed in place |
| `FollowPath(s, in, instart, inend, path, pathsize, store, h)` | same signature (`path` a list) |
| `LZ77OptimalRun(s, in, instart, inend, &path, &pathsize, length_array, costmodel, costcontext, store, h, costs)` | `lz77_optimal_run(s, in_, instart, inend, path, length_array, costmodel, costcontext, store, h, costs)`; `path` is emptied and refilled |
| `FindMinimum(f, context, start, end, &smallest)` | `find_minimum(f, context, start, end) -> (index, smallest)` |
| `AddSorted(value, &out, &outsize)` | `add_sorted(value, out)` (list, in place) |
| `FindLargestSplittableBlock(..., &lstart, &lend)` | returns `(found, lstart, lend)` (`None`s when not found; the C leaves the out-parameters unchanged, and the caller then breaks out without using them) |
| `ZopfliBlockSplitLZ77` / `ZopfliBlockSplit` / `ZopfliBlockSplitSimple` | return the split point list (spec) |

`squeeze` calls `deflate.calculate_block_size` and `blocksplitter` calls
`deflate.calculate_block_size_auto_type` through the module object, because
`deflate` imports both modules (import cycle, see the spec).

## Floating point

* `costs` is `array('f')`: every store rounds the double to float32 (C `(float)` cast,
  round to nearest even). Every read gives back the float32 value as a double. All other
  arithmetic is double, in the C order:
  * literal: `costmodel(in[i], 0) + costs[j]`;
  * match: `newCost = costmodel(k, sublen[k]) + costs[j]`, then `newCost < costs[j+k]`
    (double vs the float read back), then the store rounds;
  * pruning: `costs[j+k] <= mincost + costs[j]` (float read back vs double);
  * shortcut: `costs[j+258] = costs[j] + symbolcost`.
  `ZOPFLI_LARGE_FLOAT` (1e30) stored into `costs` becomes the float32 nearest to 1e30
  (`0x1.93e594p+99`), exactly as in C.
* `GetCostStat` for a match is `lbits + dbits + ll_symbols[lsym] + d_symbols[dsym]`:
  `(int + int)`, then `+ double`, then `+ double`. The specialised loop computes
  `len_extra[k] + db + len_llcost[k] + dc + cj`, Python's left-to-right evaluation of
  which is the same sequence `(((lbits + dbits) + ll) + d) + costs[j]`.
  `len_llcost[k]` is just `ll_symbols[LENGTH_SYMBOL[k]]` looked up once per call (no
  arithmetic is moved).
* `GetCostFixed` returns integers converted to double, so summing the integer parts in
  any order is exact; only the final `+ costs[j]` rounds.
* `AddWeighedStatFreqs`: `(size_t)(a * 1.0 + b * 0.5)`; Python `int()` truncates like
  the C cast for these non-negative values.
* Verbose `(int) cost` is `int(cost)` (truncation).

## Performance choices in `get_best_lengths`

`get_best_lengths` dispatches on the cost model object: `get_cost_stat` and
`get_cost_fixed` get specialised loops with the cost model inlined, any other function
goes through a generic loop that calls it exactly like the C function pointer (tests
check that all three agree bit-for-bit). Other choices:

* lookup tables built at import from the `symbols` functions: length -> symbol and
  extra bits, distance (0..32768) -> symbol and extra bits, fixed-tree literal and
  length costs;
* in the match loop `GetCostStat` is evaluated in full for every `k`, as in C (an
  earlier version reused the distance-dependent terms while `sublen[k]` did not change;
  that was removed because it is a cache the C does not have);
* `costs[j]` is read once per position (`cj`); nothing writes `costs[j]` while position
  `j` is processed;
* the C `sublen[259]` is a stack array reused across positions without clearing; the
  port allocates one list per call and reuses it the same way.

`get_statistics` uses the same symbol tables. `follow_path` skips the assertion-only
`ZopfliVerifyLenDist` and the unused `total_length_test`.

## Things that are reproduced on purpose

* `length_array` and `costs` are allocated once per `lz77_optimal` call and reused
  across iterations, as in C (`GetBestLengths` re-initialises `costs[0..blocksize]` and
  `length_array[0]`).
* The PRNG is the Marsaglia multiply-with-carry with `m_w = 1`, `m_z = 2`. `m_z` and
  `m_w` never exceed 32 bits, so only the returned `(m_z << 16) + m_w` is masked.
* `lastcost` starts at 0, `bestcost` at 1e30; randomisation happens when `i > 5` and
  the block cost (an exact double) equals the previous one.
* `FindMinimum` keeps the `NUM = 9` search, the `best > lastbest` stop (ties continue),
  the boundary updates and returns `pos = start` with `smallest = 1e30` if the first
  probe round is not better than 1e30.
* `FindLargestSplittableBlock` uses `lz77size - 1` as the end of the last block (see
  UPSTREAM_FINDINGS).

## Verification

See the test modules. In short: Ran sequence (20000 values), RandomizeStatFreqs (7 count
sets x 6 rounds), AddWeighedStatFreqs, both cost models on all literals and all lengths
x 57 distances plus GetCostModelMinCost (7 synthetic stat sets), CalculateStatistics,
TraceBackwards, FindMinimum on 7 synthetic functions x 11 ranges, then end to end against
the C harness: `GetBestLengths` (cost, full `length_array` and full `costs` array, both
models), `ZopfliLZ77Optimal` (per-iteration run cost and block cost, final store, for
1/2/5/15 iterations including the randomisation branch), `ZopfliLZ77OptimalFixed`,
`ZopfliBlockSplit` and `ZopfliBlockSplitLZ77` (maxblocks 0/1/3/15) and the verbose
stderr text, on empty/tiny/runs/periodic/text/random/mixed inputs, `instart > 0`, a
window start above 32 KiB, and a 40000-byte block.
