"""Differential tests: katajainen.py, tree.py, bitwriter.py vs the reference C.

The C side is tools/harness/tree/harness.c, compiled together with the
unmodified reference sources into tools/build/tree/ (gitignored). Tests are
skipped when gcc or the reference sources are not available.
"""

import ctypes
import os
import random
import shutil
import subprocess

import pytest

from zopfli_pure.bitwriter import BitWriter
from zopfli_pure.katajainen import length_limited_code_lengths
from zopfli_pure.tree import (calculate_bit_lengths, calculate_entropy,
                              lengths_to_symbols)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS = os.path.join(REPO, "tools", "harness", "tree", "harness.c")
BUILD_DIR = os.path.join(REPO, "tools", "build", "tree")
LIB = os.path.join(BUILD_DIR, "libtree_harness.so")
# deflate.c is #included by harness.c (for its static bit writers).
REF_SOURCES = ["blocksplitter.c", "cache.c", "hash.c", "katajainen.c",
               "lz77.c", "squeeze.c", "tree.c", "util.c"]
CFLAGS = ["-O2", "-ffp-contract=off", "-fPIC", "-shared", "-w"]


def _find_ref_dir():
    env = os.environ.get("ZOPFLI_REFERENCE_DIR")
    cands = [env] if env else []
    d = REPO
    while True:
        cands.append(os.path.join(d, "zopfli_reference", "src", "zopfli"))
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "katajainen.c")):
            return c
    return None


def _build():
    gcc = shutil.which("gcc")
    ref = _find_ref_dir()
    if gcc is None or ref is None:
        return None
    srcs = [HARNESS] + [os.path.join(ref, s) for s in REF_SOURCES]
    if os.path.exists(LIB):
        newest = max(os.path.getmtime(s) for s in srcs)
        if os.path.getmtime(LIB) >= newest:
            return LIB
    os.makedirs(BUILD_DIR, exist_ok=True)
    flags = list(CFLAGS)
    if os.uname().machine == "x86_64":
        flags += ["-march=x86-64", "-mno-fma"]
    subprocess.check_call([gcc] + flags + ["-I", ref, "-o", LIB] + srcs + ["-lm"])
    return LIB


def load_clib():
    """Build (if needed) and load the C harness; None if it cannot be built."""
    path = _build()
    if path is None:
        return None
    lib = ctypes.CDLL(path)
    P = ctypes.POINTER
    lib.h_length_limited_code_lengths.argtypes = [
        P(ctypes.c_size_t), ctypes.c_int, ctypes.c_int, P(ctypes.c_uint)]
    lib.h_length_limited_code_lengths.restype = ctypes.c_int
    lib.h_calculate_bit_lengths.argtypes = [
        P(ctypes.c_size_t), ctypes.c_size_t, ctypes.c_int, P(ctypes.c_uint)]
    lib.h_calculate_bit_lengths.restype = None
    lib.h_lengths_to_symbols.argtypes = [
        P(ctypes.c_uint), ctypes.c_size_t, ctypes.c_uint, P(ctypes.c_uint)]
    lib.h_lengths_to_symbols.restype = None
    lib.h_calculate_entropy.argtypes = [
        P(ctypes.c_size_t), ctypes.c_size_t, P(ctypes.c_double)]
    lib.h_calculate_entropy.restype = None
    lib.h_bitwriter.argtypes = [
        ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint, P(ctypes.c_uint),
        ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t, P(ctypes.c_uint)]
    lib.h_bitwriter.restype = ctypes.c_size_t
    return lib


@pytest.fixture(scope="module")
def clib():
    lib = load_clib()
    if lib is None:
        pytest.skip("gcc or reference C sources not available")
    return lib


# ---------------------------------------------------------------- C calls

def c_llcl(lib, freqs, n, maxbits):
    f = (ctypes.c_size_t * max(n, 1))(*freqs[:n])
    bl = (ctypes.c_uint * max(n, 1))(*([0xDEAD] * max(n, 1)))
    r = lib.h_length_limited_code_lengths(f, n, maxbits, bl)
    return r, list(bl[:n])


def c_cbl(lib, freqs, n, maxbits):
    f = (ctypes.c_size_t * n)(*freqs)
    bl = (ctypes.c_uint * n)()
    lib.h_calculate_bit_lengths(f, n, maxbits, bl)
    return list(bl)


