# Porting notes: katajainen.c, tree.c, bit writers (implementer B)

Modules: `zopfli_pure/katajainen.py`, `zopfli_pure/tree.py`,
`zopfli_pure/bitwriter.py`. Verified against the reference C with
`tests/test_tree.py` (harness: `tools/harness/tree/harness.c`).

## katajainen.py

Public: `length_limited_code_lengths(frequencies, n, maxbits, bitlengths) -> int`
(fills `bitlengths[0:n]` in place, returns 0 OK / 1 error). Private helpers keep
the C names: `_init_node`, `_boundary_pm`, `_boundary_pm_final`, `_init_lists`,
`_extract_bit_lengths`.

### Data structures

* **Nodes** are tuples `(weight, count, tail)`. C mutates a node in exactly one
  place: `BoundaryPMFinal`'s else branch sets `lists[maxbits-1][1]->tail`. That
  node is only referenced from `lists` (tails always point into a lower list,
  and it is never the shared `InitLists` node because at least one
  `BoundaryPM` run on the last list replaced it), so the port replaces it with a
  modified copy. In the other branch C takes the next pool node without
  setting its `weight` (uninitialized memory); that weight is never read
  (`ExtractBitLengths` reads only `count` and `tail`), the port stores `None`.
* **Node pool**: C pre-allocates `maxbits * 2 * numsymbols` nodes and only
  bumps a pointer (this version has no garbage collection), so plain allocation
  is equivalent.
* **Lists**: `lists[i][1]` is `l1[i]`. Of `lists[i][0]` only the weight is ever
  read (`lists[index-1][0]->weight`), so the port keeps `l0w[i]`, that weight.
* **Leaves** are two parallel lists after sorting: `leaf_weight`, `leaf_count`
  (symbol index). `leaf_weight` has one sentinel entry `1 << 80` at index
  `numsymbols`; chain weights are sums of distinct leaf weights (< 2^55 each,
  n <= 288), so `sum > leaf_weight[lastcount]` is false exactly when the C guard
  `lastcount < numsymbols` is false (`lastcount` never exceeds `numsymbols`).
* **Recursion**: `BoundaryPM` ends with two calls `BoundaryPM(index - 1)` and does
  no work after them, so an explicit LIFO stack (push `index - 1` twice)
  reproduces the exact call order. The `2 * numsymbols - 5` consecutive
  top-level calls are pushed up front as copies of `maxbits - 1`: the stack is
  always non-increasing from bottom to top, and each top-level call is fully
  processed before the next is popped.

### Leaf sort

C packs `weight << 9 | symbol` into the `size_t` weight, `qsort`s with
`LeafComparator`, then shifts back with `>> 9`. The port sorts
`((w << 9) | i, i)` tuples and recovers the weight as `packed >> 9`; for
n <= 512 the keys are distinct, so any correct sort gives the C order
(including all ties of equal weights, broken by symbol index). For n > 512
(unreachable) the tuple sort also matches C: `>> 9` then yields `w | (i >> 9)`
like C, and equal packed keys stay in input order like glibc's merge sort.

* `weight << 9` cannot overflow: C first rejects weights >= 2^55 with return
  value 1 (bitlengths stay all 0). Ported.
