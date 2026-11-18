# Porting notes: deflate.py, zlib_container.py, gzip_container.py, zopfli_lib.py, `__init__.py`

## Scope

`zopfli_pure/deflate.py` ports all of `deflate.c` except `AddBit`, `AddBits`,
`AddHuffmanBits` (in `bitwriter.py`, agent B). Function map (C → Python):

| C | Python |
|---|---|
| `PatchDistanceCodesForBuggyDecoders` | `patch_distance_codes_for_buggy_decoders` |
| `EncodeTree` | `encode_tree(ll_lengths, d_lengths, use_16, use_17, use_18, w)`; `w=None` is size-only mode |
| `AddDynamicTree` | `add_dynamic_tree(ll_lengths, d_lengths, w)` |
| `CalculateTreeSize` | `calculate_tree_size` |
| `AddLZ77Data` | `add_lz77_data(lz77, lstart, lend, expected_data_size, ll_symbols, ll_lengths, d_symbols, d_lengths, w)` |
| `GetFixedTree` | `get_fixed_tree` |
| `CalculateBlockSymbolSizeSmall` / `GivenCounts` / (plain) | `calculate_block_symbol_size_small` / `_given_counts` / `calculate_block_symbol_size` |
| `AbsDiff` | `abs_diff` |
| `OptimizeHuffmanForRle` | `optimize_huffman_for_rle(length, counts)` (in place) |
| `TryOptimizeHuffmanForRle` | `try_optimize_huffman_for_rle` |
| `GetDynamicLengths` | `get_dynamic_lengths` |
| `ZopfliCalculateBlockSize` | `calculate_block_size` (returns `float`) |
| `ZopfliCalculateBlockSizeAutoType` | `calculate_block_size_auto_type` |
| `AddNonCompressedBlock` | `add_non_compressed_block(options, final, in_, instart, inend, w)` |
| `AddLZ77Block` | `add_lz77_block(options, btype, final, lz77, lstart, lend, expected_data_size, w)` |
| `AddLZ77BlockAutoType` | `add_lz77_block_auto_type(...)` (same parameters, minus `btype`) |
| `ZopfliDeflatePart` | `deflate_part(options, btype, final, in_, instart, inend, w)` |
| `ZopfliDeflate` | `deflate(options, btype, final, in_, insize, w)` |

`bp, out, outsize` are always the `BitWriter` `w` (`w.out` bytearray, `w.bp`);
`*outsize` is `len(w.out)`.

Containers: `zlib_container.adler32(data, size)`, `zlib_compress(options, in_)`,
`gzip_container.crc(data, size)` and `CRC32_TABLE`, `gzip_compress(options, in_)`,
`zopfli_lib.compress_format(options, output_type, in_)`, `zopfli_pure.compress(...)`.

## Faithfulness details

* **Doubles.** Block costs are `double` in C built from `size_t` sums. The
  port computes the sums as ints and converts with `float()` at the same
  points as C (`treesize = CalculateTreeSize(...)` etc.), and keeps the
  `treesize2 + datasize2 < treesize + datasize` comparison in that form. All the
  values are integers < 2^53, so the conversions are exact anyway.
* **`OptimizeHuffmanForRle`**: `size_t` counts, `(sum + stride / 2) / stride`
  is an unsigned integer division (`//` on non-negative ints), the `limit`
  average is `(c0 + c1 + c2 + c3 + 2) / 4` in integers, `i < length - 3` is a
  signed comparison (Python ints behave the same). The `int count` truncation
  is unreachable (counts are bounded by the block size).
* **Tie-breaking.** `AddDynamicTree`/`CalculateTreeSize` keep the first of the
  8 flag combinations with the smallest size (`bestsize == 0 || size < bestsize`).
  `AddLZ77BlockAutoType` and `ZopfliCalculateBlockSizeAutoType` keep the exact
  `<` / `<=` comparisons, `dyncost * 1.1` in double, and `lz77.size` (the
  whole store, see UPSTREAM_FINDINGS 14) for the 1000-symbol thresholds. The
  costs for all three block types are computed before the `lstart == lend`
  early return, as in C.
* **`EncodeTree`** reads the lengths through one concatenated list
  `ll_lengths[:hlit2] + d_lengths[:hdist + 1]`, the same sequence the C ternary
  produces. In size-only mode the `rle` arrays are not built (as in C).
  `ZopfliLengthsToSymbols` for the code-length code is only called when writing.
