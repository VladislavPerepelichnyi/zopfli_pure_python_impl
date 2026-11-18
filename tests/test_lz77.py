"""Differential tests: zopfli_pure.{symbols,hash,cache,lz77} against the C reference.

The C side is tools/harness/lz77/lz77_harness.c, a unity build of the
reference hash.c / cache.c / lz77.c / util.c compiled into a shared library
(asserts enabled) and driven through ctypes in lockstep with the Python port.
Skips cleanly if gcc or the reference sources are missing.
"""

import array
import ctypes
import os
import random
import shutil
import subprocess

import pytest

from zopfli_pure import symbols, cache as pcache, lz77 as plz77
from zopfli_pure.hash import Hash, reset_hash, warmup_hash, update_hash
from zopfli_pure.util import Options, ZOPFLI_WINDOW_SIZE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.environ.get(
    "ZOPFLI_REFERENCE_SRC",
    "/home/vlad/thesis/wasm/pure_python_impl/zopfli_reference/src/zopfli")
HARNESS_SRC = os.path.join(ROOT, "tools", "harness", "lz77", "lz77_harness.c")
BUILD_DIR = os.path.join(ROOT, "tools", "build")
LIB_PATH = os.path.join(BUILD_DIR, "lz77_harness.so")

pytestmark = pytest.mark.oracle

P = ctypes.c_void_p
SZ = ctypes.c_size_t
U16P = ctypes.POINTER(ctypes.c_ushort)
I32P = ctypes.POINTER(ctypes.c_int)
SZP = ctypes.POINTER(ctypes.c_size_t)
U8P = ctypes.POINTER(ctypes.c_ubyte)


def _build():
    if shutil.which("gcc") is None:
        pytest.skip("gcc not available")
    if not os.path.isfile(os.path.join(REF, "lz77.c")):
        pytest.skip("reference sources not found at %s" % REF)
    os.makedirs(BUILD_DIR, exist_ok=True)
    deps = [HARNESS_SRC] + [os.path.join(REF, f) for f in
                            ("lz77.c", "hash.c", "cache.c", "util.c",
                             "lz77.h", "hash.h", "cache.h", "util.h",
                             "symbols.h", "zopfli.h")]
    if (not os.path.exists(LIB_PATH)
            or os.path.getmtime(LIB_PATH) < max(os.path.getmtime(d) for d in deps)):
        subprocess.check_call(["gcc", "-O1", "-g", "-shared", "-fPIC",
                               "-I", REF, HARNESS_SRC, "-o", LIB_PATH])
    lib = ctypes.CDLL(LIB_PATH)
    sig = {
        "hs_dist_extra_bits": (ctypes.c_int, [ctypes.c_int]),
        "hs_dist_extra_bits_value": (ctypes.c_int, [ctypes.c_int]),
        "hs_dist_symbol": (ctypes.c_int, [ctypes.c_int]),
        "hs_length_extra_bits": (ctypes.c_int, [ctypes.c_int]),
        "hs_length_extra_bits_value": (ctypes.c_int, [ctypes.c_int]),
        "hs_length_symbol": (ctypes.c_int, [ctypes.c_int]),
        "hs_length_symbol_extra_bits": (ctypes.c_int, [ctypes.c_int]),
        "hs_dist_symbol_extra_bits": (ctypes.c_int, [ctypes.c_int]),
        "hh_new": (P, []),
        "hh_free": (None, [P]),
        "hh_reset": (None, [P]),
        "hh_warmup": (None, [ctypes.c_char_p, SZ, SZ, P]),
        "hh_update": (None, [ctypes.c_char_p, SZ, SZ, P]),
        "hh_prepare": (None, [ctypes.c_char_p, SZ, SZ, P]),
        "hh_val": (ctypes.c_int, [P]),
        "hh_val2": (ctypes.c_int, [P]),
        "hh_head": (I32P, [P]),
        "hh_head2": (I32P, [P]),
        "hh_hashval": (I32P, [P]),
        "hh_hashval2": (I32P, [P]),
        "hh_prev": (U16P, [P]),
        "hh_prev2": (U16P, [P]),
        "hh_same": (U16P, [P]),
        "hb_new": (P, [SZ, SZ, ctypes.c_int]),
        "hb_free": (None, [P]),
        "hb_lmc_length": (U16P, [P]),
        "hb_lmc_dist": (U16P, [P]),
        "hb_lmc_sublen": (U8P, [P]),
        "hb_find": (ctypes.c_uint32, [P, P, ctypes.c_char_p, SZ, SZ, SZ, U16P]),
        "hc_sublen_to_cache": (None, [U16P, SZ, SZ, P]),
        "hc_cache_to_sublen": (None, [P, SZ, SZ, U16P]),
        "hc_max_cached_sublen": (ctypes.c_uint, [P, SZ, SZ]),
        "hl_new": (P, [ctypes.c_char_p]),
        "hl_free": (None, [P]),
        "hl_size": (SZ, [P]),
        "hl_litlens": (U16P, [P]),
        "hl_dists": (U16P, [P]),
        "hl_pos": (SZP, [P]),
        "hl_ll_symbol": (U16P, [P]),
        "hl_d_symbol": (U16P, [P]),
        "hl_ll_counts": (SZP, [P]),
        "hl_d_counts": (SZP, [P]),
        "hl_store": (None, [ctypes.c_ushort, ctypes.c_ushort, SZ, P]),
        "hl_copy": (None, [P, P]),
        "hl_append": (None, [P, P]),
        "hl_byte_range": (SZ, [P, SZ, SZ]),
        "hl_histogram": (None, [P, SZ, SZ, SZP, SZP]),
        "hl_greedy": (None, [P, ctypes.c_char_p, SZ, SZ, P, P]),
    }
    for name, (res, args) in sig.items():
        fn = getattr(lib, name)
        fn.restype = res
        fn.argtypes = args
    return lib


