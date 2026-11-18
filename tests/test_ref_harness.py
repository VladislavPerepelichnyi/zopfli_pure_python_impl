"""Validates the reference oracle tooling itself (tools/ref_shim.c, tests/ref.py).

These tests do not touch zopfli_pure. They check that

* ``ref.compress`` (our build of the reference C) is byte-identical to the
  py-zopfli oracle and to the reference CLI binary, on the whole corpus;
* the stage entry points of the shim are self-consistent (stores decode to the
  input, split points agree between ZopfliBlockSplit and ZopfliBlockSplitLZ77,
  block-size formulas, Kraft inequality for code lengths, ...).

If these fail, the stage-level differential tests in test_stages.py cannot be
trusted.
"""

import gzip
import zlib

import pytest

import corpus
import ref

pytestmark = pytest.mark.oracle

zopfli_oracle = pytest.importorskip("zopfli.zopfli")


@pytest.fixture(autouse=True)
def _need_ref():
    ref.require()


def decode_store(data, litlens, dists, pos, instart=0):
    """Expand an LZ77 store back to bytes, checking pos consistency."""
    out = bytearray(data[:instart])
    for i, (ll, d, p) in enumerate(zip(litlens, dists, pos)):
        assert p == len(out), "pos[%d]=%d but decoded %d bytes" % (i, p, len(out))
        if d == 0:
            assert 0 <= ll < 256
            out.append(ll)
        else:
            assert 3 <= ll <= 258 and 1 <= d <= 32768 and d <= len(out)
            for _ in range(ll):
                out.append(out[-d])
    return bytes(out[instart:])


# --------------------------------------------------- end-to-end equivalence

@pytest.mark.parametrize("case", corpus.params(extra_marks=()))
@pytest.mark.parametrize("gzip_mode", [0, 1])
def test_ref_compress_equals_pyzopfli(case, gzip_mode):
    data = case.data
    it = 15 if case.size in ("tiny", "small") else 3
    a = ref.compress(data, numiterations=it, gzip_mode=gzip_mode)
    b = zopfli_oracle.compress(data, numiterations=it, gzip_mode=gzip_mode)
    assert a == b
    if gzip_mode:
        assert gzip.decompress(a) == data
    else:
        assert zlib.decompress(a) == data


@pytest.mark.parametrize("opts", [
    dict(numiterations=1),
    dict(numiterations=2, blocksplitting=0),
    dict(numiterations=5, blocksplittingmax=0),
    dict(numiterations=5, blocksplittingmax=1),
    dict(numiterations=5, blocksplittingmax=3),
    dict(numiterations=5, blocksplittinglast=1),
])
@pytest.mark.parametrize("name", ["multi_block_6k", "text_5k", "mixed_3k",
                                  "run_then_text", "random_1000"])
def test_ref_compress_options_equal_pyzopfli(name, opts):
    data = corpus.get(name).data
    for gz in (0, 1):
        assert ref.compress(data, gzip_mode=gz, **opts) == \
            zopfli_oracle.compress(data, gzip_mode=gz, **opts)


@pytest.mark.parametrize("case", corpus.params("tiny", "small"))
def test_ref_deflate_format_roundtrip(case):
    raw = ref.compress_format(ref.FORMAT_DEFLATE, case.data, numiterations=5)
    assert zlib.decompress(raw, -15) == case.data
    # zlib = 2-byte header + raw deflate + adler32
    z = ref.compress_format(ref.FORMAT_ZLIB, case.data, numiterations=5)
    assert z[2:-4] == raw


@pytest.mark.parametrize("name", ["empty", "hello", "text_1k", "random_1000",
                                  "multi_block_6k"])
@pytest.mark.parametrize("fmt", [ref.FORMAT_GZIP, ref.FORMAT_ZLIB,
                                 ref.FORMAT_DEFLATE])
def test_ref_cli_equals_library(name, fmt):
    data = corpus.get(name).data
    assert ref.cli_compress(data, fmt, numiterations=7) == \
        ref.compress_format(fmt, data, numiterations=7)


@pytest.mark.parametrize("btype", [0, 1, 2])
@pytest.mark.parametrize("name", ["empty", "text_1k", "random_1000", "run_1000"])
def test_ref_deflate_btypes_decode(name, btype):
    data = corpus.get(name).data
    out = ref.deflate(data, btype=btype, numiterations=3)
    assert zlib.decompress(out, -15) == data
    if btype == 2:
        assert out == ref.compress_format(ref.FORMAT_DEFLATE, data,
                                          numiterations=3)
        assert out == ref.deflate_part(data, 0, len(data), 2, 1,
                                       numiterations=3)


# ------------------------------------------------------ stage consistency

