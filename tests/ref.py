"""ctypes wrapper around the reference Zopfli C library (``libzopfli_ref.so``).

The library is the unmodified google/zopfli sources plus ``tools/ref_shim.c``,
built by ``tools/build_reference.py`` into ``tools/build/``. It is built on
demand the first time this module needs it (only if missing or stale).

If no C compiler or no reference checkout is available, :func:`available`
returns False and :func:`require` skips the calling test (pytest.skip).

Everything here mirrors the C API with Python values:

* ``compress(data, **opts)``            == ``zopfli.zopfli.compress`` (py-zopfli)
* ``compress_format(fmt, data, **opts)``  ZopfliCompress (0 gzip, 1 zlib, 2 deflate)
* ``deflate(data, btype, final, **opts)`` ZopfliDeflate with an explicit btype
* ``lz77_greedy / lz77_optimal / lz77_optimal_fixed`` -> :class:`Store`
* ``store_from_arrays(data, litlens, dists, pos)`` -> :class:`Store`
* ``calculate_block_size(store, lstart, lend, btype)`` -> float
* ``calculate_block_size_auto_type(store, lstart, lend)`` -> float
* ``block_split_lz77(store, maxblocks, **opts)`` / ``block_split(...)`` -> list
* ``length_limited_code_lengths(freqs, maxbits)`` -> (ret, bitlengths)
* ``calculate_bit_lengths``, ``lengths_to_symbols``, ``calculate_entropy``,
  ``optimize_huffman_for_rle``, ``find_longest_match``, ``lz77_get_histogram``
* ``cli_compress(data, fmt, numiterations)`` runs the reference CLI binary.

Option keywords (``opts``) are those of ZopfliOptions: verbose, verbose_more,
numiterations, blocksplitting, blocksplittinglast, blocksplittingmax, with
ZopfliInitOptions defaults.
"""

import ctypes
import os
import subprocess
import sys
import tempfile
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_TOOLS = os.path.join(_REPO, "tools")

FORMAT_GZIP = 0
FORMAT_ZLIB = 1
FORMAT_DEFLATE = 2

DEFAULT_OPTIONS = dict(verbose=0, verbose_more=0, numiterations=15,
                       blocksplitting=1, blocksplittinglast=0,
                       blocksplittingmax=15)

_lock = threading.Lock()
_lib = None
_bin = None
_error = None

c_size_t = ctypes.c_size_t
c_int = ctypes.c_int
c_uint = ctypes.c_uint
c_ushort = ctypes.c_ushort
c_double = ctypes.c_double
c_void_p = ctypes.c_void_p
P = ctypes.POINTER

_OPTS = [c_int] * 6


def _setup(lib):
    def sig(name, restype, argtypes):
        f = getattr(lib, name)
        f.restype = restype
        f.argtypes = argtypes

    sig("ref_free", None, [c_void_p])
    sig("ref_version", c_int, [])
    sig("ref_compress", None, _OPTS + [c_int, ctypes.c_char_p, c_size_t,
                                       P(c_void_p), P(c_size_t)])
    sig("ref_deflate", None, _OPTS + [c_int, c_int, ctypes.c_char_p, c_size_t,
                                      P(c_void_p), P(c_size_t)])
    sig("ref_deflate_part", None, _OPTS + [c_int, c_int, ctypes.c_char_p,
                                           c_size_t, c_size_t,
                                           P(c_void_p), P(c_size_t)])
    sig("ref_store_free", None, [c_void_p])
    sig("ref_store_size", c_size_t, [c_void_p])
    sig("ref_store_export", None, [c_void_p, P(c_ushort), P(c_ushort),
                                   P(c_size_t)])
    sig("ref_store_export_symbols", None, [c_void_p, P(c_ushort), P(c_ushort),
                                           P(c_size_t), P(c_size_t)])
    sig("ref_store_from_arrays", c_void_p, [ctypes.c_char_p, P(c_ushort),
                                            P(c_ushort), P(c_size_t), c_size_t])
    sig("ref_lz77_get_histogram", None, [c_void_p, c_size_t, c_size_t,
                                         P(c_size_t), P(c_size_t)])
    sig("ref_lz77_get_byte_range", c_size_t, [c_void_p, c_size_t, c_size_t])
    sig("ref_lz77_greedy", c_void_p, _OPTS + [c_int, ctypes.c_char_p,
                                              c_size_t, c_size_t])
    sig("ref_lz77_optimal", c_void_p, _OPTS + [c_int, ctypes.c_char_p,
                                               c_size_t, c_size_t])
    sig("ref_lz77_optimal_fixed", c_void_p, _OPTS + [ctypes.c_char_p,
                                                     c_size_t, c_size_t])
    sig("ref_find_longest_match", c_uint, [ctypes.c_char_p, c_size_t, c_size_t,
                                           c_size_t, c_size_t, P(c_ushort),
                                           P(c_ushort)])
    sig("ref_calculate_block_size", c_double, [c_void_p, c_size_t, c_size_t,
                                               c_int])
    sig("ref_calculate_block_size_auto_type", c_double, [c_void_p, c_size_t,
                                                         c_size_t])
    sig("ref_optimize_huffman_for_rle", None, [c_int, P(c_size_t)])
    sig("ref_block_split_lz77", None, _OPTS + [c_void_p, c_size_t,
                                               P(c_void_p), P(c_size_t)])
    sig("ref_block_split", None, _OPTS + [ctypes.c_char_p, c_size_t, c_size_t,
                                          c_size_t, P(c_void_p), P(c_size_t)])
    sig("ref_block_split_simple", None, [ctypes.c_char_p, c_size_t, c_size_t,
                                         c_size_t, P(c_void_p), P(c_size_t)])
    sig("ref_length_limited_code_lengths", c_int, [P(c_size_t), c_int, c_int,
                                                   P(c_uint)])
    sig("ref_calculate_bit_lengths", None, [P(c_size_t), c_size_t, c_int,
                                            P(c_uint)])
    sig("ref_lengths_to_symbols", None, [P(c_uint), c_size_t, c_uint,
                                         P(c_uint)])
    sig("ref_calculate_entropy", None, [P(c_size_t), c_size_t, P(c_double)])


