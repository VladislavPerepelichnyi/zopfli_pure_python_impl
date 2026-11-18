"""Differential tests of intermediate stages against the reference C library.

Each test runs one ported function and the same C function (through
tests/ref.py) on identical inputs. Where a stage consumes the output of an
earlier stage (e.g. block splitting consumes an LZ77 store), the *C* result
of the earlier stage is fed to both sides, so a failure points at exactly one
function. Failure messages name the first differing index.

Tests skip cleanly while the corresponding module is not merged yet.
"""

import pytest

import corpus
import ref
import stages
from port import first_diff, need, options

pytestmark = pytest.mark.oracle


@pytest.fixture(autouse=True)
def _need_ref():
    ref.require()


def assert_lists_equal(got, want, label):
    got, want = list(got), list(want)
    i = first_diff(got, want)
    if i is not None:
        lo = max(0, i - 3)
        pytest.fail("%s differs at index %d (len py %d, C %d): py[%d:%d]=%s "
                    "C[%d:%d]=%s" % (label, i, len(got), len(want), lo, i + 4,
                                     got[lo:i + 4], lo, i + 4, want[lo:i + 4]))


def assert_store_equal(pystore, cstore, label):
    msg = stages.describe_store_diff(
        stages.store_arrays(pystore),
        (cstore.litlens, cstore.dists, cstore.pos), label)
    if msg:
        pytest.fail(msg)


def hexes(values):
    return [float(v).hex() for v in values]


def random_counts(seed, n, zero_frac=3, maxval=1000):
    r = corpus.Rng(seed)
    return [r.below(maxval) if r.below(zero_frac) else 0 for _ in range(n)]


# ----------------------------------------------------------------- symbols

@pytest.mark.parametrize("fn,domain", [
    ("get_dist_extra_bits", range(1, 32769)),
    ("get_dist_extra_bits_value", range(1, 32769)),
    ("get_dist_symbol", range(1, 32769)),
    ("get_length_extra_bits", range(3, 259)),
    ("get_length_extra_bits_value", range(3, 259)),
    ("get_length_symbol", range(3, 259)),
    ("get_length_symbol_extra_bits", range(257, 286)),
    ("get_dist_symbol_extra_bits", range(0, 30)),
])
def test_symbols_exhaustive(fn, domain):
    sym = need("symbols", fn)
    f = getattr(sym, fn)
    got = [f(x) for x in domain]
    want = [ref.symbol_fn(fn, x) for x in domain]
    assert_lists_equal(got, want, "%s over %s" % (fn, domain))


# -------------------------------------------------------- katajainen / tree

LLCL_CASES = [
    ("empty", [], 15),
    ("all_zero", [0] * 19, 7),
    ("one_symbol", [0, 0, 5, 0], 15),
    ("one_symbol_first", [9], 7),
    ("two_symbols", [3, 0, 0, 1], 15),
    ("equal_32", [1] * 32, 15),
    ("equal_256_maxbits7", [1] * 256, 7),   # 256 > 2^7 -> error
    ("equal_128_maxbits7", [1] * 128, 7),
    ("fibonacci", [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610,
                   987, 1597, 2584, 4181, 6765, 10946, 17711], 15),
    ("fibonacci_7", [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610,
                     987, 1597, 2584, 4181], 7),
    # counts > 2^22 apart hit the comparator truncation documented in
    # docs/UPSTREAM_FINDINGS.md #1 (not reproduced), so stay below that
    ("big_counts", [1000001, 1, 999999, 7, 0, 3, 2 ** 21], 15),
    ("too_heavy", [2 ** 55, 1, 2], 15),     # rejected with return value 1
]


@pytest.mark.parametrize("name,freqs,maxbits", LLCL_CASES,
                         ids=[c[0] for c in LLCL_CASES])
def test_length_limited_code_lengths_cases(name, freqs, maxbits):
    k = need("katajainen", "length_limited_code_lengths")
    out = [0] * len(freqs)
    r = k.length_limited_code_lengths(list(freqs), len(freqs), maxbits, out)
    cr, cout = ref.length_limited_code_lengths(freqs, maxbits)
    assert (r != 0) == (cr != 0), "return code py %r C %r" % (r, cr)
    if cr == 0:
        assert_lists_equal(out, cout, "bitlengths")