STAGE_CASES = corpus.params("tiny", "small", "medium")


@pytest.mark.parametrize("case", STAGE_CASES)
def test_ref_stores_decode_to_input(case):
    data = case.data
    for store in (ref.lz77_greedy(data), ref.lz77_optimal(data, numiterations=2),
                  ref.lz77_optimal_fixed(data)):
        assert decode_store(data, store.litlens, store.dists, store.pos) == data


@pytest.mark.parametrize("name", ["text_5k", "multi_block_6k", "run_then_text"])
def test_ref_stores_with_instart(name):
    data = corpus.get(name).data
    a, b = len(data) // 3, 2 * len(data) // 3
    for store in (ref.lz77_greedy(data, a, b),
                  ref.lz77_optimal(data, a, b, numiterations=2),
                  ref.lz77_optimal_fixed(data, a, b)):
        assert decode_store(data[:b], store.litlens, store.dists, store.pos,
                            instart=a) == data[a:b]


@pytest.mark.parametrize("case", corpus.params("tiny", "small"))
def test_ref_store_roundtrip_arrays(case):
    data = case.data
    s = ref.lz77_optimal(data, numiterations=1)
    s2 = ref.store_from_arrays(data, s.litlens, s.dists, s.pos)
    assert s2.as_tuples() == s.as_tuples()
    assert s2.symbols() == s.symbols()
    n = s.size
    assert ref.calculate_block_size(s2, 0, n, 2) == \
        ref.calculate_block_size(s, 0, n, 2)


@pytest.mark.parametrize("case", STAGE_CASES)
def test_ref_block_split_consistent(case):
    data = case.data
    greedy = ref.lz77_greedy(data)
    lz_points = ref.block_split_lz77(greedy, 15)
    byte_points = ref.block_split(data, 0, len(data), 15)
    assert len(lz_points) == len(byte_points)
    assert byte_points == [greedy.pos[i] for i in lz_points]
    assert byte_points == sorted(set(byte_points))


@pytest.mark.parametrize("name", ["multi_block_6k", "multi_block_24k",
                                  "run_then_text"])
def test_corpus_multi_block_inputs_split(name):
    """Sanity check of the corpus: these inputs really produce several blocks."""
    data = corpus.get(name).data
    assert len(ref.block_split(data, 0, len(data), 15)) >= 1


@pytest.mark.parametrize("case", STAGE_CASES)
def test_ref_block_sizes_consistent(case):
    data = case.data
    s = ref.lz77_optimal(data, numiterations=1)
    n = s.size
    if n == 0:
        return
    b0 = ref.calculate_block_size(s, 0, n, 0)
    length = ref.lz77_get_byte_range(s, 0, n)
    assert length == len(data)
    blocks = length // 65535 + (1 if length % 65535 else 0)
    assert b0 == blocks * 5 * 8 + length * 8
    b1 = ref.calculate_block_size(s, 0, n, 1)
    b2 = ref.calculate_block_size(s, 0, n, 2)
    auto = ref.calculate_block_size_auto_type(s, 0, n)
    if n > 1000:
        assert auto == min(b0, b2) or auto == b2
    else:
        assert auto == min(b0, b1, b2)


@pytest.mark.parametrize("seed", range(20))
@pytest.mark.parametrize("maxbits", [7, 9, 15])
def test_ref_length_limited_code_lengths_valid(seed, maxbits):
    r = corpus.Rng(seed)
    n = [19, 30, 32, 288][seed % 4]
    freqs = [r.below(1000) if r.below(3) else 0 for _ in range(n)]
    ret, lengths = ref.length_limited_code_lengths(freqs, maxbits)
    nonzero = sum(1 for f in freqs if f)
    if nonzero > (1 << maxbits):
        assert ret != 0
        return
    assert ret == 0
    assert all((l == 0) == (f == 0) for f, l in zip(freqs, lengths))
    assert max(lengths) <= maxbits
    if nonzero >= 2:
        assert sum(2.0 ** -l for l in lengths if l) == 1.0
    elif nonzero == 1:
        assert sorted(lengths)[-1] == 1


def test_ref_find_longest_match_matches_greedy_first_match():
    data = corpus.get("text_1k").data
    s = ref.lz77_greedy(data)
    # first match in the greedy store must be findable (lazy matching may
    # delay it by one position, so check either pos or pos-1)
    for i, (ll, d, p) in enumerate(s.as_tuples()):
        if d:
            dist, length, sub = ref.find_longest_match(data, p)
            assert length >= ll
            assert data[p - dist:p - dist + length] == data[p:p + length]
            for k in range(3, length + 1):
                assert data[p - sub[k]:p - sub[k] + k] == data[p:p + k]
            break