@pytest.fixture(scope="module")
def clib():
    return _build()


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------

def _text(rng, n):
    words = ("the of and to in is that for it as was with be by on not he "
             "this are or his from at which but have an they you were her "
             "compression zopfli deflate huffman window hash match length "
             "distance block symbol literal").split()
    out = []
    size = 0
    while size < n:
        w = rng.choice(words)
        if rng.random() < 0.1:
            w = w.capitalize()
        out.append(w)
        size += len(w) + 1
        out.append("." if rng.random() < 0.05 else " ")
    return "".join(out).encode()[:n]


def _runs(rng, n, alphabet=b"ab\x00\xff", maxrun=700):
    out = bytearray()
    while len(out) < n:
        out += bytes([rng.choice(alphabet)]) * rng.randint(1, maxrun)
    return bytes(out[:n])


def _skewed(rng, n, p=0.02):
    return bytes(1 if rng.random() < p else 0 for _ in range(n))


def _ref_sources():
    blob = b""
    for f in sorted(os.listdir(REF)) if os.path.isdir(REF) else []:
        if f.endswith((".c", ".h")):
            with open(os.path.join(REF, f), "rb") as fh:
                blob += fh.read()
    return blob


def small_inputs():
    rng = random.Random(1234)
    return [
        ("empty", b""),
        ("1byte", b"a"),
        ("2bytes", b"ab"),
        ("3bytes", b"abc"),
        ("aaa", b"aaa"),
        ("aaaa", b"aaaa"),
        ("abab5", b"ababa"),
        ("run1000", b"a" * 1000),
        ("run3000_tail", b"x" * 3000 + b"yz"),
        ("period3", b"abc" * 700),
        ("period7", b"abcdefg" * 400),
        ("period300", bytes(rng.randrange(256) for _ in range(300)) * 12),
        ("text", _text(rng, 6000)),
        ("random", bytes(rng.randrange(256) for _ in range(5000))),
        ("lowentropy", bytes(rng.choice(b"ACGT") for _ in range(6000))),
        ("runs", _runs(rng, 8000)),
        ("binary01", bytes(rng.randrange(2) for _ in range(5000))),
    ]


def large_inputs():
    rng = random.Random(99)
    src = _ref_sources()
    out = [
        ("text40k", _text(rng, 40000)),
        ("random70k", bytes(rng.randrange(256) for _ in range(70000))),
        ("runs70k", _runs(rng, 70000, maxrun=3000)),
        ("lowentropy70k", bytes(rng.choice(b"ACGT") for _ in range(70000))),
        ("skewed70k", _skewed(rng, 70000)),
        ("longrun", b"q" * 70000 + b"r" + b"q" * 1000),
        ("period5_70k", b"hello" * 14000),
    ]
    if src:
        out.append(("refsrc", src[:140000]))
    return out


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _carr(ptr, n):
    """Copy n elements from a ctypes pointer into a Python list."""
    return ptr[:n]


