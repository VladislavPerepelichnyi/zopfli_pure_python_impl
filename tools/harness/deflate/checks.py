"""Checks of zopfli_pure.deflate and the containers against the reference C.

init(use_stubs=True) replaces every dependency module by a C-backed stand-in
(stubs.py) so deflate.py can be checked in isolation; init(use_stubs=False)
uses the real package modules (tests/test_deflate.py, tests/test_containers.py).

Isolated run (from the worktree root):
    python tools/harness/deflate/checks.py [--quick]
"""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import cref  # noqa: E402
import stubs  # noqa: E402

QUICK = "--quick" in sys.argv
D = zlib_container = gzip_container = zopfli_lib = zopfli_pure = None
mods = Options = BitWriter = LZ77Store = store_lld = None
rng = random.Random(12345)
counts = {}
USE_STUBS = True


def init(use_stubs=True, seed=12345):
    """Binds the module globals to the stand-ins or to the real modules."""
    global D, zlib_container, gzip_container, zopfli_lib, zopfli_pure, mods
    global Options, BitWriter, LZ77Store, store_lld, rng, USE_STUBS
    USE_STUBS = use_stubs
    if use_stubs:
        mods = stubs.install(prefer_real="--all-stubs" not in sys.argv)
    else:
        import importlib
        mods = {n: importlib.import_module("zopfli_pure." + n) for n in stubs.NAMES}
    import importlib
    D = importlib.import_module("zopfli_pure.deflate")
    zlib_container = importlib.import_module("zopfli_pure.zlib_container")
    gzip_container = importlib.import_module("zopfli_pure.gzip_container")
    zopfli_lib = importlib.import_module("zopfli_pure.zopfli_lib")
    zopfli_pure = importlib.import_module("zopfli_pure")
    Options = mods["util"].Options
    BitWriter = mods["bitwriter"].BitWriter
    LZ77Store = mods["lz77"].LZ77Store
    store_lld = mods["lz77"].store_lit_len_dist
    rng = random.Random(seed)
    counts.clear()


def ok(name):
    counts[name] = counts.get(name, 0) + 1


def rand_counts(n):
    kind = rng.randrange(6)
    if kind == 0:
        return [rng.randrange(0, 50) for _ in range(n)]
    if kind == 1:  # sparse with zeros
        return [rng.choice([0, 0, 0, rng.randrange(1, 1000)]) for _ in range(n)]
    if kind == 2:  # runs
        v, out = 0, []
        while len(out) < n:
            v = rng.choice([0, rng.randrange(0, 20), rng.randrange(0, 5000)])
            out += [v + rng.randrange(0, 3) * (rng.random() < 0.3)] * rng.randrange(1, 20)
        return out[:n]
    if kind == 3:  # strides of near-equal counts
        out = []
        while len(out) < n:
            base = rng.randrange(0, 100)
            out += [max(0, base + rng.randrange(-4, 5)) for _ in range(rng.randrange(1, 12))]
        return out[:n]
    if kind == 4:  # trailing zeros
        k = rng.randrange(0, n + 1)
        return [rng.randrange(0, 30) for _ in range(k)] + [0] * (n - k)
    return [rng.randrange(0, 3) for _ in range(n)]


def check_optimize(iters):
    for _ in range(iters):
        for n in (288, 32, rng.randrange(0, 40)):
            c = rand_counts(n)
            if n == 0:
                c = [0]
                n = 0
            want = cref.optimize_huffman_for_rle(n, c)
            got = list(c)
            D.optimize_huffman_for_rle(n, got)
            assert got == want, (n, c, got, want)
            ok("optimize_huffman_for_rle")


def rand_lengths():
    """A valid (or at least plausible) pair of length vectors."""
    tree = mods["tree"]
    llc = rand_counts(288)
    dc = rand_counts(32)
    if rng.random() < 0.3:
        for i in range(286, 288):
            llc[i] = 0
    llc[256] = max(llc[256], 1)
    ll, d = [0] * 288, [0] * 32
    tree.calculate_bit_lengths(llc, 288, 15, ll)
    tree.calculate_bit_lengths(dc, 32, 15, d)
    if rng.random() < 0.5:
        D.patch_distance_codes_for_buggy_decoders(d)
    return ll, d


