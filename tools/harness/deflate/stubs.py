"""Stand-ins for the zopfli_pure modules deflate.py depends on.

install() registers fake zopfli_pure.{util,symbols,lz77,tree,bitwriter,squeeze,
blocksplitter} modules in sys.modules. They are backed by the reference C
(through cref.py) or by tiny Python versions, so deflate.py and the containers
can be checked in isolation before the real modules land. Never used by the
package itself.
"""
import ctypes
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cref  # noqa: E402

NAMES = ("util", "symbols", "lz77", "tree", "bitwriter", "squeeze", "blocksplitter")


def _module(name):
    m = types.ModuleType("zopfli_pure." + name)
    m.__stub__ = True
    return m


def _util():
    m = _module("util")
    m.ZOPFLI_MAX_MATCH = 258
    m.ZOPFLI_MIN_MATCH = 3
    m.ZOPFLI_NUM_LL = 288
    m.ZOPFLI_NUM_D = 32
    m.ZOPFLI_WINDOW_SIZE = 32768
    m.ZOPFLI_WINDOW_MASK = 32767
    m.ZOPFLI_MASTER_BLOCK_SIZE = 1000000
    m.ZOPFLI_LARGE_FLOAT = 1e30
    m.ZOPFLI_CACHE_LENGTH = 8
    m.ZOPFLI_MAX_CHAIN_HITS = 8192
    m.ZOPFLI_FORMAT_GZIP = 0
    m.ZOPFLI_FORMAT_ZLIB = 1
    m.ZOPFLI_FORMAT_DEFLATE = 2

    class Options:
        def __init__(self, verbose=0, verbose_more=0, numiterations=15,
                     blocksplitting=1, blocksplittinglast=0, blocksplittingmax=15):
            self.verbose = verbose
            self.verbose_more = verbose_more
            self.numiterations = numiterations
            self.blocksplitting = blocksplitting
            self.blocksplittinglast = blocksplittinglast
            self.blocksplittingmax = blocksplittingmax
    m.Options = Options
    return m


def _symbols():
    m = _module("symbols")
    f = cref.symbol_fn
    m.LENGTH_SYMBOL = [f("get_length_symbol", i) for i in range(259)]
    m.LENGTH_EXTRA_BITS = [f("get_length_extra_bits", i) for i in range(259)]
    m.LENGTH_EXTRA_BITS_VALUE = [f("get_length_extra_bits_value", i) for i in range(259)]
    m.LENGTH_SYMBOL_EXTRA_BITS = [f("get_length_symbol_extra_bits", s)
                                  for s in range(257, 286)]
    m.DIST_SYMBOL_EXTRA_BITS = [f("get_dist_symbol_extra_bits", s) for s in range(30)]
    ds = [0] + [f("get_dist_symbol", d) for d in range(1, 32769)]
    deb = [0] + [f("get_dist_extra_bits", d) for d in range(1, 32769)]
    debv = [0] + [f("get_dist_extra_bits_value", d) for d in range(1, 32769)]
    m.get_dist_symbol = ds.__getitem__
    m.get_dist_extra_bits = deb.__getitem__
    m.get_dist_extra_bits_value = debv.__getitem__
    m.get_length_symbol = m.LENGTH_SYMBOL.__getitem__
    m.get_length_extra_bits = m.LENGTH_EXTRA_BITS.__getitem__
    m.get_length_extra_bits_value = m.LENGTH_EXTRA_BITS_VALUE.__getitem__
    m.get_length_symbol_extra_bits = lambda s: m.LENGTH_SYMBOL_EXTRA_BITS[s - 257]
    m.get_dist_symbol_extra_bits = m.DIST_SYMBOL_EXTRA_BITS.__getitem__
    return m