def compare_hash(clib, ch, ph, label):
    assert clib.hh_val(ch) == ph.val, label
    assert clib.hh_val2(ch) == ph.val2, label
    W = ZOPFLI_WINDOW_SIZE
    assert _carr(clib.hh_head(ch), 65536) == ph.head, label
    assert _carr(clib.hh_head2(ch), 65536) == ph.head2, label
    assert _carr(clib.hh_prev(ch), W) == ph.prev, label
    assert _carr(clib.hh_prev2(ch), W) == ph.prev2, label
    assert _carr(clib.hh_hashval(ch), W) == ph.hashval, label
    assert _carr(clib.hh_hashval2(ch), W) == ph.hashval2, label
    assert _carr(clib.hh_same(ch), W) == ph.same, label


def compare_lmc(clib, cs, ps, n, label):
    assert _carr(clib.hb_lmc_length(cs), n) == ps.lmc.length, label
    assert _carr(clib.hb_lmc_dist(cs), n) == ps.lmc.dist, label
    assert bytes(_carr(clib.hb_lmc_sublen(cs), 24 * n)) == bytes(ps.lmc.sublen), label


def run_find_longest_match(clib, data, instart, add_lmc, plan, passes=1,
                           check_hash_every=0):
    """Drive C and Python find_longest_match in lockstep.

    plan(pos) -> list of (limit, use_sublen) calls made at that position, in
    order. One sublen buffer per side is reused for all calls (like the C
    callers), so stale entries are compared too. Returns the number of
    find_longest_match calls compared.
    """
    size = len(data)
    ch = clib.hh_new()
    cs = clib.hb_new(instart, size, 1 if add_lmc else 0)
    csub = (ctypes.c_ushort * 259)()
    psub = [0] * 259
    ph = Hash(ZOPFLI_WINDOW_SIZE)
    ps = plz77.BlockState(Options(), instart, size, add_lmc)
    calls = 0
    try:
        for npass in range(passes):
            if instart == size:
                break
            clib.hh_prepare(data, instart, size, ch)
            windowstart = instart - ZOPFLI_WINDOW_SIZE if instart > ZOPFLI_WINDOW_SIZE else 0
            reset_hash(ZOPFLI_WINDOW_SIZE, ph)
            warmup_hash(data, windowstart, size, ph)
            for i in range(windowstart, instart):
                update_hash(data, i, size, ph)
            for pos in range(instart, size):
                clib.hh_update(data, pos, size, ch)
                update_hash(data, pos, size, ph)
                for limit, use_sublen in plan(pos):
                    r = clib.hb_find(cs, ch, data, pos, size, limit,
                                     csub if use_sublen else None)
                    cd, cl = r & 0xFFFF, r >> 16
                    pd, pl = plz77.find_longest_match(
                        ps, ph, data, pos, size, limit,
                        psub if use_sublen else None)
                    calls += 1
                    if (cd, cl) != (pd, pl) or (
                            use_sublen and bytes(csub) != array.array("H", psub).tobytes()):
                        raise AssertionError(
                            "mismatch at pos %d pass %d limit %d sublen=%s: "
                            "C (dist %d, len %d) Py (dist %d, len %d); "
                            "sublen equal: %s" % (
                                pos, npass, limit, use_sublen, cd, cl, pd, pl,
                                list(csub) == psub))
                if check_hash_every and pos % check_hash_every == 0:
                    compare_hash(clib, ch, ph, "pos %d" % pos)
            compare_hash(clib, ch, ph, "end of pass %d" % npass)
            if add_lmc:
                compare_lmc(clib, cs, ps, size - instart, "end of pass %d" % npass)
    finally:
        clib.hh_free(ch)
        clib.hb_free(cs)
    return calls


def plan_squeeze(pos):
    return ((258, True),)


def plan_nosublen(pos):
    return ((258, False),)