def c_lts(lib, lengths, maxbits):
    n = len(lengths)
    a = (ctypes.c_uint * n)(*lengths)
    s = (ctypes.c_uint * n)()
    lib.h_lengths_to_symbols(a, n, maxbits, s)
    return list(s)


def c_entropy(lib, counts):
    n = len(counts)
    a = (ctypes.c_size_t * max(n, 1))(*counts)
    b = (ctypes.c_double * max(n, 1))()
    lib.h_calculate_entropy(a, n, b)
    return list(b[:n])


def c_bitwriter(lib, init, bp0, ops):
    flat = [v for op in ops for v in op]
    a = (ctypes.c_uint * max(len(flat), 1))(*flat)
    cap = len(init) + sum(1 + (op[2] if op[0] else 1) // 8 for op in ops) + 8
    res = ctypes.create_string_buffer(cap)
    bp = ctypes.c_uint()
    size = lib.h_bitwriter(bytes(init), len(init), bp0, a, len(ops), res,
                           cap, ctypes.byref(bp))
    assert size != ctypes.c_size_t(-1).value
    return res.raw[:size], bp.value


# ---------------------------------------------------------- generators

def _fib_weights(k):
    a, b, out = 1, 1, []
    for _ in range(k):
        out.append(a)
        a, b = b, a + b
    return out


def gen_freqs(rng, n, kind):
    f = [0] * n
    if kind == "zero":
        pass
    elif kind == "one":
        f[rng.randrange(n)] = rng.choice([1, 2, 7, 1000, rng.randrange(1, 1 << 20)])
    elif kind == "two":
        i, j = rng.sample(range(n), 2)
        f[i] = rng.randrange(1, 1000)
        f[j] = rng.randrange(1, 1000)
    elif kind == "sparse":
        for i in rng.sample(range(n), rng.randrange(3, max(4, n // 6) + 1)):
            f[i] = rng.randrange(1, 200)
    elif kind == "dense":
        for i in range(n):
            if rng.random() < 0.9:
                f[i] = rng.randrange(1, 5000)
    elif kind == "equal":
        w = rng.choice([1, 2, 3, 100, rng.randrange(1, 1 << 20)])
        for i in range(n):
            if rng.random() < rng.choice([0.3, 0.7, 1.0]):
                f[i] = w
    elif kind == "fewvalues":
        vals = [rng.randrange(1, 50) for _ in range(3)]
        for i in range(n):
            if rng.random() < 0.8:
                f[i] = rng.choice(vals)
    elif kind == "fib":
        # Up to F(30) * 3 < 2**22 (see the "large" note below).
        k = rng.randrange(3, min(n, 30) + 1)
        ws = _fib_weights(k)
        if rng.random() < 0.5:
            ws = [w * rng.randrange(1, 4) for w in ws]
        idx = rng.sample(range(n), k)
        for i, w in zip(idx, ws):
            f[i] = w
    elif kind == "geometric":
        k = rng.randrange(3, n + 1)
        idx = rng.sample(range(n), k)
        for t, i in enumerate(idx):
            f[i] = max(1, int(1.6 ** min(t, 32)))  # < 2**22
    elif kind == "large":
        # Large counts, but max - min < 2**22 so that the C comparator's
        # size_t -> int truncation is harmless (see UPSTREAM_FINDINGS).
        base = rng.choice([0, 1 << 20, 1 << 30, 1 << 40, (1 << 55) - (1 << 22)])
        for i in range(n):
            if rng.random() < 0.8:
                f[i] = base + rng.randrange(1, 1 << 22)
                if f[i] >= 1 << 55:
                    f[i] = (1 << 55) - 1
    elif kind == "zopfli":
        # Realistic: counts summing to at most ~1e6 (a master block).
        total = rng.randrange(1, 1000001)
        k = rng.randrange(1, n + 1)
        idx = rng.sample(range(n), k)
        for _ in range(min(total, 3000)):
            f[rng.choice(idx)] += 1
        scale = max(1, total // 3000)
        f = [v * scale for v in f]
    else:
        raise ValueError(kind)
    return f


KINDS = ["zero", "one", "two", "sparse", "dense", "equal", "fewvalues", "fib",
         "geometric", "large", "zopfli"]
CONFIGS = [(288, 15), (32, 15), (19, 7), (288, 7), (32, 7)]


# ------------------------------------------------------------------ tests

def test_length_limited_code_lengths(clib):
    rng = random.Random(1234)
    ncases = 0
    for n, maxbits in CONFIGS:
        for kind in KINDS:
            for _ in range(70):
                f = gen_freqs(rng, n, kind)
                expect = c_llcl(clib, f, n, maxbits)
                bl = [0xBEEF] * n
                r = length_limited_code_lengths(f, n, maxbits, bl)
                assert (r, bl) == expect, (n, maxbits, kind, f)
                ncases += 1
    assert ncases == len(CONFIGS) * len(KINDS) * 70


def test_length_limited_other_maxbits(clib):
    """All maxbits 0..15 and small n, including the error returns."""
    rng = random.Random(99)
    for _ in range(3000):
        n = rng.randrange(0, 40)
        maxbits = rng.randrange(0, 16)
        f = [rng.choice([0, 0, 1, 1, 2, rng.randrange(1, 10000)]) for _ in range(n)]
        if rng.random() < 0.3 and n:
            f = gen_freqs(rng, n, rng.choice(["fib", "equal", "geometric"]) if n >= 3 else "one")
        expect = c_llcl(clib, f, n, maxbits)
        bl = [7] * n
        r = length_limited_code_lengths(f, n, maxbits, bl)
        assert (r, bl) == expect, (n, maxbits, f)


def test_length_limited_weight_too_large(clib):
    """A weight >= 2**55 makes C return 1 (the count needs 9 bits)."""
    for big in [1 << 55, (1 << 55) + 5, (1 << 64) - 1]:
        f = [0] * 19
        f[3], f[5], f[7] = 4, big, 9
        assert c_llcl(clib, f, 19, 7) == (1, [0] * 19)
        bl = [3] * 19
        assert length_limited_code_lengths(f, 19, 7, bl) == 1
        assert bl == [0] * 19
    # Two symbols: the 2**55 check is not reached.
    f = [0] * 19
    f[2], f[4] = (1 << 64) - 1, 1
    bl = [0] * 19
    assert (length_limited_code_lengths(f, 19, 7, bl), bl) == c_llcl(clib, f, 19, 7)


def test_length_limited_comparator_truncation(clib):
    """Documents UPSTREAM_FINDINGS: LeafComparator truncates a size_t
    difference to int. With weights more than ~2**22 apart, C's qsort order can
    differ from the true weight order; the port sorts correctly. This is not
    reachable from zopfli (counts <= ~1e6). We only check that every
    divergence lies in that region."""
    rng = random.Random(5)
    diverged = 0
    for _ in range(300):
        n = rng.choice([19, 32])
        f = [0] * n
        for i in range(n):
            if rng.random() < 0.8:
                f[i] = rng.randrange(1, 1 << rng.choice([10, 23, 30, 40, 54]))
        r, expect = c_llcl(clib, f, n, 15)
        bl = [0] * n
        length_limited_code_lengths(f, n, 15, bl)
        if bl != expect:
            nz = [v for v in f if v]
            assert max(nz) - min(nz) >= 1 << 22
            diverged += 1
    assert diverged > 0  # the C truncation is real


def test_calculate_bit_lengths(clib):
    rng = random.Random(42)
    for _ in range(1500):
        n, maxbits = rng.choice([(288, 15), (32, 15), (19, 7)])
        f = gen_freqs(rng, n, rng.choice(KINDS))
        expect = c_cbl(clib, f, n, maxbits)
        bl = [0] * n
        calculate_bit_lengths(f, n, maxbits, bl)
        assert bl == expect


def test_calculate_bit_lengths_error():
    f = [1] * 288
    with pytest.raises(AssertionError):
        calculate_bit_lengths(f, 288, 7, [0] * 288)


def test_lengths_to_symbols(clib):
    rng = random.Random(7)
    for i in range(3000):
        n, maxbits = rng.choice([(288, 15), (32, 15), (19, 7), (30, 9)])
        if i % 2 == 0:
            # Valid complete codes from the length-limited Huffman algorithm.
            f = gen_freqs(rng, n, rng.choice(KINDS))
            lengths = [0] * n
            length_limited_code_lengths(f, n, maxbits, lengths)
        else:
            # Arbitrary (possibly over-subscribed) lengths <= maxbits.
            p0 = rng.random()
            lengths = [0 if rng.random() < p0 else rng.randrange(1, maxbits + 1)
                       for _ in range(n)]
        expect = c_lts(clib, lengths, maxbits)
        sym = [0xABC] * n
        lengths_to_symbols(lengths, n, maxbits, sym)
        assert sym == expect


def _hex(xs):
    return [x.hex() for x in xs]


def test_calculate_entropy(clib):
    rng = random.Random(3)
    ncases = 0
    for i in range(4000):
        n = rng.choice([288, 32, 19, 1, 2, 5, 100])
        mode = i % 6
        if mode == 0:
            counts = [0] * n
        elif mode == 1:
            counts = [0] * n
            counts[rng.randrange(n)] = rng.randrange(1, 1 << 20)
        elif mode == 2:
            counts = [rng.randrange(0, 3) for _ in range(n)]
        elif mode == 3:
            counts = [rng.choice([0, rng.randrange(1, 1 << 22)]) for _ in range(n)]
        elif mode == 4:
            counts = gen_freqs(rng, n, rng.choice(KINDS[:4] + ["fib", "zopfli"])) \
                if n >= 5 else [rng.randrange(0, 5) for _ in range(n)]
        else:
            m = (1 << 32) // n - 1
            counts = [rng.randrange(0, m) for _ in range(n)]
        assert sum(counts) < 1 << 32
        expect = c_entropy(clib, counts)
        out = [None] * n
        calculate_entropy(counts, n, out)
        assert _hex(out) == _hex(expect), counts
        ncases += 1
    # n == 0: C computes log(0) = -inf and returns; must not raise here.
    calculate_entropy([], 0, [])
    assert c_entropy(clib, []) == []


def test_calculate_entropy_values_exact(clib):
    """Every count value 0..5000 alone and with one other symbol."""
    for c in range(0, 5001):
        for counts in ([c, 0, 0], [c, 1, 2], [c, c, 0, 3]):
            out = [None] * len(counts)
            calculate_entropy(counts, len(counts), out)
            assert _hex(out) == _hex(c_entropy(clib, counts))


def _random_ops(rng, k):
    ops = []
    for _ in range(k):
        kind = rng.randrange(3)
        if kind == 0:
            ops.append((0, rng.choice([0, 1, 1, 0, 2, 3, 255]), 0))
        else:
            length = rng.choice([0, 1, 2, 3, 5, 7, 8, 9, 13, 15, 16,
                                 rng.randrange(0, 33)])
            sym = rng.randrange(0, 1 << 32)
            if rng.random() < 0.5 and length:
                sym &= (1 << length) - 1
            ops.append((kind, sym, length))
    return ops


def test_bitwriter(clib):
    rng = random.Random(11)
    for i in range(3000):
        if i % 3 == 0:
            init, bp0 = b"", 0
        else:
            init = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 4)))
            bp0 = rng.randrange(8)
        ops = _random_ops(rng, rng.randrange(0, 60))
        expect = c_bitwriter(clib, init, bp0, ops)
        w = BitWriter(bytearray(init), bp0)
        for kind, sym, length in ops:
            if kind == 0:
                w.add_bit(sym)
            elif kind == 1:
                w.add_bits(sym, length)
            else:
                w.add_huffman_bits(sym, length)
        assert (bytes(w.out), w.bp) == expect, (init, bp0, ops)


def test_bitwriter_default():
    w = BitWriter()
    assert w.out == bytearray() and w.bp == 0
    w.add_bits(0, 0)
    assert w.out == bytearray()
    w.add_bit(1)
    w.add_huffman_bits(0b10, 2)
    assert (bytes(w.out), w.bp) == (b"\x03", 3)


def test_length_limited_maxbits_over_15():
    """Effective maxbits >= 16 is undefined behaviour in C (UPSTREAM_FINDINGS);
    the port refuses it. With <= 16 used symbols maxbits is clamped and fine."""
    f = list(range(1, 18))  # 17 used symbols
    with pytest.raises(ValueError):
        length_limited_code_lengths(f, 17, 16, [0] * 17)
    bl = [0] * 16
    assert length_limited_code_lengths(list(range(1, 17)), 16, 20, bl) == 0
    assert sum(2.0 ** -b for b in bl) == 1.0