def _lz77(symbols):
    m = _module("lz77")

    class LZ77Store:
        def __init__(self, data):
            self.data = data
            self.litlens, self.dists, self.pos = [], [], []
            self.ll_symbol, self.d_symbol = [], []
            self.ll_counts, self.d_counts = [], []
            self.size = 0

    def store_lit_len_dist(length, dist, pos, store):
        store.litlens.append(length)
        store.dists.append(dist)
        store.pos.append(pos)
        if dist == 0:
            store.ll_symbol.append(length)
            store.d_symbol.append(0)
        else:
            store.ll_symbol.append(symbols.LENGTH_SYMBOL[length])
            store.d_symbol.append(symbols.get_dist_symbol(dist))
        store.size = len(store.litlens)

    def append_lz77_store(store, target):
        for i in range(store.size):
            store_lit_len_dist(store.litlens[i], store.dists[i], store.pos[i], target)

    def lz77_get_byte_range(lz77, lstart, lend):
        if lstart == lend:
            return 0
        l = lend - 1
        return lz77.pos[l] + (1 if lz77.dists[l] == 0 else lz77.litlens[l]) - lz77.pos[lstart]

    def lz77_get_histogram(lz77, lstart, lend, ll_counts, d_counts):
        for i in range(288):
            ll_counts[i] = 0
        for i in range(32):
            d_counts[i] = 0
        for i in range(lstart, lend):
            ll_counts[lz77.ll_symbol[i]] += 1
            if lz77.dists[i] != 0:
                d_counts[lz77.d_symbol[i]] += 1

    class BlockState:
        def __init__(self, options, blockstart, blockend, add_lmc):
            self.options = options
            self.blockstart = blockstart
            self.blockend = blockend
            self.lmc = object() if add_lmc else None

    m.LZ77Store = LZ77Store
    m.store_lit_len_dist = store_lit_len_dist
    m.append_lz77_store = append_lz77_store
    m.lz77_get_byte_range = lz77_get_byte_range
    m.lz77_get_histogram = lz77_get_histogram
    m.BlockState = BlockState
    return m


def _tree():
    m = _module("tree")
    lib = cref.lib()

    def calculate_bit_lengths(count, n, maxbits, bitlengths):
        c = (ctypes.c_size_t * n)(*count[:n])
        b = (ctypes.c_uint * n)()
        lib.ZopfliCalculateBitLengths(c, ctypes.c_size_t(n), maxbits, b)
        bitlengths[:n] = list(b)

    def lengths_to_symbols(lengths, n, maxbits, symbols):
        l = (ctypes.c_uint * n)(*lengths[:n])
        s = (ctypes.c_uint * n)()
        lib.ZopfliLengthsToSymbols(l, ctypes.c_size_t(n), ctypes.c_uint(maxbits), s)
        symbols[:n] = list(s)

    m.calculate_bit_lengths = calculate_bit_lengths
    m.lengths_to_symbols = lengths_to_symbols
    return m


def _bitwriter():
    m = _module("bitwriter")

    class BitWriter:
        def __init__(self, out=None, bp=0):
            self.out = bytearray() if out is None else out
            self.bp = bp

        def add_bit(self, bit):
            if self.bp == 0:
                self.out.append(0)
            self.out[-1] |= (bit << self.bp) & 0xFF
            self.bp = (self.bp + 1) & 7

        def add_bits(self, symbol, length):
            for i in range(length):
                self.add_bit((symbol >> i) & 1)

        def add_huffman_bits(self, symbol, length):
            for i in range(length):
                self.add_bit((symbol >> (length - i - 1)) & 1)

    m.BitWriter = BitWriter
    return m


def _fill(lz77mod, store, triple):
    for l, d, p in zip(*triple):
        lz77mod.store_lit_len_dist(l, d, p, store)


def _squeeze(lz77mod):
    m = _module("squeeze")

    def lz77_optimal(s, in_, instart, inend, numiterations, store):
        _fill(lz77mod, store, cref.lz77_optimal(s.options, 0, in_, instart, inend,
                                                numiterations))

    def lz77_optimal_fixed(s, in_, instart, inend, store):
        _fill(lz77mod, store, cref.lz77_optimal(s.options, 1, in_, instart, inend, 0))

    m.lz77_optimal = lz77_optimal
    m.lz77_optimal_fixed = lz77_optimal_fixed
    return m


def _blocksplitter():
    m = _module("blocksplitter")

    def block_split(options, in_, instart, inend, maxblocks):
        return cref.block_split(options, in_, instart, inend, maxblocks)

    def block_split_lz77(options, lz77, maxblocks):
        return cref.block_split_lz77(options, lz77.data, lz77.litlens, lz77.dists,
                                     lz77.pos, maxblocks)

    m.block_split = block_split
    m.block_split_lz77 = block_split_lz77
    return m


def install():
    """Installs all stand-ins (and drops already-imported package modules)."""
    if cref.lib() is None:
        raise RuntimeError("C harness unavailable")
    import zopfli_pure
    for k in list(sys.modules):
        if k.startswith("zopfli_pure."):
            del sys.modules[k]
    mods = {}
    mods["util"] = _util()
    mods["symbols"] = _symbols()
    mods["lz77"] = _lz77(mods["symbols"])
    mods["tree"] = _tree()
    mods["bitwriter"] = _bitwriter()
    mods["squeeze"] = _squeeze(mods["lz77"])
    mods["blocksplitter"] = _blocksplitter()
    for name, mod in mods.items():
        sys.modules["zopfli_pure." + name] = mod
        setattr(zopfli_pure, name, mod)
    return mods