@pytest.mark.parametrize("seed", range(60))
def test_length_limited_code_lengths_random(seed):
    k = need("katajainen", "length_limited_code_lengths")
    n = [19, 30, 32, 288][seed % 4]
    maxbits = 7 if n == 19 else 15
    freqs = random_counts(seed, n, zero_frac=2 + seed % 5,
                          maxval=[10, 1000, 100000][seed % 3])
    out = [0] * n
    r = k.length_limited_code_lengths(freqs, n, maxbits, out)
    cr, cout = ref.length_limited_code_lengths(freqs, maxbits)
    assert r == cr
    assert_lists_equal(out, cout, "bitlengths (seed %d)" % seed)


@pytest.mark.parametrize("seed", range(30))
def test_calculate_bit_lengths(seed):
    t = need("tree", "calculate_bit_lengths")
    n = [19, 32, 288][seed % 3]
    maxbits = 7 if n == 19 else 15
    counts = random_counts(1000 + seed, n)
    out = [0] * n
    t.calculate_bit_lengths(counts, n, maxbits, out)
    assert_lists_equal(out, ref.calculate_bit_lengths(counts, maxbits),
                       "bitlengths")


@pytest.mark.parametrize("seed", range(30))
def test_lengths_to_symbols(seed):
    t = need("tree", "lengths_to_symbols")
    n = [19, 32, 288][seed % 3]
    maxbits = 7 if n == 19 else 15
    lengths = ref.calculate_bit_lengths(random_counts(2000 + seed, n), maxbits)
    out = [0] * n
    t.lengths_to_symbols(lengths, n, maxbits, out)
    assert_lists_equal(out, ref.lengths_to_symbols(lengths, maxbits), "symbols")


@pytest.mark.parametrize("seed", range(30))
def test_calculate_entropy(seed):
    t = need("tree", "calculate_entropy")
    n = [32, 288][seed % 2]
    counts = random_counts(3000 + seed, n, zero_frac=2 + seed % 4,
                           maxval=[3, 100, 1000000][seed % 3])
    out = [0.0] * n
    t.calculate_entropy(counts, n, out)
    assert_lists_equal(hexes(out), hexes(ref.calculate_entropy(counts)),
                       "entropy (float.hex)")


@pytest.mark.parametrize("seed", range(40))
def test_optimize_huffman_for_rle(seed):
    d = need("deflate", "optimize_huffman_for_rle")
    n = [32, 288][seed % 2]
    r = corpus.Rng(4000 + seed)
    # runs of equal values and zeros make the RLE logic do something
    counts = []
    while len(counts) < n:
        v = r.below(50) if r.below(3) else 0
        counts += [v + (r.below(2) if r.below(4) == 0 else 0)
                   for _ in range(1 + r.below(12))]
    counts = counts[:n]
    got = list(counts)
    d.optimize_huffman_for_rle(n, got)
    assert_lists_equal(got, ref.optimize_huffman_for_rle(counts),
                       "OptimizeHuffmanForRle counts")


# --------------------------------------------------------------- bitwriter

