"""ctypes front-end to tools/build/deflate_harness.so (the reference C).

Everything takes/returns plain Python values. Stores are passed as the
(litlens, dists, pos) lists plus the data bytes they refer to.
"""
import ctypes
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _load_build(path, name):
    # Load build.py by path under a unique name: tools/harness/squeeze and
    # tools/harness/deflate both have a build.py, and a plain "import build"
    # returns whichever one was imported first in the pytest session.
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_build = _load_build(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "build.py"), "_zopfli_deflate_harness_build")

_lib = None


def lib():
    """Loads (building if needed) the harness; returns None if unavailable."""
    global _lib
    if _lib is None:
        path = _build.build()
        if path is None:
            return None
        _lib = ctypes.CDLL(path)
        _lib.h_calc_block_size.restype = ctypes.c_double
        _lib.h_calc_block_size_auto.restype = ctypes.c_double
        _lib.h_get_dynamic_lengths.restype = ctypes.c_double
        for name in ("h_encode_tree", "h_calculate_tree_size", "h_lz77_optimal",
                     "h_block_split", "h_block_split_lz77"):
            getattr(_lib, name).restype = ctypes.c_size_t
        _lib.h_adler32.restype = ctypes.c_uint
        _lib.h_crc.restype = ctypes.c_ulong
        _lib.h_crc_table.restype = ctypes.POINTER(ctypes.c_ulong)
    return _lib


SZ = ctypes.c_size_t
U = ctypes.c_uint


def _arr(ctype, values, n=None):
    values = list(values)
    if n is None:
        n = len(values)
    a = (ctype * max(n, 1))()
    for i, v in enumerate(values):
        a[i] = v
    return a


def _opts(options):
    return _arr(ctypes.c_int, [options.verbose, getattr(options, "verbose_more", 0),
                               options.numiterations, options.blocksplitting,
                               options.blocksplittinglast,
                               options.blocksplittingmax])


def _buf(data):
    data = bytes(data)
    return ctypes.create_string_buffer(data, max(len(data), 1))


def _store(data, litlens, dists, pos):
    return (_buf(data), _arr(ctypes.c_ushort, litlens), _arr(ctypes.c_ushort, dists),
            _arr(SZ, pos), SZ(len(litlens)))


class _Out:
    def __init__(self, prefix, bp, cap):
        self.cap = cap + len(prefix) + 64
        self.buf = ctypes.create_string_buffer(bytes(prefix), self.cap)
        self.n = SZ(len(prefix))
        self.bp = ctypes.c_ubyte(bp)

    def args(self):
        return (self.buf, SZ(self.cap), ctypes.byref(self.n), ctypes.byref(self.bp))

    def result(self):
        return bytes(self.buf.raw[:self.n.value]), self.bp.value


def symbol_fn(name, x):
    return getattr(lib(), "h_" + name)(x)


def optimize_huffman_for_rle(length, counts):
    a = _arr(SZ, counts)
    lib().h_optimize_huffman_for_rle(length, a)
    return list(a[:len(counts)])


def patch_distance_codes(d_lengths):
    a = _arr(U, d_lengths)
    lib().h_patch_distance_codes(a)
    return list(a[:len(d_lengths)])


def encode_tree(ll, d, u16, u17, u18, out=None):
    """out: None (size only) or (prefix bytes, bp). Returns size or (size, bytes, bp)."""
    lla, da = _arr(U, ll), _arr(U, d)
    if out is None:
        return lib().h_encode_tree(lla, da, u16, u17, u18, 1, None, SZ(0), None, None)
    o = _Out(out[0], out[1], 4096)
    size = lib().h_encode_tree(lla, da, u16, u17, u18, 0, *o.args())
    return (size,) + o.result()


def add_dynamic_tree(ll, d, prefix=b"", bp=0):
    o = _Out(prefix, bp, 4096)
    assert lib().h_add_dynamic_tree(_arr(U, ll), _arr(U, d), *o.args()) == 0
    return o.result()


def calculate_tree_size(ll, d):
    return lib().h_calculate_tree_size(_arr(U, ll), _arr(U, d))


def calculate_block_size(data, litlens, dists, pos, lstart, lend, btype):
    return lib().h_calc_block_size(*_store(data, litlens, dists, pos),
                                   SZ(lstart), SZ(lend), btype)


def calculate_block_size_auto_type(data, litlens, dists, pos, lstart, lend):
    return lib().h_calc_block_size_auto(*_store(data, litlens, dists, pos),
                                        SZ(lstart), SZ(lend))


def get_dynamic_lengths(data, litlens, dists, pos, lstart, lend):
    ll, d = (U * 288)(), (U * 32)()
    r = lib().h_get_dynamic_lengths(*_store(data, litlens, dists, pos),
                                    SZ(lstart), SZ(lend), ll, d)
    return r, list(ll), list(d)


def add_lz77_block(options, mode, btype, final, data, litlens, dists, pos,
                   lstart, lend, expected=0, prefix=b"", bp=0):
    o = _Out(prefix, bp, 2 * len(data) + 1024)
    r = lib().h_add_lz77_block(mode, _opts(options), btype, final,
                               *_store(data, litlens, dists, pos), SZ(lstart),
                               SZ(lend), SZ(expected), *o.args())
    assert r == 0
    return o.result()


def deflate_part(options, btype, final, data, instart, inend, prefix=b"", bp=0):
    o = _Out(prefix, bp, 2 * len(data) + 1024)
    r = lib().h_deflate_part(_opts(options), btype, final, _buf(data),
                             SZ(instart), SZ(inend), *o.args())
    assert r == 0
    return o.result()


def compress(options, fmt, data):
    cap = 2 * len(data) + 1024
    buf = ctypes.create_string_buffer(cap)
    n = SZ(0)
    assert lib().h_compress(_opts(options), fmt, _buf(data), SZ(len(data)), buf,
                            SZ(cap), ctypes.byref(n)) == 0
    return bytes(buf.raw[:n.value])


def adler32(data, size=None):
    if size is None:
        size = len(data)
    return lib().h_adler32(_buf(data), SZ(size))


def crc(data, size=None):
    if size is None:
        size = len(data)
    return lib().h_crc(_buf(data), SZ(size))


def crc_table():
    t = lib().h_crc_table()
    return [t[i] for i in range(256)]


def lz77_optimal(options, fixed, data, instart, inend, numiterations):
    """Returns (litlens, dists, pos) from ZopfliLZ77Optimal(Fixed)."""
    cap = max(inend - instart, 1)
    ll, d, p = (ctypes.c_ushort * cap)(), (ctypes.c_ushort * cap)(), (SZ * cap)()
    n = lib().h_lz77_optimal(_opts(options), fixed, _buf(data), SZ(instart),
                             SZ(inend), numiterations, ll, d, p, SZ(cap))
    assert n != ctypes.c_size_t(-1).value
    return list(ll[:n]), list(d[:n]), list(p[:n])


def block_split(options, data, instart, inend, maxblocks):
    cap = max(inend - instart, 1) + 1
    pts = (SZ * cap)()
    n = lib().h_block_split(_opts(options), _buf(data), SZ(instart), SZ(inend),
                            SZ(maxblocks), pts, SZ(cap))
    return list(pts[:n])


def block_split_lz77(options, data, litlens, dists, pos, maxblocks):
    cap = len(litlens) + 1
    pts = (SZ * cap)()
    n = lib().h_block_split_lz77(_opts(options), *_store(data, litlens, dists, pos),
                                 SZ(maxblocks), pts, SZ(cap))
    return list(pts[:n])