def make_plan_mixed(seed):
    rng = random.Random(seed)
    cache = {}

    def plan(pos):
        # Deterministic per (pos, pass): use a dict keyed by pos, regenerated
        # on each pass via a counter so passes differ.
        k = cache.get(pos, 0)
        cache[pos] = k + 1
        r = random.Random(seed * 1000003 + pos * 7 + k)
        calls = []
        for _ in range(r.randint(1, 4)):
            x = r.random()
            if x < 0.4:
                limit = 258
            elif x < 0.6:
                limit = r.randint(3, 10)
            else:
                limit = r.randint(3, 258)
            calls.append((limit, r.random() < 0.7))
        return calls
    del rng
    return plan


def make_store_pair(clib, data, triples):
    cst = clib.hl_new(data)
    pst = plz77.LZ77Store(data)
    for length, dist, pos in triples:
        clib.hl_store(length, dist, pos, cst)
        plz77.store_lit_len_dist(length, dist, pos, pst)
    return cst, pst


def compare_store(clib, cst, pst, label=""):
    n = clib.hl_size(cst)
    assert n == pst.size == len(pst.litlens), label
    for name in ("litlens", "dists", "pos", "ll_symbol", "d_symbol"):
        if n:
            assert _carr(getattr(clib, "hl_" + name)(cst), n) == getattr(pst, name), (label, name)
        else:
            assert getattr(pst, name) == [], (label, name)
    llsize = 288 * ((n + 287) // 288)
    dsize = 32 * ((n + 31) // 32)
    assert len(pst.ll_counts) == llsize, label
    assert len(pst.d_counts) == dsize, label
    if n:
        assert _carr(clib.hl_ll_counts(cst), llsize) == pst.ll_counts, label
        assert _carr(clib.hl_d_counts(cst), dsize) == pst.d_counts, label


def run_greedy(clib, data, instart, add_lmc):
    size = len(data)
    ch = clib.hh_new()
    cs = clib.hb_new(instart, size, 1 if add_lmc else 0)
    cst = clib.hl_new(data)
    ph = Hash(ZOPFLI_WINDOW_SIZE)
    ps = plz77.BlockState(Options(), instart, size, add_lmc)
    pst = plz77.LZ77Store(data)
    clib.hl_greedy(cs, data, instart, size, cst, ch)
    plz77.lz77_greedy(ps, data, instart, size, pst, ph)
    try:
        compare_store(clib, cst, pst, "greedy")
        if instart < size:
            compare_hash(clib, ch, ph, "after greedy")
        if add_lmc:
            compare_lmc(clib, cs, ps, size - instart, "after greedy")
    except Exception:
        clib.hl_free(cst)
        raise
    finally:
        clib.hh_free(ch)
        clib.hb_free(cs)
    return cst, pst


# --------------------------------------------------------------------------
# Tests: symbols
# --------------------------------------------------------------------------

def test_symbols(clib):
    for d in range(0, 32769):
        assert symbols.get_dist_symbol(d) == clib.hs_dist_symbol(d) == symbols.DIST_SYMBOL[d]
        assert symbols.get_dist_extra_bits(d) == clib.hs_dist_extra_bits(d) == symbols.DIST_EXTRA_BITS[d]
        assert (symbols.get_dist_extra_bits_value(d) == clib.hs_dist_extra_bits_value(d)
                == symbols.DIST_EXTRA_BITS_VALUE[d])
    for l in range(259):
        assert symbols.get_length_symbol(l) == clib.hs_length_symbol(l)
        assert symbols.get_length_extra_bits(l) == clib.hs_length_extra_bits(l)
        assert symbols.get_length_extra_bits_value(l) == clib.hs_length_extra_bits_value(l)
    for s in range(257, 286):
        assert symbols.get_length_symbol_extra_bits(s) == clib.hs_length_symbol_extra_bits(s)
    for s in range(30):
        assert symbols.get_dist_symbol_extra_bits(s) == clib.hs_dist_symbol_extra_bits(s)


# --------------------------------------------------------------------------
# Tests: hash
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name,data", small_inputs() + [
    ("run70k", b"z" * 70000), ("runs40k", _runs(random.Random(5), 40000))])