def _load():
    global _lib, _bin, _error
    with _lock:
        if _lib is not None or _error is not None:
            return
        try:
            sys.path.insert(0, _TOOLS)
            try:
                import build_reference
            finally:
                sys.path.remove(_TOOLS)
            libpath, binpath = build_reference.build()
            lib = ctypes.CDLL(libpath)
            _setup(lib)
            _lib, _bin = lib, binpath
        except Exception as e:  # BuildError, OSError, ...
            _error = "%s: %s" % (type(e).__name__, e)


def available():
    """True if the reference library could be built and loaded."""
    _load()
    return _lib is not None


def unavailable_reason():
    _load()
    return _error


def require():
    """Skip the current pytest test if the reference library is unavailable."""
    if not available():
        import pytest
        pytest.skip("reference C library unavailable: %s" % _error)
    return _lib


def lib():
    if not available():
        raise RuntimeError("reference C library unavailable: %s" % _error)
    return _lib


def binary():
    lib()
    return _bin


# ------------------------------------------------------------------ helpers

def _opts(opts):
    unknown = set(opts) - set(DEFAULT_OPTIONS)
    if unknown:
        raise TypeError("unknown option(s): %s" % ", ".join(sorted(unknown)))
    o = dict(DEFAULT_OPTIONS)
    o.update(opts)
    return [int(o[k]) for k in ("verbose", "verbose_more", "numiterations",
                                "blocksplitting", "blocksplittinglast",
                                "blocksplittingmax")]


def _bytes(data):
    if isinstance(data, str):
        return data.encode("utf-8")
    return bytes(data)


def _take_bytes(out, outsize):
    try:
        return ctypes.string_at(out.value, outsize.value) if outsize.value else b""
    finally:
        if out.value:
            _lib.ref_free(out.value)


def _take_points(points, n):
    try:
        if not n.value:
            return []
        arr = ctypes.cast(points.value, P(c_size_t))
        return [arr[i] for i in range(n.value)]
    finally:
        if points.value:
            _lib.ref_free(points.value)


def _size_t_array(values):
    return (c_size_t * max(1, len(values)))(*values)


# ----------------------------------------------------------------- compress

def compress_format(fmt, data, **opts):
    """ZopfliCompress(options, fmt, data). fmt: 0 gzip, 1 zlib, 2 deflate."""
    L = lib()
    data = _bytes(data)
    out, outsize = c_void_p(), c_size_t()
    L.ref_compress(*_opts(opts), fmt, data, len(data), ctypes.byref(out),
                   ctypes.byref(outsize))
    return _take_bytes(out, outsize)


def compress(data, verbose=0, numiterations=15, blocksplitting=1,
             blocksplittinglast=0, blocksplittingmax=15, gzip_mode=0):
    """Same signature/semantics as py-zopfli's zopfli.zopfli.compress."""
    fmt = FORMAT_GZIP if gzip_mode else FORMAT_ZLIB
    return compress_format(fmt, data, verbose=verbose,
                           numiterations=numiterations,
                           blocksplitting=blocksplitting,
                           blocksplittinglast=blocksplittinglast,
                           blocksplittingmax=blocksplittingmax)