def test_bitwriter_layout():
    bw = need("bitwriter", "BitWriter")
    r = corpus.Rng(77)
    w = bw.BitWriter()
    bits = []  # model: list of bits in stream order
    for _ in range(2000):
        kind = r.below(3)
        if kind == 0:
            b = r.below(2)
            w.add_bit(b)
            bits.append(b)
        else:
            length = r.below(17)
            sym = r.below(1 << length) if length else 0
            if kind == 1:
                w.add_bits(sym, length)            # LSB first
                bits += [(sym >> i) & 1 for i in range(length)]
            else:
                w.add_huffman_bits(sym, length)    # MSB first
                bits += [(sym >> (length - 1 - i)) & 1 for i in range(length)]
    want = bytearray((len(bits) + 7) // 8)
    for i, b in enumerate(bits):
        want[i >> 3] |= b << (i & 7)
    assert bytes(w.out) == bytes(want)
    assert w.bp == len(bits) & 7


# ------------------------------------------------------------- LZ77 stages

STORE_CASES = corpus.params("tiny", "small")
STORE_CASES_MEDIUM = corpus.params("medium")


@pytest.mark.parametrize("name", ["text_1k", "periodic_258", "run_1000",
                                  "all_bytes_x4", "mixed_3k"])
def test_find_longest_match(name):
    data = corpus.get(name).data
    positions = list(range(0, len(data), 7)) + [len(data) - 1]
    positions = sorted(set(p for p in positions if 0 <= p < len(data)))
    for limit in (258, 20):
        for p, dist, length, sublen in stages.py_find_longest_match_scan(
                data, positions, limit=limit):
            cdist, clength, csub = ref.find_longest_match(data, p, limit=limit)
            assert (dist, length) == (cdist, clength), \
                "pos %d limit %d: py (dist,len)=%s C %s" % (
                    p, limit, (dist, length), (cdist, clength))
            if length >= 3:
                assert_lists_equal(sublen[3:length + 1], csub[3:length + 1],
                                   "sublen[3:] at pos %d" % p)


@pytest.mark.parametrize("case", STORE_CASES + STORE_CASES_MEDIUM)
def test_lz77_greedy(case):
    data = case.data
    assert_store_equal(stages.py_lz77_greedy(data), ref.lz77_greedy(data),
                       "greedy store")


@pytest.mark.parametrize("name", ["text_5k", "multi_block_6k", "run_then_text",
                                  "text_20k"])
def test_lz77_greedy_subrange(name):
    data = corpus.get(name).data
    a, b = len(data) // 3, 2 * len(data) // 3
    assert_store_equal(stages.py_lz77_greedy(data, a, b),
                       ref.lz77_greedy(data, a, b),
                       "greedy store [%d,%d)" % (a, b))
    assert_store_equal(stages.py_lz77_greedy(data, a, b, add_lmc=1),
                       ref.lz77_greedy(data, a, b, add_lmc=1),
                       "greedy store with lmc [%d,%d)" % (a, b))


@pytest.mark.slow
@pytest.mark.parametrize("name", ["text_33000", "mixed_65537"])
def test_lz77_greedy_window_boundary(name):
    data = corpus.get(name).data
    assert_store_equal(stages.py_lz77_greedy(data), ref.lz77_greedy(data),
                       "greedy store")
    a = 32768 + 100
    assert_store_equal(stages.py_lz77_greedy(data, a, len(data)),
                       ref.lz77_greedy(data, a, len(data)),
                       "greedy store [%d,%d)" % (a, len(data)))


@pytest.mark.parametrize("name", ["text_1k", "multi_block_6k", "run_1000",
                                  "random_1000", "empty", "byte_00"])
def test_store_symbols_and_histograms(name):
    """LZ77Store built by store_lit_len_dist from the C greedy store:
    ll_symbol/d_symbol, chunked cumulative counts, histograms, byte ranges."""
    lz77 = need("lz77", "lz77_get_histogram", "lz77_get_byte_range")
    data = corpus.get(name).data
    cs = ref.lz77_greedy(data)
    ps = stages.py_store_from_ref(data, cs)
    n = cs.size
    assert ps.size == n
    ls, ds, lc, dc = cs.symbols()
    assert_lists_equal(ps.ll_symbol[:n], ls, "ll_symbol")
    assert_lists_equal(ps.d_symbol[:n], ds, "d_symbol")
    assert_lists_equal(ps.ll_counts[:len(lc)], lc, "ll_counts")
    assert_lists_equal(ps.d_counts[:len(dc)], dc, "d_counts")
    r = corpus.Rng(n)
    ranges = [(0, n)] + [tuple(sorted((r.below(n + 1), r.below(n + 1))))
                         for _ in range(20)] if n else [(0, 0)]
    for a, b in ranges:
        ll, d = [0] * 288, [0] * 32
        lz77.lz77_get_histogram(ps, a, b, ll, d)
        cll, cd = ref.lz77_get_histogram(cs, a, b)
        assert_lists_equal(ll, cll, "ll histogram [%d,%d)" % (a, b))
        assert_lists_equal(d, cd, "d histogram [%d,%d)" % (a, b))
        if a < b:
            assert lz77.lz77_get_byte_range(ps, a, b) == \
                ref.lz77_get_byte_range(cs, a, b)


@pytest.mark.parametrize("case", corpus.params("tiny"))
@pytest.mark.parametrize("numiterations", [1, 2, 15])
def test_lz77_optimal_tiny(case, numiterations):
    data = case.data
    assert_store_equal(stages.py_lz77_optimal(data, numiterations=numiterations),
                       ref.lz77_optimal(data, numiterations=numiterations),
                       "optimal store numiterations=%d" % numiterations)


@pytest.mark.parametrize("case", corpus.params("small"))
def test_lz77_optimal_small(case):
    data = case.data
    assert_store_equal(stages.py_lz77_optimal(data, numiterations=1),
                       ref.lz77_optimal(data, numiterations=1),
                       "optimal store numiterations=1")


@pytest.mark.parametrize("name", ["text_1k", "gettysburg", "random_1000",
                                  "periodic_31", "run_then_text"])
@pytest.mark.parametrize("numiterations", [5, 8, 15])
def test_lz77_optimal_iterations(name, numiterations):
    """numiterations > 6 exercises the randomisation (RandomizeStatFreqs)."""
    data = corpus.get(name).data
    assert_store_equal(stages.py_lz77_optimal(data, numiterations=numiterations),
                       ref.lz77_optimal(data, numiterations=numiterations),
                       "optimal store numiterations=%d" % numiterations)


@pytest.mark.parametrize("name", ["text_5k", "multi_block_6k"])
def test_lz77_optimal_subrange(name):
    data = corpus.get(name).data
    a, b = len(data) // 3, 2 * len(data) // 3
    assert_store_equal(stages.py_lz77_optimal(data, a, b, numiterations=2),
                       ref.lz77_optimal(data, a, b, numiterations=2),
                       "optimal store [%d,%d)" % (a, b))


@pytest.mark.parametrize("case", corpus.params("tiny", "small"))
def test_lz77_optimal_fixed(case):
    data = case.data
    assert_store_equal(stages.py_lz77_optimal_fixed(data),
                       ref.lz77_optimal_fixed(data), "fixed store")


@pytest.mark.parametrize("name", ["text_5k", "multi_block_6k"])
def test_lz77_optimal_fixed_subrange(name):
    data = corpus.get(name).data
    a, b = len(data) // 4, 3 * len(data) // 4
    assert_store_equal(stages.py_lz77_optimal_fixed(data, a, b),
                       ref.lz77_optimal_fixed(data, a, b),
                       "fixed store [%d,%d)" % (a, b))


@pytest.mark.parametrize("case", STORE_CASES_MEDIUM)
def test_lz77_optimal_medium(case):
    data = case.data
    assert_store_equal(stages.py_lz77_optimal(data, numiterations=1),
                       ref.lz77_optimal(data, numiterations=1),
                       "optimal store numiterations=1")


# ---------------------------------------------------------- block sizes

def _ranges(n, seed, k=10):
    r = corpus.Rng(seed)
    out = [(0, n)]
    for _ in range(k):
        a, b = sorted((r.below(n + 1), r.below(n + 1)))
        if a < b:
            out.append((a, b))
    return out


@pytest.mark.parametrize("case", corpus.params("tiny", "small", "medium"))
def test_calculate_block_size(case):
    data = case.data
    if not data:
        pytest.skip("empty store")
    cs = ref.lz77_optimal(data, numiterations=1)
    ps = stages.py_store_from_ref(data, cs)
    for a, b in _ranges(cs.size, len(data)):
        for bt in (0, 1, 2):
            pv = stages.py_calculate_block_size(ps, a, b, bt)
            cv = ref.calculate_block_size(cs, a, b, bt)
            assert float(pv).hex() == cv.hex(), \
                "CalculateBlockSize btype %d [%d,%d): py %s C %s" % (
                    bt, a, b, float(pv).hex(), cv.hex())
        pv = stages.py_calculate_block_size_auto_type(ps, a, b)
        cv = ref.calculate_block_size_auto_type(cs, a, b)
        assert float(pv).hex() == cv.hex(), \
            "CalculateBlockSizeAutoType [%d,%d): py %s C %s" % (
                a, b, float(pv).hex(), cv.hex())


@pytest.mark.parametrize("name", ["text_5k", "multi_block_6k", "mixed_3k"])
def test_calculate_block_size_greedy_store(name):
    data = corpus.get(name).data
    cs = ref.lz77_greedy(data)
    ps = stages.py_store_from_ref(data, cs)
    for a, b in _ranges(cs.size, 99, k=30):
        pv = stages.py_calculate_block_size_auto_type(ps, a, b)
        cv = ref.calculate_block_size_auto_type(cs, a, b)
        assert float(pv).hex() == cv.hex(), "[%d,%d)" % (a, b)


# ---------------------------------------------------------- block splitting

@pytest.mark.parametrize("maxblocks", [0, 1, 3, 15])
@pytest.mark.parametrize("case", corpus.params("tiny", "small", "medium"))
def test_block_split_lz77(case, maxblocks):
    data = case.data
    cs = ref.lz77_greedy(data)
    ps = stages.py_store_from_ref(data, cs)
    assert stages.py_block_split_lz77(ps, maxblocks) == \
        ref.block_split_lz77(cs, maxblocks)


@pytest.mark.parametrize("name", ["multi_block_6k", "multi_block_24k",
                                  "mixed_20k", "text_20k"])
def test_block_split_lz77_optimal_store(name):
    """Second split attempt in ZopfliDeflatePart runs on the optimal store."""
    data = corpus.get(name).data
    cs = ref.lz77_optimal(data, numiterations=1)
    ps = stages.py_store_from_ref(data, cs)
    assert stages.py_block_split_lz77(ps, 15) == ref.block_split_lz77(cs, 15)


@pytest.mark.parametrize("case", corpus.params("tiny", "small"))
def test_block_split(case):
    data = case.data
    assert stages.py_block_split(data, 0, len(data), 15) == \
        ref.block_split(data, 0, len(data), 15)


@pytest.mark.parametrize("name", ["multi_block_6k", "text_5k"])
def test_block_split_subrange(name):
    data = corpus.get(name).data
    a, b = 500, len(data) - 300
    for mb in (0, 3, 15):
        assert stages.py_block_split(data, a, b, mb) == \
            ref.block_split(data, a, b, mb)


@pytest.mark.parametrize("instart,inend,blocksize", [
    (0, 0, 10), (0, 1000, 100), (0, 1001, 100), (7, 5000, 999), (0, 10, 20)])
def test_block_split_simple(instart, inend, blocksize):
    bs = need("blocksplitter", "block_split_simple")
    data = corpus.random_bytes(max(inend, 1))
    assert list(bs.block_split_simple(data, instart, inend, blocksize)) == \
        ref.block_split_simple(data, instart, inend, blocksize)


# ----------------------------------------------------------------- deflate

@pytest.mark.parametrize("btype", [0, 1, 2])
@pytest.mark.parametrize("case", corpus.params("tiny") + [
    pytest.param(corpus.get(n), id=n) for n in ("text_1k", "random_1000",
                                                "run_then_text")])
def test_deflate_btype(case, btype):
    data = case.data
    got = stages.py_deflate(data, btype, 1, numiterations=2)
    want = ref.deflate(data, btype, 1, numiterations=2)
    assert got == want, stages.describe_bytes_diff(got, want, "ZopfliDeflate")


@pytest.mark.parametrize("final", [0, 1])
def test_deflate_not_final(final):
    data = corpus.get("text_1k").data
    got = stages.py_deflate(data, 2, final, numiterations=1)
    want = ref.deflate(data, 2, final, numiterations=1)
    assert got == want, stages.describe_bytes_diff(got, want, "ZopfliDeflate")


@pytest.mark.parametrize("btype", [0, 1, 2])
@pytest.mark.parametrize("name", ["text_5k", "multi_block_6k"])
def test_deflate_part_subrange(name, btype):
    data = corpus.get(name).data
    a, b = 1000, len(data) - 500
    got = stages.py_deflate_part(data, a, b, btype, 1, numiterations=1)
    want = ref.deflate_part(data, a, b, btype, 1, numiterations=1)
    assert got == want, stages.describe_bytes_diff(got, want, "DeflatePart")


@pytest.mark.slow
def test_deflate_uncompressed_multi_block():
    """btype 0 over > 65535 bytes splits into several stored blocks."""
    data = corpus.random_bytes(140000, seed=5)
    got = stages.py_deflate(data, 0, 1)
    assert got == ref.deflate(data, 0, 1)