def test_hash_update(clib, name, data):
    size = len(data)
    if size == 0:
        return
    ch = clib.hh_new()
    ph = Hash(ZOPFLI_WINDOW_SIZE)
    try:
        compare_hash(clib, ch, ph, "fresh")
        clib.hh_warmup(data, 0, size, ch)
        warmup_hash(data, 0, size, ph)
        step = max(1, size // 7)
        for pos in range(size):
            clib.hh_update(data, pos, size, ch)
            update_hash(data, pos, size, ph)
            assert clib.hh_val(ch) == ph.val and clib.hh_val2(ch) == ph.val2, pos
            if pos % step == 0:
                compare_hash(clib, ch, ph, "pos %d" % pos)
        compare_hash(clib, ch, ph, "end")
        clib.hh_reset(ch)
        reset_hash(ZOPFLI_WINDOW_SIZE, ph)
        compare_hash(clib, ch, ph, "reset")
    finally:
        clib.hh_free(ch)


# --------------------------------------------------------------------------
# Tests: cache
# --------------------------------------------------------------------------

def test_cache_roundtrip(clib):
    rng = random.Random(7)
    n = 64
    cs = clib.hb_new(0, n, 1)
    ps = plz77.BlockState(Options(), 0, n, 1)
    try:
        for pos in range(n):
            length = rng.choice([0, 1, 2, 3, 4, 10, 100, 257, 258, rng.randint(3, 258)])
            ndistinct = rng.choice([1, 2, 7, 8, 9, 30])
            # sublen: non-decreasing distances for increasing lengths.
            sub = [rng.randrange(65536) for _ in range(3)]
            cuts = sorted(rng.sample(range(3, 259), min(ndistinct, 256)))
            d = rng.randint(1, 50)
            for i in range(3, 259):
                if i in cuts:
                    d += rng.randint(1, 3000)
                sub.append(min(d, 32768))
            csub = (ctypes.c_ushort * 259)(*sub)
            clib.hc_sublen_to_cache(csub, pos, length, cs)
            pcache.sublen_to_cache(sub, pos, length, ps.lmc)
            assert clib.hc_max_cached_sublen(cs, pos, length) == pcache.max_cached_sublen(ps.lmc, pos, length)
            for qlen in (0, 2, 3, length, 258):
                cout = (ctypes.c_ushort * 259)(*([0xAAAA] * 259))
                pout = [0xAAAA] * 259
                clib.hc_cache_to_sublen(cs, pos, qlen, cout)
                pcache.cache_to_sublen(ps.lmc, pos, qlen, pout)
                assert list(cout) == pout, (pos, length, qlen)
        compare_lmc(clib, cs, ps, n, "cache")
    finally:
        clib.hb_free(cs)


# --------------------------------------------------------------------------
# Tests: find_longest_match
# --------------------------------------------------------------------------

SMALL = small_inputs()


@pytest.mark.parametrize("name,data", SMALL, ids=[n for n, _ in SMALL])
@pytest.mark.parametrize("add_lmc", [0, 1])
def test_find_longest_match_small(clib, name, data, add_lmc):
    run_find_longest_match(clib, data, 0, add_lmc, plan_squeeze,
                           passes=2, check_hash_every=997)
    run_find_longest_match(clib, data, 0, add_lmc, plan_nosublen, passes=1)
    run_find_longest_match(clib, data, 0, add_lmc, make_plan_mixed(len(data)),
                           passes=2)
    if len(data) > 10:
        run_find_longest_match(clib, data, len(data) // 3, add_lmc,
                               make_plan_mixed(3), passes=2)


LARGE = large_inputs()


@pytest.mark.slow
@pytest.mark.parametrize("name,data", LARGE, ids=[n for n, _ in LARGE])
def test_find_longest_match_large(clib, name, data):
    run_find_longest_match(clib, data, 0, 1, plan_squeeze, passes=2)
    run_find_longest_match(clib, data, 0, 0, make_plan_mixed(11), passes=1)
    # instart beyond the window: windowstart > 0.
    run_find_longest_match(clib, data, min(len(data) - 1, 40000), 1,
                           make_plan_mixed(12), passes=2)


# --------------------------------------------------------------------------
# Tests: greedy, store, histogram
# --------------------------------------------------------------------------

def _check_histograms(clib, cst, pst, rng, nranges):
    n = pst.size
    cll = (ctypes.c_size_t * 288)()
    cd = (ctypes.c_size_t * 32)()
    ranges = [(0, n), (0, 0), (n, n)]
    if n:
        ranges += [(0, 1), (n - 1, n), (0, min(n, 864)), (0, min(n, 865)),
                   (1, min(n, 866))]
    for _ in range(nranges):
        if n == 0:
            break
        a = rng.randrange(n + 1)
        b = rng.randrange(a, n + 1)
        ranges.append((a, b))
        if a + 900 <= n:
            ranges.append((a, rng.randrange(a + 864, n + 1)))
    for a, b in ranges:
        if a > b:
            continue
        pll = [7] * 288
        pd = [7] * 32
        if n:
            clib.hl_histogram(cst, a, b, cll, cd)
            plz77.lz77_get_histogram(pst, a, b, pll, pd)
            assert list(cll) == pll, (a, b)
            assert list(cd) == pd, (a, b)
            # Also the plain definition.
            exp_ll = [0] * 288
            exp_d = [0] * 32
            for i in range(a, b):
                exp_ll[pst.ll_symbol[i]] += 1
                if pst.dists[i]:
                    exp_d[pst.d_symbol[i]] += 1
            assert pll == exp_ll and pd == exp_d
            assert clib.hl_byte_range(cst, a, b) == plz77.lz77_get_byte_range(pst, a, b)
    return len(ranges)


@pytest.mark.parametrize("name,data", SMALL, ids=[n for n, _ in SMALL])
@pytest.mark.parametrize("add_lmc", [0, 1])
def test_greedy_small(clib, name, data, add_lmc):
    rng = random.Random(len(data))
    for instart in sorted({0, len(data) // 2, len(data)}):
        cst, pst = run_greedy(clib, data, instart, add_lmc)
        try:
            _check_histograms(clib, cst, pst, rng, 30)
        finally:
            clib.hl_free(cst)


@pytest.mark.slow
@pytest.mark.parametrize("name,data", LARGE, ids=[n for n, _ in LARGE])
def test_greedy_large(clib, name, data):
    rng = random.Random(len(data))
    for instart, add_lmc in ((0, 1), (40000, 0)):
        cst, pst = run_greedy(clib, data, instart, add_lmc)
        try:
            _check_histograms(clib, cst, pst, rng, 100)
        finally:
            clib.hl_free(cst)


def test_store_copy_append(clib):
    rng = random.Random(3)
    data = _text(rng, 30000)
    # Positions are absolute and increase along a store, and across stores in
    # the order they get appended (b, then a), as in real use;
    # ZopfliLZ77GetByteRange would wrap (size_t) otherwise.
    def triples(n, pos, litprob):
        out = []
        for _ in range(n):
            if rng.random() < litprob:
                out.append((rng.randrange(256), 0, pos))
                pos += 1
            else:
                length = rng.randint(3, 258)
                out.append((length, rng.randint(1, 32768), pos))
                pos += length
        return out
    triples1 = triples(1000, 500000, 0.5)
    triples2 = triples(333, 0, 0.0)
    ca, pa = make_store_pair(clib, data, triples1)
    cb, pb = make_store_pair(clib, data, triples2)
    ce, pe = make_store_pair(clib, data, [])
    try:
        compare_store(clib, ca, pa, "a")
        compare_store(clib, cb, pb, "b")
        clib.hl_append(ca, cb)
        plz77.append_lz77_store(pa, pb)
        compare_store(clib, cb, pb, "append")
        clib.hl_append(ce, cb)
        plz77.append_lz77_store(pe, pb)
        compare_store(clib, cb, pb, "append empty")
        clib.hl_copy(cb, ca)
        plz77.copy_lz77_store(pb, pa)
        compare_store(clib, ca, pa, "copy")
        assert pa.data is pb.data
        clib.hl_copy(ce, ca)
        plz77.copy_lz77_store(pe, pa)
        compare_store(clib, ca, pa, "copy empty")
        _check_histograms(clib, cb, pb, rng, 200)
        # The copy is independent of its source.
        plz77.copy_lz77_store(pb, pa)
        plz77.store_lit_len_dist(65, 0, 0, pa)
        assert pa.size == pb.size + 1
    finally:
        for p in (ca, cb, ce):
            clib.hl_free(p)