def deflate(data, btype=2, final=1, **opts):
    """ZopfliDeflate(options, btype, final, data) starting at bp = 0."""
    L = lib()
    data = _bytes(data)
    out, outsize = c_void_p(), c_size_t()
    L.ref_deflate(*_opts(opts), btype, final, data, len(data),
                  ctypes.byref(out), ctypes.byref(outsize))
    return _take_bytes(out, outsize)


def deflate_part(data, instart, inend, btype=2, final=1, **opts):
    """ZopfliDeflatePart(options, btype, final, data, instart, inend), bp = 0."""
    L = lib()
    data = _bytes(data)
    out, outsize = c_void_p(), c_size_t()
    L.ref_deflate_part(*_opts(opts), btype, final, data, instart, inend,
                       ctypes.byref(out), ctypes.byref(outsize))
    return _take_bytes(out, outsize)


def cli_compress(data, fmt=FORMAT_GZIP, numiterations=15):
    """Run the reference ``zopfli`` CLI binary on data, return its stdout."""
    binp = binary()
    flag = {FORMAT_GZIP: "--gzip", FORMAT_ZLIB: "--zlib",
            FORMAT_DEFLATE: "--deflate"}[fmt]
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "input")
        with open(path, "wb") as f:
            f.write(_bytes(data))
        r = subprocess.run([binp, "-c", flag, "--i%d" % numiterations, path],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           check=True)
    return r.stdout


# ------------------------------------------------------------------- stores