* The comparator itself truncates the 64-bit difference to `int`
  (UPSTREAM_FINDINGS #1): for counts >= ~2^22 apart, C's order is wrong and
  libc-dependent. Unreachable from zopfli (counts <= ~1e6); not reproduced.
* Weight sums cannot overflow `size_t` for n <= 511 (each chain is a set of
  distinct leaves, each < 2^55), so Python's unbounded ints match.

### ExtractBitLengths

Ported literally (`counts[16]`, walk from the last list down). Undefined in C
when the effective `maxbits` (`min(maxbits, numsymbols - 1)`) is >= 16; the
port raises `ValueError` there (UPSTREAM_FINDINGS #2). Zopfli uses 15 and 7.

### Special cases (ported in C order)

zero bitlengths; `(1 << maxbits) < numsymbols` -> 1; 0 symbols -> 0; 1 symbol ->
length 1; 2 symbols -> `++` on both; any weight >= 2^55 -> 1 (checked after the
2-symbol case, as in C).

## tree.py

* `calculate_bit_lengths`: wraps `length_limited_code_lengths`; C's
  `assert(!error)` becomes `raise AssertionError` (unreachable from zopfli:
  288 <= 2^15, 19 <= 2^7, weights < 2^55).
* `lengths_to_symbols`: literal port, `bl_count` / `next_code` of size
  `maxbits + 1`, `bl_count[0] = 0` after counting. C's `assert(lengths[i] <=
  maxbits)` becomes a natural `IndexError`. `code` is `unsigned` in C; with
  maxbits <= 15 and n <= 288 it stays below ~2^24, so no masking.
  Over-subscribed length sets are handled exactly like C (codes simply exceed
  their length).
* `calculate_entropy`: `kInvLog2 = 1.4426950408889` kept, same expression order
  (`log2sum - log(count) * kInvLog2`, `log(sum) * kInvLog2`). `sum == 0` uses
  `log(n)`; for `n == 0` C computes `log(0) = -inf` and never uses it, the port
  avoids `math.log(0)` (which raises) and uses `-inf`. The clamp
  (`-1e-5 < b < 0` -> `0.0`) is applied only on the `count != 0` branch, which is
  equivalent: on the `count == 0` branch `b = log2sum >= 0`. The C `unsigned`
  32-bit sum is not wrapped (UPSTREAM_FINDINGS #3, unreachable).
  `math.log` on an `int` converts it to `double` and calls libm `log`, as C
  does for `size_t`/`unsigned` arguments (exact below 2^53).

## bitwriter.py

`BitWriter(out=None, bp=0)` with `out` (bytearray) and `bp` (0..7), methods
`add_bit`, `add_bits`, `add_huffman_bits`. C writes one bit per iteration; the
port writes whole groups:

1. If `bp != 0`, OR the low bits into the last byte (C also ORs, so pre-existing
   high bits in a caller-provided last byte are kept, and stores truncate to 8
   bits: `add_bit(2)` at `bp == 7` writes nothing, like C).
2. Then append whole bytes, then a final partial byte. A new byte is appended
   only when a bit is actually written at `bp == 0`, exactly as C's
   `if (*bp == 0) ZOPFLI_APPEND_DATA(0, ...)`; writing 0 bits appends nothing.

`add_huffman_bits` reverses the low `length` bits (via an 8-bit reversal table
for `length <= 16`) and then writes them LSB first, which is C's MSB-first
order. Only the low `length` bits of `symbol` are used, like C. Lengths >= 32
(C shift UB) are unreachable and not special-cased.

## Verification (tests/test_tree.py)

The harness compiles the unmodified reference sources (with `deflate.c`
`#include`d for its static bit writers) with `-O2 -ffp-contract=off`
(`-march=x86-64 -mno-fma` on x86-64) into `tools/build/tree/` and calls it via
ctypes.

* `length_limited_code_lengths`: 3,850 cases over (n, maxbits) in
  {(288,15), (32,15), (19,7), (288,7), (32,7)} x 11 generators (zero, one, two,
  sparse, dense, all-equal weights, few distinct values, Fibonacci, geometric,
  large counts up to 2^55 - 1 with spread < 2^22, realistic block histograms),
  plus 3,000 cases with random n in 0..39 and maxbits in 0..15 (including error
  returns), plus the >= 2^55 error path and the comparator-truncation region.
* `calculate_bit_lengths`: 1,500 cases at the zopfli configurations.
* `lengths_to_symbols`: 3,000 cases (valid complete codes and arbitrary,
  possibly over-subscribed, lengths).
* `calculate_entropy`: 4,000 random vectors plus all counts 0..5000 in three
  layouts (15,003 vectors); every value compared with `float.hex()`.
* `BitWriter`: 3,000 random sequences of up to 60 mixed operations (lengths
  0..32, non-0/1 bits for `add_bit`, initial buffers with arbitrary bytes and
  any `bp`); bytes and final `bp` compared.

Speed (CPython 3.12): `length_limited_code_lengths` ~0.7 ms for 288 dense
symbols, ~50 us for 32, ~20 us for 19; bit writer ~0.2 us per call.

A one-off extended fuzz run (20 seeds, 9 (n, maxbits) configurations x 11
generators, not part of the committed suite) also matched C on 79,200
`length_limited_code_lengths` cases (plus `lengths_to_symbols` on each
result), 10,000 entropy vectors and 6,000 bit writer sequences.
