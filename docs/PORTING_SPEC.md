# Porting spec: zopfli_pure

All implementers code against this document. Do not change an interface on your own:
if you need a change, explain it in your final report and the orchestrator will update
this file.

## Reference

* C source: `/home/vlad/thesis/wasm/pure_python_impl/zopfli_reference/src/zopfli/`
  (google/zopfli @ `df1517dd8518113a245e4d203a04b8a0e02ab493`, which is tag `zopfli-1.0.3`
  plus one cast in an error message).
* Oracle: `py-zopfli` 0.4.3 (`zopfli.zopfli.compress`), installed in
  `/home/vlad/thesis/wasm/pure_python_impl/zopfli_pure_python/.venv`. Its bundled C differs
  from the reference only by a `memcpy` change in `GetMatch` (`lz77.c`), and produces the same output.
* Build/compile flags are the defaults in `util.h`: `ZOPFLI_LONGEST_MATCH_CACHE`,
  `ZOPFLI_HASH_SAME`, `ZOPFLI_HASH_SAME_HASH`, `ZOPFLI_SHORTCUT_LONG_REPETITIONS`,
  `ZOPFLI_LAZY_MATCHING` are all **on**. Port only the code paths these flags enable.

## Goal

A faithful, function-by-function port. Output must be **byte-identical** to
`zopfli.zopfli.compress(data, ...)` for every input and option combination.
Faithful means the same algorithm, the same order of operations, the same tie-breaking,
the same floating-point arithmetic, and the same integer wrap-around behaviour where it
is observable. It does not mean the same memory management.

## Strict pure-Python rule

Code under `zopfli_pure/` may only import from the standard library, and of the standard
library only `math`, `array`, `sys`, `struct` (if needed), and modules of this package.
**Never** import `zlib`, `gzip`, `binascii`, `ctypes`, `cffi`, or any native compression
module in `zopfli_pure/`. Tests and `tools/` may use anything (`zlib` for round-trip
checks, `ctypes` for C harnesses, `zopfli` as the oracle).

## Conventions

* Package: `zopfli_pure/`, one module per C file, same name (see the table below).
* Names: C function `ZopfliFooBar` / static `FooBar` becomes `foo_bar` (snake_case, `zopfli_`
  prefix dropped). Struct `ZopfliFoo` becomes class `Foo` (e.g. `LZ77Store`, `BlockState`,
  `Hash`, `LongestMatchCache`, `Options`). Each Python function's docstring starts with
  the name of the C function it ports, e.g. `"""Port of ZopfliLZ77GetHistogram (lz77.c)."""`.
* Arrays: use plain Python `list` of `int` (fastest indexing in CPython) unless
  a C type's rounding matters (see the float note below). `unsigned char*` input data is `bytes`
  (or any object indexable to `int`, e.g. `bytes`/`bytearray`/`memoryview`).
* **Output-array parameters** (C `unsigned* bitlengths`, `size_t* ll_counts`, ...): the
  caller passes a pre-sized `list`; the callee fills it **in place**, like C.
  **Scalar out-parameters** (`unsigned short* distance`, `size_t* npoints`, ...): returned
  as the return value (a tuple if there are several, in C parameter order, after the C
  return value if any).
* Dynamic arrays grown with `ZOPFLI_APPEND_DATA` become `list.append`.
* `size_t`/`unsigned` arithmetic: if a C expression can wrap (subtraction of unsigned values,
  `unsigned int` multiplications in the PRNG), reproduce the wrap with explicit masking
  (`& 0xFFFFFFFF`, `& 0xFFFFFFFFFFFFFFFF`) **if and only if the wrap is reachable**. Where it is
  reachable and looks like a bug, add an entry to `docs/UPSTREAM_FINDINGS.md`.
* `verbose` output goes to `sys.stderr` with the same text as the C `fprintf(stderr, ...)`.
* Speed matters (this library is benchmarked later against C/WASM builds), but faithfulness
  matters more. Use idiomatic fast CPython: bind attributes and globals to locals in hot
  loops, avoid per-element method calls and small object allocation, use lookup tables
  instead of branches where the C does the same. Do not add caches or shortcuts the C does not have.

### Floating point

* C `double` is Python `float`. `log` is `math.log` (both call libm). Keep the C
  evaluation order: `a * b * c` is `(a * b) * c`. Do not "simplify" constants (for example
  keep `kInvLog2 = 1.4426950408889`, not `1/math.log(2)`).
* **C `float` (32-bit) must be emulated.** `squeeze.c` stores path costs in
  `float* costs`: use `array.array('f', ...)` so every store rounds to float32, and compare
  the `double` value with the value read back, exactly as C does.
* x86-64 SSE2 semantics are assumed (no x87 extended precision, no FMA contraction).

## Module ownership and public interfaces

