# zopfli_pure_python_impl

A pure-Python (standard library only) port of Google's [Zopfli](https://github.com/google/zopfli)
compressor. It follows the reference C implementation (google/zopfli @ `df1517dd`, i.e.
`zopfli-1.0.3`) function by function.

```python
import zlib, zopfli_pure
packed = zopfli_pure.compress(data)            # zlib container, 15 iterations, block splitting
assert zlib.decompress(packed) == data
gz = zopfli_pure.compress(data, gzip_mode=1)   # gzip container
```

The API mirrors `zopfli.zopfli.compress` from the C-backed `py-zopfli` package:

- `compress(data, verbose=0, numiterations=15, blocksplitting=1, blocksplittinglast=0, blocksplittingmax=15, gzip_mode=0) -> bytes`

`data` may be `bytes` or `str` (encoded as UTF-8, like py-zopfli). As a deliberate extension,
`bytearray` and `memoryview` are accepted too. Raw DEFLATE output is available through
`zopfli_pure.zopfli_lib.compress_format(options, ZOPFLI_FORMAT_DEFLATE, data)`.

## Status

The output is **byte-identical** to `py-zopfli` 0.4.3 (and to the reference C library)
for zlib, gzip and raw deflate, across all option combinations tested. This has been
checked on about 100 named corpus inputs from 0 bytes to more than 1 MB, on hypothesis
property tests, and stage by stage: every intermediate LZ77 store, split point, block
cost (compared bit-exactly as `float.hex()`), and Huffman code length.

Compression runs in pure Python. Modules in `zopfli_pure/` import only `sys`,
`math` (`log`) and `array`. `tests/test_purity.py` enforces this both statically
(an AST scan) and dynamically (`zlib`, `binascii`, `gzip`, `ctypes` and others are
poisoned in `sys.modules`).

Pure Python is much slower than C (no benchmarks are included here). Most of
the time goes to block splitting, which repeatedly computes dynamic-tree block costs
(`katajainen` and `EncodeTree`), and to `find_longest_match` during the squeeze
iterations. The port does the same work as the C. It adds no caches or shortcuts the
C does not have, so timings compare like with like.

**Assertions:** the port keeps the C `assert`s as Python `assert` statements, and
`ZopfliVerifyLenDist` sits under `if __debug__:`. To compare with C built with
`-DNDEBUG`, such as the py-zopfli wheel (built with CPython's `CFLAGS`, which include
`-DNDEBUG`), run Python with `-O`. The C harnesses in `tools/` build *with* asserts, on
purpose, for verification.

## Layout

| Path | Port of |
|------|---------|
| `zopfli_pure/util.py`, `symbols.py` | `util.h`/`util.c`, `zopfli.h`, `symbols.h` |
| `zopfli_pure/hash.py`, `cache.py`, `lz77.py` | `hash.c` (both hash chains plus `same`), `cache.c` (longest-match cache), `lz77.c` (store with cumulative histograms, `FindLongestMatch`, greedy LZ77 with lazy matching) |
| `zopfli_pure/katajainen.py`, `tree.py`, `bitwriter.py` | `katajainen.c` (boundary package-merge), `tree.c`, and the bit writers from `deflate.c` |
| `zopfli_pure/squeeze.py` | `squeeze.c` (iterative shortest path, `float` cost array emulated with `array('f')`, Marsaglia `Ran`, `LZ77OptimalFixed`) |
| `zopfli_pure/blocksplitter.py` | `blocksplitter.c` (`FindMinimum`, `BlockSplit`, `BlockSplitLZ77`) |
| `zopfli_pure/deflate.py` | `deflate.c` (`EncodeTree` with 8 RLE flag combinations, `OptimizeHuffmanForRle`, automatic block type, `DeflatePart`) |
| `zopfli_pure/zlib_container.py`, `gzip_container.py`, `zopfli_lib.py` | containers with `adler32` / CRC32, `ZopfliCompress` |
| `tools/` | reference C build (`build_reference.py`, `ref_shim.c` exposing intermediate stages) and per-module C harnesses |
| `tests/` | functional tests; see [tests/README.md](tests/README.md) |
| `docs/PORTING_SPEC.md` | porting conventions and interfaces |
| `docs/UPSTREAM_FINDINGS.md` | bugs and questionable behaviour in the reference C |
| `docs/notes/` | per-module porting notes |

## Tests

```sh
python3 -m venv .venv
.venv/bin/pip install pytest hypothesis zopfli==0.4.3   # zopfli = C oracle
git clone https://github.com/google/zopfli.git ../zopfli_reference   # for the C harnesses (needs gcc)

.venv/bin/python -m pytest                      # default run (~11 min)
ZOPFLI_PURE_SLOW=1 .venv/bin/python -m pytest   # adds large inputs
ZOPFLI_PURE_SLOW=2 .venv/bin/python -m pytest   # adds inputs > 1 MB (master-block boundary)
```

## Upstream findings

[docs/UPSTREAM_FINDINGS.md](docs/UPSTREAM_FINDINGS.md) lists 23 findings in the
reference C. The port reproduces the upstream output in every case, except where
the upstream behaviour cannot be reached from Zopfli. Two of them change the
compressed output:

- **#4:** `numiterations <= 0` produces an empty LZ77 store, so the stream silently
  loses the data. py-zopfli then returns a zlib stream that fails its checksum.
- **#9:** `FindLargestSplittableBlock` ends the last block at `lz77size - 1`, so the
  final LZ77 symbol is never considered by later split searches.

The others are undefined behaviour that Zopfli's inputs cannot reach (integer
truncation in the katajainen comparator, `maxbits >= 16`, unaligned type-punned
loads, a stale `sublen[0]` read), dead code, and verbose-output quirks.

## License

Apache License 2.0, the same as Zopfli. This is a derivative work; see `LICENSE` and `NOTICE`.