class Store(object):
    """A reference ZopfliLZ77Store, owned by C; arrays copied out lazily."""

    def __init__(self, handle, data_buf):
        self._h = handle
        self._buf = data_buf  # keeps store->data alive
        self._arrays = None

    def __del__(self):
        h, self._h = getattr(self, "_h", None), None
        if h and _lib is not None:
            _lib.ref_store_free(h)

    @property
    def handle(self):
        return self._h

    @property
    def size(self):
        return _lib.ref_store_size(self._h)

    def __len__(self):
        return self.size

    def _export(self):
        if self._arrays is None:
            n = self.size
            ll = (c_ushort * max(1, n))()
            d = (c_ushort * max(1, n))()
            p = (c_size_t * max(1, n))()
            _lib.ref_store_export(self._h, ll, d, p)
            self._arrays = (list(ll[:n]), list(d[:n]), list(p[:n]))
        return self._arrays

    @property
    def litlens(self):
        return self._export()[0]

    @property
    def dists(self):
        return self._export()[1]

    @property
    def pos(self):
        return self._export()[2]

    def symbols(self):
        """(ll_symbol, d_symbol, ll_counts, d_counts) as lists."""
        n = self.size
        llsize = 288 * ((n + 287) // 288)
        dsize = 32 * ((n + 31) // 32)
        ls = (c_ushort * max(1, n))()
        ds = (c_ushort * max(1, n))()
        lc = (c_size_t * max(1, llsize))()
        dc = (c_size_t * max(1, dsize))()
        _lib.ref_store_export_symbols(self._h, ls, ds, lc, dc)
        return list(ls[:n]), list(ds[:n]), list(lc[:llsize]), list(dc[:dsize])

    def as_tuples(self):
        return list(zip(self.litlens, self.dists, self.pos))


def _buf(data):
    data = _bytes(data)
    return data, ctypes.create_string_buffer(data, len(data) + 1)


def lz77_greedy(data, instart=0, inend=None, add_lmc=0, **opts):
    """ZopfliLZ77Greedy with a fresh BlockState(add_lmc) and hash."""
    L = lib()
    data, buf = _buf(data)
    if inend is None:
        inend = len(data)
    h = L.ref_lz77_greedy(*_opts(opts), add_lmc, buf, instart, inend)
    return Store(h, buf)


def lz77_optimal(data, instart=0, inend=None, numiterations=15, **opts):
    """ZopfliLZ77Optimal (BlockState with lmc), as ZopfliDeflatePart calls it."""
    L = lib()
    data, buf = _buf(data)
    if inend is None:
        inend = len(data)
    o = dict(opts)
    o.setdefault("numiterations", numiterations)
    h = L.ref_lz77_optimal(*_opts(o), numiterations, buf, instart, inend)
    return Store(h, buf)


def lz77_optimal_fixed(data, instart=0, inend=None, **opts):
    """ZopfliLZ77OptimalFixed (BlockState with lmc)."""
    L = lib()
    data, buf = _buf(data)
    if inend is None:
        inend = len(data)
    h = L.ref_lz77_optimal_fixed(*_opts(opts), buf, instart, inend)
    return Store(h, buf)


def store_from_arrays(data, litlens, dists, pos):
    """Build a C store by ZopfliStoreLitLenDist over the given arrays."""
    L = lib()
    data, buf = _buf(data)
    n = len(litlens)
    assert len(dists) == n and len(pos) == n
    ll = (c_ushort * max(1, n))(*litlens)
    d = (c_ushort * max(1, n))(*dists)
    p = (c_size_t * max(1, n))(*pos)
    h = L.ref_store_from_arrays(buf, ll, d, p, n)
    return Store(h, buf)


def lz77_get_histogram(store, lstart, lend):
    ll = (c_size_t * 288)()
    d = (c_size_t * 32)()
    lib().ref_lz77_get_histogram(store.handle, lstart, lend, ll, d)
    return list(ll), list(d)


def lz77_get_byte_range(store, lstart, lend):
    return lib().ref_lz77_get_byte_range(store.handle, lstart, lend)


def find_longest_match(data, pos, instart=0, inend=None, limit=258,
                       want_sublen=True):
    """ZopfliFindLongestMatch at pos (fresh hash updated up to pos, no lmc).

    Returns (distance, length, sublen) where sublen is a 259-entry list (only
    entries 3..length are meaningful) or None.
    """
    L = lib()
    data, buf = _buf(data)
    if inend is None:
        inend = len(data)
    sub = (c_ushort * 259)() if want_sublen else None
    dist = c_ushort()
    length = L.ref_find_longest_match(buf, instart, inend, pos, limit, sub,
                                      ctypes.byref(dist))
    return dist.value, length, (list(sub) if want_sublen else None)


# ---------------------------------------------------------------- deflate.c

def calculate_block_size(store, lstart, lend, btype):
    return lib().ref_calculate_block_size(store.handle, lstart, lend, btype)


def calculate_block_size_auto_type(store, lstart, lend):
    return lib().ref_calculate_block_size_auto_type(store.handle, lstart, lend)


def optimize_huffman_for_rle(counts):
    """OptimizeHuffmanForRle(len(counts), counts); returns the new counts."""
    arr = _size_t_array(counts)
    lib().ref_optimize_huffman_for_rle(len(counts), arr)
    return list(arr[:len(counts)])


# ---------------------------------------------------------- blocksplitter.c

def block_split_lz77(store, maxblocks, **opts):
    points, n = c_void_p(), c_size_t()
    lib().ref_block_split_lz77(*_opts(opts), store.handle, maxblocks,
                               ctypes.byref(points), ctypes.byref(n))
    return _take_points(points, n)


def block_split(data, instart=0, inend=None, maxblocks=15, **opts):
    L = lib()
    data, buf = _buf(data)
    if inend is None:
        inend = len(data)
    points, n = c_void_p(), c_size_t()
    L.ref_block_split(*_opts(opts), buf, instart, inend, maxblocks,
                      ctypes.byref(points), ctypes.byref(n))
    return _take_points(points, n)


def block_split_simple(data, instart, inend, blocksize):
    L = lib()
    data, buf = _buf(data)
    points, n = c_void_p(), c_size_t()
    L.ref_block_split_simple(buf, instart, inend, blocksize,
                             ctypes.byref(points), ctypes.byref(n))
    return _take_points(points, n)


# --------------------------------------------------------- katajainen / tree

def length_limited_code_lengths(frequencies, maxbits):
    """Returns (return_code, bitlengths list)."""
    n = len(frequencies)
    f = _size_t_array(frequencies)
    out = (c_uint * max(1, n))()
    r = lib().ref_length_limited_code_lengths(f, n, maxbits, out)
    return r, list(out[:n])


def calculate_bit_lengths(count, maxbits):
    n = len(count)
    c = _size_t_array(count)
    out = (c_uint * max(1, n))()
    lib().ref_calculate_bit_lengths(c, n, maxbits, out)
    return list(out[:n])


def lengths_to_symbols(lengths, maxbits):
    n = len(lengths)
    ln = (c_uint * max(1, n))(*lengths)
    out = (c_uint * max(1, n))()
    lib().ref_lengths_to_symbols(ln, n, maxbits, out)
    return list(out[:n])


def calculate_entropy(count):
    n = len(count)
    c = _size_t_array(count)
    out = (c_double * max(1, n))()
    lib().ref_calculate_entropy(c, n, out)
    return list(out[:n])
