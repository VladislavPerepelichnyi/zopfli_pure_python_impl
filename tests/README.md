# zopfli_pure tests

Functional and correctness tests for the pure-Python Zopfli port. No
performance benchmarks live here.

## Running

From the repository root, with the project venv (has pytest, hypothesis and
the oracle `zopfli` = py-zopfli 0.4.3):

```sh
PY=/home/vlad/thesis/wasm/pure_python_impl/zopfli_pure_python/.venv/bin/python

$PY -m pytest                         # default run, slow tests skipped (~11 min, of
                                      # which ~6 min are the files listed below)
ZOPFLI_PURE_SLOW=1 $PY -m pytest      # + large inputs (> 40 KB), all periods 1..300,
                                      #   15 iterations on small/medium (~+10 min)
ZOPFLI_PURE_SLOW=2 $PY -m pytest      # + inputs > 1 MB (master block boundary, ~+1 min)
$PY -m pytest tests/test_oracle.py tests/test_stages.py   # just the T suite parts
$PY -m pytest tests/test_stages.py -k optimal     # one area
ZOPFLI_PURE_HYPOTHESIS=thorough $PY -m pytest -k property   # 500 examples per property
```

Tests for modules that have not been merged yet are skipped, with the missing
module named in the skip reason (`-rs` shows them). A module that exists but
fails to import is a failure, not a skip.

## Reference C oracle (`tools/`)

* `tools/build_reference.py` (or `tools/build_reference.sh`) compiles the
  unmodified reference sources (`../zopfli_reference`, or
  `$ZOPFLI_REFERENCE_DIR`) into `tools/build/` (gitignored):
  * `zopfli`: the reference CLI;
  * `libzopfli_ref.so`: the library plus `tools/ref_shim.c`, which exposes
    intermediate stages as flat C functions.

  Flags: `-O2 -ffp-contract=off -fno-fast-math -march=x86-64 -mno-fma`. It
  rebuilds only when sources are newer (`--force` to rebuild).
* `tests/ref.py`: ctypes wrapper. Builds the library on demand; if gcc or the
  reference sources are missing, `ref.require()` skips the test. API:
  `compress` (same signature as py-zopfli), `compress_format`, `deflate`,
  `deflate_part`, `cli_compress`, `lz77_greedy`, `lz77_optimal`,
  `lz77_optimal_fixed` (these return a `Store` with `.litlens/.dists/.pos`
  lists and `.symbols()`), `store_from_arrays`, `lz77_get_histogram`,
  `lz77_get_byte_range`, `find_longest_match`, `calculate_block_size(_auto_type)`,
  `block_split_lz77`, `block_split`, `block_split_simple`,
  `length_limited_code_lengths`, `calculate_bit_lengths`, `lengths_to_symbols`,
  `calculate_entropy`, `optimize_huffman_for_rle`, `symbol_fn`.

## Files

| File | Covers |
|---|---|
| `conftest.py` | `sys.path`, `slow`/`huge` gating via `ZOPFLI_PURE_SLOW`, hypothesis profiles |
| `corpus.py` | Deterministic named inputs (`tiny`/`small`/`medium`/`large`): empty, single bytes, 2-3 bytes, all 256 values, runs (10, 258, 259, 516, 517, 1000, 40000), periodic data (periods 1-300), pseudo-English text, the Gettysburg Address, reference C sources, seeded random (stored blocks), mixed text/binary, DNA, sparse, multi-block inputs, sizes around 32768 and 65536 |
| `port.py` | Imports port modules, skipping if absent; memoised `compress`; diff helpers |
| `stages.py` | Runs Python stages with the same setup as the C shim; `localize(data, **opts)` walks the ZopfliDeflatePart pipeline and names the first stage that differs (each stage fed C's upstream results) |
| `test_ref_harness.py` | Validates the oracle tooling itself: `ref.compress` == py-zopfli == CLI on the corpus; C stages self-consistent (stores decode to the input, split points agree, block-size formulas, Kraft equality) |
| `test_oracle.py` | Byte-for-byte `zopfli_pure.compress == zopfli.zopfli.compress` over corpus x options (gzip_mode, numiterations 1/2/5/15 and <= 0, blocksplitting, blocksplittingmax 0/1/3/15, blocksplittinglast), str input, hypothesis properties; raw deflate/zlib/gzip via `zopfli_lib.compress_format` vs the C library and the CLI. Failures include a `localize` report |
| `test_roundtrip.py` | `zlib`/`gzip`/raw-inflate of the output gives the input; header/trailer fields |
| `test_stages.py` | Differential tests per function: symbols.h (exhaustive), katajainen, tree, OptimizeHuffmanForRle, BitWriter layout, FindLongestMatch (incl. sublen), greedy/optimal/fixed stores (incl. sub-ranges, iterations > 6 for the randomisation), store symbols/histograms, block sizes (`float.hex()`), block splitting, ZopfliDeflate per btype, DeflatePart sub-ranges |
| `test_purity.py` | Static AST scan of `zopfli_pure/` imports (only `math`, `array`, `sys`, `struct`, package-internal); dynamic run with `zlib`, `binascii`, `gzip`, `ctypes`, `_cffi_backend`, `zopfli`, ... poisoned in `sys.modules` |
| `test_api.py` | `compress` argument handling vs py-zopfli: positional/keyword forms, defaults, str/bytes input, exception types for bad input, int overflow, verbose output; bytearray/memoryview extension |
| `test_tree.py`, `test_lz77.py`, `test_squeeze.py`, `test_blocksplitter.py`, `test_deflate.py`, `test_containers.py` | Module tests written by the implementers (with their own harnesses in `tools/harness/`) |

## Cost model

Pure Python is ~100-250x slower than C. Block splitting dominates: every
candidate split evaluates `ZopfliCalculateBlockSizeAutoType` (dynamic tree
lengths, `EncodeTree` x8, katajainen), ~3 ms each in Python, thousands of times
per input. Inputs that split into many blocks are therefore in the `medium`
class even when they are only a few KB.

## Localising a mismatch by hand

```python
import sys; sys.path[:0] = ["tests", "."]
import stages
print(stages.localize_report(data, numiterations=15))
```