def check_trees(iters):
    for _ in range(iters):
        ll, d = rand_lengths()
        dd = list(d)
        D.patch_distance_codes_for_buggy_decoders(dd)
        assert dd == cref.patch_distance_codes(d)
        ok("patch_distance_codes")
        for flags in range(8):
            u16, u17, u18 = flags & 1, flags & 2, flags & 4
            assert D.encode_tree(ll, d, u16, u17, u18, None) == \
                cref.encode_tree(ll, d, u16, u17, u18)
            ok("encode_tree size_only")
            prefix = bytes([rng.randrange(256)]) if rng.random() < 0.5 else b""
            bp = rng.randrange(8) if prefix else 0
            if prefix:
                prefix = bytes([prefix[0] & ((1 << bp) - 1)])
            w = BitWriter(bytearray(prefix), bp)
            size = D.encode_tree(ll, d, u16, u17, u18, w)
            csize, cbytes, cbp = cref.encode_tree(ll, d, u16, u17, u18, (prefix, bp))
            assert (size, bytes(w.out), w.bp) == (csize, cbytes, cbp)
            ok("encode_tree output")
        w = BitWriter(bytearray(), 0)
        D.add_dynamic_tree(ll, d, w)
        assert (bytes(w.out), w.bp) == cref.add_dynamic_tree(ll, d)
        ok("add_dynamic_tree")
        assert D.calculate_tree_size(ll, d) == cref.calculate_tree_size(ll, d)
        ok("calculate_tree_size")


def check_checksums(iters):
    assert gzip_container.CRC32_TABLE == cref.crc_table()
    sizes = [0, 1, 2, 5549, 5550, 5551, 5552, 5553, 11100, 11101, 65535, 65536]
    for _ in range(iters):
        sizes.append(rng.randrange(0, 20000))
    for n in sizes:
        for kind in range(3):
            if kind == 0:
                data = bytes(rng.randrange(256) for _ in range(n))
            elif kind == 1:
                data = b"\xff" * n
            else:
                data = bytes(rng.choice(b"ab\x00\xfe") for _ in range(n))
            assert zlib_container.adler32(data, n) == cref.adler32(data)
            ok("adler32")
            assert gzip_container.crc(data, n) == cref.crc(data)
            ok("crc32")


def rand_store(n_items, max_dist=32768):
    """A hand-built store over random data (literals and length/dist pairs)."""
    lit, dst, pos = [], [], []
    p = 0
    for _ in range(n_items):
        if rng.random() < 0.5 or p < 1:
            lit.append(rng.randrange(256))
            dst.append(0)
            pos.append(p)
            p += 1
        else:
            l = rng.choice([3, 4, 5, rng.randrange(3, 259), 258])
            d = rng.choice([1, 2, rng.randrange(1, min(p, max_dist) + 1)])
            d = min(d, p)
            lit.append(l)
            dst.append(d)
            pos.append(p)
            p += l
    data = bytes(rng.randrange(256) for _ in range(p))
    return data, lit, dst, pos


def py_store(data, lit, dst, pos):
    st = LZ77Store(data)
    for a, b, c in zip(lit, dst, pos):
        store_lld(a, b, c, st)
    return st


def real_store(data, numiterations=3):
    o = Options(numiterations=numiterations)
    lit, dst, pos = cref.lz77_optimal(o, 0, data, 0, len(data), numiterations)
    return data, lit, dst, pos