| Module | Ports | Owner |
|---|---|---|
| `zopfli_pure/util.py` | `util.h`/`util.c`, `zopfli.h` (`Options`, constants) | A |
| `zopfli_pure/symbols.py` | `symbols.h` | A |
| `zopfli_pure/hash.py` | `hash.c` | A |
| `zopfli_pure/cache.py` | `cache.c` | A |
| `zopfli_pure/lz77.py` | `lz77.c` | A |
| `zopfli_pure/katajainen.py` | `katajainen.c` | B |
| `zopfli_pure/tree.py` | `tree.c` | B |
| `zopfli_pure/bitwriter.py` | `AddBit`, `AddBits`, `AddHuffmanBits` from `deflate.c` | B |
| `zopfli_pure/squeeze.py` | `squeeze.c` | C |
| `zopfli_pure/blocksplitter.py` | `blocksplitter.c` | C |
| `zopfli_pure/deflate.py` | `deflate.c` (rest) | D |
| `zopfli_pure/zlib_container.py` | `zlib_container.c` (incl. `adler32`) | D |
| `zopfli_pure/gzip_container.py` | `gzip_container.c` (incl. CRC32) | D |
| `zopfli_pure/zopfli_lib.py` | `zopfli_lib.c` | D |
| `zopfli_pure/__init__.py` | public API `compress(...)` | D |
| `tests/`, `tools/` (C harnesses) | | T (testers); implementers may add `tests/test_<module>.py` and `tools/harness/<module>/` for their own modules |

### util.py (A)
```python
ZOPFLI_MAX_MATCH = 258; ZOPFLI_MIN_MATCH = 3; ZOPFLI_NUM_LL = 288; ZOPFLI_NUM_D = 32
ZOPFLI_WINDOW_SIZE = 32768; ZOPFLI_WINDOW_MASK = 32767; ZOPFLI_MASTER_BLOCK_SIZE = 1000000
ZOPFLI_LARGE_FLOAT = 1e30; ZOPFLI_CACHE_LENGTH = 8; ZOPFLI_MAX_CHAIN_HITS = 8192
class Options:                       # ZopfliOptions + ZopfliInitOptions defaults
    verbose = 0; verbose_more = 0; numiterations = 15
    blocksplitting = 1; blocksplittinglast = 0; blocksplittingmax = 15
    def __init__(self, verbose=0, verbose_more=0, numiterations=15, blocksplitting=1,
                 blocksplittinglast=0, blocksplittingmax=15): ...
ZOPFLI_FORMAT_GZIP = 0; ZOPFLI_FORMAT_ZLIB = 1; ZOPFLI_FORMAT_DEFLATE = 2
```

### symbols.py (A)
`get_dist_extra_bits(dist)`, `get_dist_extra_bits_value(dist)`, `get_dist_symbol(dist)`,
`get_length_extra_bits(l)`, `get_length_extra_bits_value(l)`, `get_length_symbol(l)`,
`get_length_symbol_extra_bits(s)`, `get_dist_symbol_extra_bits(s)`. Also export the lookup
tables as module-level lists (`LENGTH_SYMBOL`, `LENGTH_EXTRA_BITS`, `LENGTH_EXTRA_BITS_VALUE`,
`LENGTH_SYMBOL_EXTRA_BITS` (index s-257), `DIST_SYMBOL_EXTRA_BITS`, and a fast
`get_dist_symbol`) so hot loops in other modules can index them directly.

### hash.py (A)
```python
class Hash:   # fields: head, prev, hashval, val, head2, prev2, hashval2, val2, same (lists / int)
    def __init__(self, window_size): ...      # ZopfliAllocHash + ZopfliResetHash
def reset_hash(window_size, h): ...
def update_hash(array, pos, end, h): ...
def warmup_hash(array, pos, end, h): ...
```

### cache.py (A)
```python
class LongestMatchCache:   # fields length, dist (lists), sublen (bytearray of 8*3*blocksize)
    def __init__(self, blocksize): ...        # ZopfliInitCache
def sublen_to_cache(sublen, pos, length, lmc): ...
def cache_to_sublen(lmc, pos, length, sublen): ...
def max_cached_sublen(lmc, pos, length) -> int: ...
```

### lz77.py (A)
```python
class LZ77Store:
    # fields: litlens, dists, pos, ll_symbol, d_symbol, ll_counts, d_counts (lists), data
    # property / attribute `size` == len(litlens) (keep it consistent)
    def __init__(self, data): ...              # ZopfliInitLZ77Store
def copy_lz77_store(source, dest): ...          # dest is an existing LZ77Store, overwritten
def store_lit_len_dist(length, dist, pos, store): ...
def append_lz77_store(store, target): ...
def lz77_get_byte_range(lz77, lstart, lend) -> int: ...
def lz77_get_histogram(lz77, lstart, lend, ll_counts, d_counts): ...   # fills 288/32 lists
class BlockState:
    def __init__(self, options, blockstart, blockend, add_lmc): ...  # lmc is None if not add_lmc
def find_longest_match(s, h, array, pos, size, limit, sublen) -> (distance, length)
    # sublen: list of >= 259 ints, or None
def verify_len_dist(data, datasize, pos, dist, length): ...  # assertion helper
def lz77_greedy(s, in_, instart, inend, store, h): ...
```