* **`AddNonCompressedBlock`**: `unsigned short blocksize`/`nlen`, `nlen = ~blocksize & 0xFFFF`,
  final bit `final && currentfinal`, `bp` forced to 0 (the partial byte is kept),
  then LEN, NLEN and the raw bytes, in 65535-byte chunks. An empty range gives
  one empty stored block, as in C.
* **`ZopfliDeflate`**: the `do { } while (i < insize)` loop over
  `ZOPFLI_MASTER_BLOCK_SIZE` chunks runs once for empty input.
  `ZOPFLI_FORMAT_DEFLATE` is handled in `zopfli_lib.compress_format` (as in
  `zopfli_lib.c`): a fresh writer with `bp = 0`, `deflate(options, 2, 1, ...)`.
* **Containers.** zlib header `cmfflg = 256*120 + 0*32 + 3*64`, `fcheck = 31 - cmfflg % 31`
  → `78 DA`; adler32 big-endian after the stream. gzip header
  `1f 8b 08 00 00000000 02 03`, then CRC32 and ISIZE (mod 2^32) little-endian.
  `adler32` keeps the 5550-byte chunking (no overflow possible; see finding 17
  for the `(unsigned)insize` cast, reproduced). The CRC table is generated
  from the polynomial and tested equal to the C literal.
* **Verbose output** (`treesize:`, `compressed block size:`, the
  `Original Size:` lines of deflate/zlib/gzip) is written to `sys.stderr` with
  the same text, including the `size_t` wrap, `(int)` casts, `inf` for empty
  input and glibc's `-nan`. Verified byte-identical to py-zopfli's stderr.

## Performance choices (same output)

* `add_lz77_data` inlines the bit writer: Huffman codes are bit-reversed once
  per block (`_reversed_codes`) and all bits of the block are accumulated
  LSB-first in a Python int, flushed every 64 bits. The partial last byte of
  `w.out` is taken into the accumulator first and `w.bp` is restored at the
  end, so bytes and `bp` are identical to the C bit-by-bit writes.
* The per-symbol `assert`s of `AddLZ77Data` are left out of that hot loop
  (py-zopfli builds with `NDEBUG` anyway); the final `testlength` assert is kept.
* `CalculateBlockSymbolSize*` use the `symbols` lookup tables directly.
* `compress()` converts its input to `bytes` once, so every module indexes a
  `bytes` object.

## `compress()` argument semantics (py-zopfli `zopflimodule.c`)

`PyArg_ParseTupleAndKeywords(args, kw, "s#|iiiiii", ...)` with keywords
`data, verbose, numiterations, blocksplitting, blocksplittinglast,
blocksplittingmax, gzip_mode`, options from `ZopfliInitOptions` then
overridden. Ported as: `str` → UTF-8 (strict, like `s#`), bytes-like objects
via `memoryview(...).tobytes()` (bytearray / writable buffers accepted as a
deliberate extension; `s#` rejects them), ints via `__index__` with C `int`
range checks (`TypeError` for floats, `OverflowError` outside `int`).
`gzip_mode` non-zero → gzip, else zlib.

## Verification

`tools/harness/deflate/` unity-builds the reference C (`harness.c`, built by
`build.py` into `tools/build/deflate_harness.so`) and exposes the static
deflate.c / container functions through ctypes (`cref.py`). `stubs.py` provides
C-backed stand-ins for dependency modules that are not available yet
(`lz77`, `squeeze`, `blocksplitter` are the C ones; `symbols` tables are read
from the C). `checks.py` runs everything:

    python tools/harness/deflate/checks.py           # full, stand-ins where needed
    python tools/harness/deflate/checks.py --quick   # smaller
    python tools/harness/deflate/checks.py --all-stubs   # ignore real modules

Tests: `tests/test_deflate.py`, `tests/test_containers.py` (real modules;
skip until all dependencies are importable, plus one test that runs
`checks.py --quick` in a subprocess).

## Interface note for blocksplitter

`ZopfliBlockSplit` / `ZopfliBlockSplitLZ77` take `size_t maxblocks`, and
`ZopfliDeflatePart` passes the `int options->blocksplittingmax`. The port does
that conversion at the call site (`options.blocksplittingmax & 0xFFFFFFFFFFFFFFFF`),
so `blocksplitter` always receives a non-negative `maxblocks`
(`blocksplittingmax=-1` means "no limit" in C, and in the port). Checked
against py-zopfli with `blocksplittingmax=-1`.