def sample_data(n):
    kind = rng.randrange(5)
    if kind == 0:
        return bytes(rng.randrange(256) for _ in range(n))
    if kind == 1:
        words = [b"the ", b"quick ", b"brown ", b"fox ", b"jumps ", b"zopfli ", b"\n"]
        out = b""
        while len(out) < n:
            out += rng.choice(words)
        return out[:n]
    if kind == 2:
        return bytes(rng.choice(b"ACGT") for _ in range(n))
    if kind == 3:
        return bytes((i * i // 7) & 0xFF for i in range(n))
    return b"a" * n


def check_block_sizes(iters):
    for it in range(iters):
        if it % 2 == 0:
            n = rng.choice([0, 1, 2, 10, 100, 863, 864, 865, 1000, 1001, 2000,
                            rng.randrange(0, 4000)])
            data, lit, dst, pos = rand_store(n)
        else:
            data, lit, dst, pos = real_store(sample_data(rng.randrange(0, 3000)))
        st = py_store(data, lit, dst, pos)
        n = len(lit)
        ranges = [(0, n)]
        for _ in range(3):
            a = rng.randrange(0, n + 1)
            b = rng.randrange(a, n + 1)
            ranges.append((a, b))
        for a, b in ranges:
            for btype in (0, 1, 2):
                got = D.calculate_block_size(st, a, b, btype)
                want = cref.calculate_block_size(data, lit, dst, pos, a, b, btype)
                assert type(got) is float and got == want, (btype, a, b, got, want)
                ok("calculate_block_size")
            got = D.calculate_block_size_auto_type(st, a, b)
            assert got == cref.calculate_block_size_auto_type(data, lit, dst, pos, a, b)
            ok("calculate_block_size_auto_type")
            ll, d = [0] * 288, [0] * 32
            r = D.get_dynamic_lengths(st, a, b, ll, d)
            assert (r, ll, d) == cref.get_dynamic_lengths(data, lit, dst, pos, a, b)
            ok("get_dynamic_lengths")


def check_add_blocks(iters):
    o = Options()
    for it in range(iters):
        if it % 2 == 0:
            data, lit, dst, pos = rand_store(rng.choice([0, 1, 5, 50, 300, 1200]))
        else:
            data, lit, dst, pos = real_store(sample_data(rng.randrange(0, 1500)))
        st = py_store(data, lit, dst, pos)
        n = len(lit)
        a = rng.randrange(0, n + 1)
        b = rng.randrange(a, n + 1)
        if rng.random() < 0.5:
            a, b = 0, n
        bp = rng.randrange(8)
        prefix = bytes([rng.randrange(256) & ((1 << bp) - 1)]) if bp else b""
        for btype in (0, 1, 2):
            final = rng.randrange(2)
            w = BitWriter(bytearray(prefix), bp)
            D.add_lz77_block(o, btype, final, st, a, b, 0, w)
            want = cref.add_lz77_block(o, 0, btype, final, data, lit, dst, pos, a, b,
                                       0, prefix, bp)
            assert (bytes(w.out), w.bp) == want, (btype, a, b)
            ok("add_lz77_block")
        final = rng.randrange(2)
        w = BitWriter(bytearray(prefix), bp)
        D.add_lz77_block_auto_type(o, final, st, a, b, 0, w)
        want = cref.add_lz77_block(o, 1, 0, final, data, lit, dst, pos, a, b, 0,
                                   prefix, bp)
        assert (bytes(w.out), w.bp) == want
        ok("add_lz77_block_auto_type")


def check_non_compressed():
    o = Options()
    for n in (0, 1, 65534, 65535, 65536, 131070, 131071, 140000):
        data = bytes(rng.randrange(256) for _ in range(n))
        for btype in (0,):
            for bp in (0, 3):
                prefix = b"\x05" if bp else b""
                w = BitWriter(bytearray(prefix), bp)
                D.deflate_part(o, btype, 1, data, 0, n, w)
                assert (bytes(w.out), w.bp) == cref.deflate_part(o, btype, 1, data, 0,
                                                                  n, prefix, bp)
                ok("add_non_compressed_block / deflate_part btype 0")


def check_end_to_end(iters):
    import zlib
    try:
        import zopfli.zopfli as oracle
    except ImportError:
        oracle = None
    cases = [b"", b"a", b"ab", b"hello hello hello hello", b"\x00" * 1000,
             bytes(range(256)) * 4, bytes(rng.randrange(256) for _ in range(2000))]
    for _ in range(iters):
        cases.append(sample_data(rng.choice([1, 10, 100, 1000, rng.randrange(0, 6000)])))
    optsets = [dict(), dict(numiterations=2), dict(blocksplitting=0),
               dict(blocksplittingmax=2, numiterations=3),
               dict(blocksplittingmax=0, numiterations=1),
               dict(blocksplittinglast=1, numiterations=4)]
    for i, data in enumerate(cases):
        kw = optsets[i % len(optsets)]
        for gz in (0, 1):
            got = zopfli_pure.compress(data, gzip_mode=gz, **kw)
            if oracle is not None:
                want = oracle.compress(data, gzip_mode=gz, **kw)
                assert got == want, (i, kw, gz, len(data))
                ok("compress == py-zopfli")
            o = Options(**kw)
            assert got == cref.compress(o, 0 if gz else 1, data)
            ok("compress == reference ZopfliCompress")
            if gz:
                assert zlib.decompress(got, 31) == data
            else:
                assert zlib.decompress(got) == data
            ok("round trip")
        o = Options(**kw)
        got = zopfli_lib.compress_format(o, 2, data)
        assert got == cref.compress(o, 2, data)
        assert zlib.decompress(got, -15) == data
        ok("compress_format DEFLATE")
        for btype in (1,):
            w = BitWriter(bytearray(), 0)
            D.deflate_part(o, btype, 1, data, 0, len(data), w)
            assert (bytes(w.out), w.bp) == cref.deflate_part(o, btype, 1, data, 0,
                                                              len(data))
            ok("deflate_part btype 1")



def mixed_data(n, seed):
    """Concatenation of differently distributed segments (forces block splits)."""
    r = random.Random(seed)
    out = b""
    while len(out) < n:
        k = r.randrange(4)
        m = r.randrange(500, 4000)
        if k == 0:
            out += bytes(r.randrange(256) for _ in range(m))
        elif k == 1:
            out += bytes(r.choice(b"ACGT") for _ in range(m))
        elif k == 2:
            out += (b"lorem ipsum dolor sit amet %d " % r.randrange(100)) * (m // 30)
        else:
            out += bytes(r.choice(b"\x00\x01\x02\x03\xff") for _ in range(m))
    return out[:n]


def check_large(seeds, base=30000):
    import zopfli.zopfli as oracle
    for seed in seeds:
        data = mixed_data(base + 7000 * seed, seed)
        for kw in (dict(numiterations=2), dict(numiterations=1, blocksplittingmax=3),
                   dict(numiterations=1, blocksplittingmax=-1)):
            assert zopfli_pure.compress(data, **kw) == oracle.compress(data, **kw)
            ok("compress == py-zopfli (mixed, large)")


VERBOSE_SNIPPET = r"""
import sys
sys.path.insert(0, %(root)r); sys.path.insert(0, %(here)r)
data = %(data)r
if %(mine)r:
    if %(stub)r:
        import stubs; stubs.install(%(prefer_real)r)
    import zopfli_pure as z
else:
    import zopfli.zopfli as z
out = z.compress(data, verbose=1, gzip_mode=%(gz)d, numiterations=2)
sys.stderr.flush()
sys.stdout.write(out.hex())
"""


def check_verbose(big=20000):
    import subprocess
    for data in (b"", b"a", b"hello hello hello", mixed_data(big, 3)):
        for gz in (0, 1):
            res = []
            for mine in (True, False):
                code = VERBOSE_SNIPPET % dict(root=ROOT, here=HERE, data=data,
                                              mine=mine, gz=gz, stub=USE_STUBS,
                                              prefer_real="--all-stubs" not in sys.argv)
                p = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                   cwd=ROOT)
                assert p.returncode == 0, p.stderr
                res.append((p.stdout, p.stderr))
            assert res[0] == res[1], (res[0][1], res[1][1])
            ok("verbose stderr == py-zopfli")



def run_all(k=1, large_seeds=(0,), verbose_check=True):
    check_optimize(400 * k)
    check_trees(60 * k)
    check_checksums(10 * k)
    check_block_sizes(40 * k)
    check_add_blocks(40 * k)
    check_non_compressed()
    check_end_to_end(8 * k)
    check_large(large_seeds)
    if verbose_check:
        check_verbose()
    return dict(counts)


if __name__ == "__main__":
    init(use_stubs="--real" not in sys.argv)
    print("stand-ins: %s" % ", ".join(
        n for n, m in mods.items() if getattr(m, "__stub__", False)))
    result = run_all(1 if QUICK else 5, range(1 if QUICK else 3))
    for name in sorted(result):
        print("%-50s %d" % (name, result[name]))
    print("ALL OK")