### katajainen.py (B)
`length_limited_code_lengths(frequencies, n, maxbits, bitlengths) -> int` (0 = OK).

### tree.py (B)
```python
def calculate_bit_lengths(count, n, maxbits, bitlengths): ...
def lengths_to_symbols(lengths, n, maxbits, symbols): ...
def calculate_entropy(count, n, bitlengths): ...
```

### bitwriter.py (B)
The C code threads `unsigned char* bp` (bit pointer, 0..7) and a growing `out` buffer.
In Python both live in one object:
```python
class BitWriter:
    def __init__(self, out=None, bp=0): ...   # self.out: bytearray, self.bp: int
    def add_bit(self, bit): ...               # AddBit
    def add_bits(self, symbol, length): ...   # AddBits
    def add_huffman_bits(self, symbol, length): ...  # AddHuffmanBits
```
Hot loops may inline these, but the bit layout must be identical.

### squeeze.py (C)
```python
def lz77_optimal(s, in_, instart, inend, numiterations, store): ...
def lz77_optimal_fixed(s, in_, instart, inend, store): ...
```
Internal helpers keep their C names in snake_case (`get_best_lengths`, `trace_backwards`,
`follow_path`, `ran`, `randomize_freqs`, `get_cost_fixed`, `get_cost_stat`, ...).

### blocksplitter.py (C)
```python
def block_split_lz77(options, lz77, maxblocks) -> list   # splitpoints (LZ77 indices)
def block_split(options, in_, instart, inend, maxblocks) -> list   # byte indices
def block_split_simple(in_, instart, inend, blocksize) -> list
```
(The list return replaces `size_t** splitpoints, size_t* npoints`.)

### deflate.py (D)
```python
def deflate(options, btype, final, in_, insize, w): ...   # ZopfliDeflate; w: BitWriter
def deflate_part(options, btype, final, in_, instart, inend, w): ...
def calculate_block_size(lz77, lstart, lend, btype) -> float
def calculate_block_size_auto_type(lz77, lstart, lend) -> float
def optimize_huffman_for_rle(length, counts): ...   # public in C too
```

### zlib_container.py / gzip_container.py / zopfli_lib.py / __init__.py (D)
```python
def zlib_compress(options, in_) -> bytes          # ZopfliZlibCompress
def gzip_compress(options, in_) -> bytes          # ZopfliGzipCompress
def compress_format(options, output_type, in_) -> bytes   # ZopfliCompress
# zopfli_pure/__init__.py
def compress(data, verbose=0, numiterations=15, blocksplitting=1,
             blocksplittinglast=0, blocksplittingmax=15, gzip_mode=0) -> bytes
```
`compress` mirrors py-zopfli's `zopfli.zopfli.compress` (`src/zopflimodule.c`): it accepts
`str` (encoded as UTF-8, like the `s#` format) and read-only bytes-like objects, and builds
options with `ZopfliInitOptions` defaults overridden by the keyword arguments.
Also accept `bytearray`/`memoryview` (a deliberate, harmless extension).

## Import cycles

`deflate` imports `blocksplitter` and `squeeze`; `blocksplitter` imports `deflate`
(`calculate_block_size_auto_type`). Resolve this with module imports
(`from . import deflate` and calling `deflate.calculate_block_size_auto_type` at run time),
not `from .deflate import ...` at module top level.

## Git workflow

* `main` is integration-only (orchestrator merges). Each agent works on its own branch in
  its own worktree under `/home/vlad/thesis/wasm/pure_python_impl/zopfli_wt/<branch>`.
* Commit often, with small, descriptive commits. Do **not** push and do **not** merge into
  `main`: the orchestrator does that. You may `git merge main` into your branch to pick up
  other modules.
* Commit messages end with the line
  `Claude-Session: https://claude.ai/code/session_014Pazkfrgez2Qg1CARRSHjm`.
* Python: `/home/vlad/thesis/wasm/pure_python_impl/zopfli_pure_python/.venv/bin/python`
  (has `pytest`, `hypothesis`, `zopfli`). Run it from your worktree root so `zopfli_pure`
  imports from your worktree.
* Upstream bugs or questionable behaviour go in `docs/UPSTREAM_FINDINGS.md` (append a
  numbered entry: file:line, description, whether it affects output, how the port handles it).
  Porting notes go in `docs/notes/<module>.md`.
