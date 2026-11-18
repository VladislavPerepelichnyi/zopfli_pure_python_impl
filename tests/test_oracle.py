"""Byte-for-byte equality of zopfli_pure.compress with the py-zopfli oracle
(and of the raw deflate format with the reference C library / CLI).

On a mismatch the assertion message includes a localisation report
(stages.localize) naming the first pipeline stage whose Python output differs
from C, with the first differing index.

Cost: pure Python is ~100x slower than C, so the option grid is applied in
full only to tiny inputs; larger inputs get fewer combinations and fewer
iterations. Large inputs are marked slow (ZOPFLI_PURE_SLOW=1).
"""

import pytest

import corpus
import ref
from port import compress, compress_format, compress_fn, describe_bytes_diff
from stages import localize_report

pytestmark = pytest.mark.oracle

zopfli_oracle = pytest.importorskip("zopfli.zopfli")


def check(data, **opts):
    got = compress(data, **opts)
    want = zopfli_oracle.compress(data, **opts)
    assert isinstance(got, bytes), type(got)
    if got != want:
        raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        o = dict(opts)
        o.pop("gzip_mode", None)
        pytest.fail("%s (len(data)=%d, opts=%r)%s" % (
            describe_bytes_diff(got, want), len(raw), opts,
            localize_report(raw, **o)))


# Option grid (a subset of the cartesian product; each axis value appears).
GRID = [
    dict(),
    dict(numiterations=1),
    dict(numiterations=2),
    dict(numiterations=5),
    dict(numiterations=15),
    dict(numiterations=1, blocksplitting=0),
    dict(numiterations=5, blocksplitting=0),
    dict(numiterations=2, blocksplittingmax=0),
    dict(numiterations=2, blocksplittingmax=1),
    dict(numiterations=5, blocksplittingmax=3),
    dict(numiterations=1, blocksplittingmax=15),
    dict(numiterations=2, blocksplittinglast=1),
    dict(numiterations=2, blocksplitting=0, blocksplittingmax=0),
]


def _grid_id(o):
    return ",".join("%s=%s" % kv for kv in sorted(o.items())) or "defaults"


GRID_TINY_CASES = ["empty", "byte_00", "byte_ff", "two_ab", "three_aaa",
                   "abab_7", "all_bytes", "run_259", "hello", "random_100",
                   "text_200", "periodic_7_n120"]


@pytest.mark.parametrize("gzip_mode", [0, 1])
@pytest.mark.parametrize("opts", GRID, ids=_grid_id)
@pytest.mark.parametrize("name", GRID_TINY_CASES)
def test_grid_tiny(name, opts, gzip_mode):
    check(corpus.get(name).data, gzip_mode=gzip_mode, **opts)


@pytest.mark.parametrize("gzip_mode", [0, 1])
@pytest.mark.parametrize("case", corpus.params("tiny"))
def test_tiny_defaults(case, gzip_mode):
    check(case.data, gzip_mode=gzip_mode)


@pytest.mark.parametrize("case", corpus.params("small"))
def test_small_1_iteration(case):
    check(case.data, numiterations=1)


SMALL_SELECTED = ["gettysburg", "text_1k", "run_1000", "run_517",
                  "all_bytes_x4", "source_4k", "dna_then_text",
                  "src_then_random", "periodic_258", "periodic_259"]


@pytest.mark.parametrize("opts", [
    dict(numiterations=2, gzip_mode=1),
    dict(numiterations=5, blocksplittingmax=3),
    dict(numiterations=2, blocksplitting=0),
    dict(numiterations=1, blocksplittingmax=0),
], ids=_grid_id)
@pytest.mark.parametrize("name", SMALL_SELECTED)
def test_small_selected(name, opts):
    check(corpus.get(name).data, **opts)


@pytest.mark.parametrize("name", ["gettysburg", "text_1k", "dna_then_text",
                                  "periodic_100"])
def test_small_defaults(name):
    """Full default options (15 iterations) on a few small inputs."""
    check(corpus.get(name).data)


@pytest.mark.parametrize("case", corpus.params("medium"))
def test_medium_1_iteration(case):
    check(case.data, numiterations=1)


@pytest.mark.slow
@pytest.mark.parametrize("case", corpus.params("small", "medium"))
def test_small_medium_defaults_slow(case):
    check(case.data)


@pytest.mark.parametrize("gzip_mode", [0, 1])
@pytest.mark.parametrize("case", corpus.params("large"))
def test_large(case, gzip_mode):
    check(case.data, numiterations=5 if gzip_mode else 15, gzip_mode=gzip_mode)


@pytest.mark.parametrize("data", corpus.all_periods_params())
def test_all_periods_slow(data):
    check(data, numiterations=5)


@pytest.mark.huge
@pytest.mark.slow
@pytest.mark.parametrize("name,maker", [
    ("run_1000001", lambda: corpus.run(1000001)),
    ("text_1000100", lambda: corpus.pseudo_text(1000100, seed=99)),
])
def test_master_block_boundary(name, maker):
    """Inputs larger than ZOPFLI_MASTER_BLOCK_SIZE (1,000,000)."""
    check(maker(), numiterations=1)


# ---------------------------------------------------------- odd options

@pytest.mark.parametrize("numiterations", [0, -1, -(2 ** 31)])
@pytest.mark.parametrize("name", ["empty", "hello", "text_1k", "dna_then_text"])
def test_nonpositive_iterations(name, numiterations):
    """numiterations < 1: upstream never fills the LZ77 store and emits empty
    blocks (output does not decompress to the input). Must still match."""
    check(corpus.get(name).data, numiterations=numiterations)


@pytest.mark.parametrize("opts", [
    dict(blocksplitting=2), dict(blocksplitting=-1),
    dict(blocksplittingmax=-1), dict(blocksplittingmax=2 ** 31 - 1),
    dict(gzip_mode=2), dict(gzip_mode=-1), dict(gzip_mode=True),
    dict(verbose=0, blocksplittinglast=7),
], ids=_grid_id)
def test_odd_option_values(opts):
    check(corpus.get("dna_then_text").data, numiterations=1, **opts)


# ------------------------------------------------------------- str input

@pytest.mark.parametrize("text", [
    "", "a", "hello world", "héllo wörld € \U0001F600" * 5,
    "日本語のテキスト" * 20,
    corpus.GETTYSBURG.decode("ascii"),
], ids=["empty", "a", "ascii", "mixed_utf8", "cjk", "gettysburg"])
@pytest.mark.parametrize("gzip_mode", [0, 1])
def test_str_input(text, gzip_mode):
    check(text, numiterations=2, gzip_mode=gzip_mode)
    assert compress(text, numiterations=2, gzip_mode=gzip_mode) == \
        compress(text.encode("utf-8"), numiterations=2, gzip_mode=gzip_mode)


# ----------------------------------------------- raw deflate vs C reference

@pytest.mark.parametrize("fmt", [ref.FORMAT_GZIP, ref.FORMAT_ZLIB,
                                 ref.FORMAT_DEFLATE])
@pytest.mark.parametrize("case", corpus.params("tiny") + [
    pytest.param(corpus.get(n), id=n) for n in
    ("gettysburg", "random_4000", "dna_then_text", "run_1000")])
def test_compress_format_vs_ref(case, fmt):
    ref.require()
    opts = dict(numiterations=2)
    got = compress_format(fmt, case.data, **opts)
    want = ref.compress_format(fmt, case.data, **opts)
    if got != want:
        pytest.fail(describe_bytes_diff(bytes(got), want) +
                    localize_report(case.data, **opts))


@pytest.mark.parametrize("name", ["hello", "text_1k", "random_4000"])
@pytest.mark.parametrize("fmt", [ref.FORMAT_GZIP, ref.FORMAT_ZLIB,
                                 ref.FORMAT_DEFLATE])
def test_vs_cli(name, fmt):
    ref.require()
    data = corpus.get(name).data
    got = compress_format(fmt, data, numiterations=3)
    assert got == ref.cli_compress(data, fmt, numiterations=3)


# --------------------------------------------------------- property tests

try:
    from hypothesis import given, strategies as st
except ImportError:  # pragma: no cover
    given = None

if given is not None:
    _opts_st = st.fixed_dictionaries({
        "numiterations": st.sampled_from([1, 2, 5]),
        "blocksplitting": st.sampled_from([0, 1]),
        "blocksplittingmax": st.sampled_from([0, 1, 3, 15]),
        "gzip_mode": st.sampled_from([0, 1]),
    })

    # structured data: concatenation of runs, repeats of earlier content,
    # small-alphabet text and random bytes
    _chunk = st.one_of(
        st.binary(max_size=40),
        st.tuples(st.integers(0, 255), st.integers(1, 300)).map(
            lambda t: bytes([t[0]]) * t[1]),
        st.text(alphabet="ab \n", max_size=60).map(lambda s: s.encode()),
        st.tuples(st.binary(min_size=1, max_size=8), st.integers(1, 40)).map(
            lambda t: t[0] * t[1]),
    )
    _structured = st.lists(_chunk, max_size=8).map(b"".join).filter(
        lambda b: len(b) <= 1500)

    @given(data=st.binary(max_size=300), opts=_opts_st)
    def test_property_random_bytes(data, opts):
        compress_fn()  # skip early if not available
        check(data, **opts)

    @given(data=_structured, opts=_opts_st)
    def test_property_structured(data, opts):
        compress_fn()
        check(data, **opts)
