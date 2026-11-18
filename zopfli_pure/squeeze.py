"""Port of squeeze.c: the iterative shortest-path ("squeeze") LZ77 optimizer.

The forward pass (``get_best_lengths``) keeps path costs in a C ``float`` array;
here that is an ``array.array('f')`` so that every store rounds to float32 while
all other arithmetic is done in double (Python ``float``), exactly as in C.
See docs/notes/squeeze.md.
"""

import sys
from array import array

from . import deflate
from . import symbols
from . import tree
from .hash import Hash, reset_hash, update_hash, warmup_hash
from .lz77 import (LZ77Store, copy_lz77_store, find_longest_match,
                   lz77_greedy, store_lit_len_dist)
from .util import (ZOPFLI_LARGE_FLOAT, ZOPFLI_MAX_MATCH, ZOPFLI_MIN_MATCH,
                   ZOPFLI_NUM_D, ZOPFLI_NUM_LL, ZOPFLI_WINDOW_MASK,
                   ZOPFLI_WINDOW_SIZE)

# ---------------------------------------------------------------------------
# Lookup tables (built once from the symbols module; same values as the C
# inline functions, just indexed instead of computed).
# ---------------------------------------------------------------------------

_get_length_symbol = symbols.get_length_symbol
_get_length_extra_bits = symbols.get_length_extra_bits
_get_dist_symbol = symbols.get_dist_symbol
_get_dist_extra_bits = symbols.get_dist_extra_bits

# Index: length 0..258 (entries 0..2 are never used by the cost models).
_LEN_SYMBOL = [0, 0, 0] + [_get_length_symbol(k) for k in range(3, 259)]
_LEN_EXTRA = [0, 0, 0] + [_get_length_extra_bits(k) for k in range(3, 259)]
# Index: distance 0..32768 (entry 0 is never used by the cost models).
_DIST_SYMBOL = [0] + [_get_dist_symbol(d) for d in range(1, 32769)]
_DIST_EXTRA = [0] + [_get_dist_extra_bits(d) for d in range(1, 32769)]
# GetCostFixed, literal part: 8 bits for 0..143, 9 bits for 144..255.
_FIXED_LIT = [8 if c <= 143 else 9 for c in range(256)]
# GetCostFixed, length part without dbits: (7 or 8) + 5 + lbits (all ints, so
# the C evaluation order ((cost + dbits) + lbits) gives the same exact value).
_FIXED_LEN = [0, 0, 0] + [(7 if _LEN_SYMBOL[k] <= 279 else 8) + 5 + _LEN_EXTRA[k]
                          for k in range(3, 259)]


class SymbolStats(object):
    """Port of struct SymbolStats (squeeze.c), initialised as by InitStats."""

    __slots__ = ("litlens", "dists", "ll_symbols", "d_symbols")

    def __init__(self):
        self.litlens = [0] * ZOPFLI_NUM_LL
        self.dists = [0] * ZOPFLI_NUM_D
        self.ll_symbols = [0.0] * ZOPFLI_NUM_LL
        self.d_symbols = [0.0] * ZOPFLI_NUM_D


def init_stats(stats):
    """Port of InitStats (squeeze.c)."""
    stats.litlens[:] = [0] * ZOPFLI_NUM_LL
    stats.dists[:] = [0] * ZOPFLI_NUM_D
    stats.ll_symbols[:] = [0.0] * ZOPFLI_NUM_LL
    stats.d_symbols[:] = [0.0] * ZOPFLI_NUM_D


def copy_stats(source, dest):
    """Port of CopyStats (squeeze.c)."""
    dest.litlens[:] = source.litlens
    dest.dists[:] = source.dists
    dest.ll_symbols[:] = source.ll_symbols
    dest.d_symbols[:] = source.d_symbols


def add_weighed_stat_freqs(stats1, w1, stats2, w2, result):
    """Port of AddWeighedStatFreqs (squeeze.c).

    (size_t)(double) truncates toward zero; the values are non-negative, so
    int() is the same conversion.
    """
    l1 = stats1.litlens
    l2 = stats2.litlens
    rl = result.litlens
    for i in range(ZOPFLI_NUM_LL):
        rl[i] = int(l1[i] * w1 + l2[i] * w2)
    d1 = stats1.dists
    d2 = stats2.dists
    rd = result.dists
    for i in range(ZOPFLI_NUM_D):
        rd[i] = int(d1[i] * w1 + d2[i] * w2)
    rl[256] = 1  # End symbol.


class RanState(object):
    """Port of struct RanState (squeeze.c); __init__ is InitRanState."""

    __slots__ = ("m_w", "m_z")

    def __init__(self):
        self.m_w = 1
        self.m_z = 2


def init_ran_state(state):
    """Port of InitRanState (squeeze.c)."""
    state.m_w = 1
    state.m_z = 2


def ran(state):
    """Port of Ran (squeeze.c): Marsaglia multiply-with-carry, 32-bit result.

    m_z and m_w cannot exceed 32 bits (36969 * 65535 + 65535 < 2**32), so only
    the final ``(m_z << 16) + m_w`` needs the unsigned int wrap.
    """
    m_z = 36969 * (state.m_z & 65535) + (state.m_z >> 16)
    m_w = 18000 * (state.m_w & 65535) + (state.m_w >> 16)
    state.m_z = m_z
    state.m_w = m_w
    return ((m_z << 16) + m_w) & 0xFFFFFFFF


def randomize_freqs(state, freqs, n):
    """Port of RandomizeFreqs (squeeze.c)."""
    for i in range(n):
        if (ran(state) >> 4) % 3 == 0:
            freqs[i] = freqs[ran(state) % n]


def randomize_stat_freqs(state, stats):
    """Port of RandomizeStatFreqs (squeeze.c)."""
    randomize_freqs(state, stats.litlens, ZOPFLI_NUM_LL)
    randomize_freqs(state, stats.dists, ZOPFLI_NUM_D)
    stats.litlens[256] = 1  # End symbol.


def clear_stat_freqs(stats):
    """Port of ClearStatFreqs (squeeze.c)."""
    stats.litlens[:] = [0] * ZOPFLI_NUM_LL
    stats.dists[:] = [0] * ZOPFLI_NUM_D


def get_cost_fixed(litlen, dist, unused):
    """Port of GetCostFixed (squeeze.c). Returns a float, like the C double."""
    if dist == 0:
        if litlen <= 143:
            return 8.0
        else:
            return 9.0
    else:
        dbits = _get_dist_extra_bits(dist)
        lbits = _get_length_extra_bits(litlen)
        lsym = _get_length_symbol(litlen)
        cost = 0
        if lsym <= 279:
            cost += 7
        else:
            cost += 8
        cost += 5  # Every dist symbol has length 5.
        return float(cost + dbits + lbits)


def get_cost_stat(litlen, dist, context):
    """Port of GetCostStat (squeeze.c)."""
    stats = context
    if dist == 0:
        return stats.ll_symbols[litlen]
    else:
        lsym = _get_length_symbol(litlen)
        lbits = _get_length_extra_bits(litlen)
        dsym = _get_dist_symbol(dist)
        dbits = _get_dist_extra_bits(dist)
        return lbits + dbits + stats.ll_symbols[lsym] + stats.d_symbols[dsym]


# Port of the static dsymbols table in GetCostModelMinCost.
_DSYMBOLS = (
    1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513,
    769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577
)


def get_cost_model_min_cost(costmodel, costcontext):
    """Port of GetCostModelMinCost (squeeze.c)."""
    bestlength = 0
    bestdist = 0

    mincost = ZOPFLI_LARGE_FLOAT
    for i in range(3, 259):
        c = costmodel(i, 1, costcontext)
        if c < mincost:
            bestlength = i
            mincost = c

    mincost = ZOPFLI_LARGE_FLOAT
    for i in range(30):
        c = costmodel(3, _DSYMBOLS[i], costcontext)
        if c < mincost:
            bestdist = _DSYMBOLS[i]
            mincost = c

    return costmodel(bestlength, bestdist, costcontext)


def get_best_lengths(s, in_, instart, inend, costmodel, costcontext,
                     length_array, h, costs):
    """Port of GetBestLengths (squeeze.c).

    costs: array.array('f') of at least inend - instart + 1 entries (C float*).
    length_array: list of at least inend - instart + 1 ints (C unsigned short*).
    Returns the cost (a float) to reach the end according to the cost model.

    The forward pass is specialised for the two cost models of squeeze.c
    (GetCostStat, GetCostFixed); any other cost model function goes through a
    generic path that calls it like the C function pointer. All three paths
    perform the same double operations in the same order as the C code.
    """
    blocksize = inend - instart
    windowstart = instart - ZOPFLI_WINDOW_SIZE if instart > ZOPFLI_WINDOW_SIZE else 0
    mincost = get_cost_model_min_cost(costmodel, costcontext)

    if instart == inend:
        return 0.0

    reset_hash(ZOPFLI_WINDOW_SIZE, h)
    warmup_hash(in_, windowstart, inend, h)
    for i in range(windowstart, instart):
        update_hash(in_, i, inend, h)

    # for (i = 1; i < blocksize + 1; i++) costs[i] = ZOPFLI_LARGE_FLOAT;
    costs[1:blocksize + 1] = array('f', [ZOPFLI_LARGE_FLOAT]) * blocksize
    costs[0] = 0  # Because it's the start.
    length_array[0] = 0

    if costmodel is get_cost_stat:
        _best_lengths_stat(s, in_, instart, inend, costcontext, mincost,
                           length_array, h, costs)
    elif costmodel is get_cost_fixed:
        _best_lengths_fixed(s, in_, instart, inend, mincost,
                            length_array, h, costs)
    else:
        _best_lengths_generic(s, in_, instart, inend, costmodel, costcontext,
                              mincost, length_array, h, costs)

    result = costs[blocksize]
    assert result >= 0
    return result


def _best_lengths_generic(s, in_, instart, inend, costmodel, costcontext,
                          mincost, length_array, h, costs):
    """Main loop of GetBestLengths (squeeze.c), calling costmodel per symbol."""
    MAX_MATCH = ZOPFLI_MAX_MATCH
    MASK = ZOPFLI_WINDOW_MASK
    sublen = [0] * 259
    same = h.same
    i = instart
    while i < inend:
        j = i - instart  # Index in the costs array and length_array.
        update_hash(in_, i, inend, h)

        # ZOPFLI_SHORTCUT_LONG_REPETITIONS
        if (same[i & MASK] > MAX_MATCH * 2
                and i > instart + MAX_MATCH + 1
                and i + MAX_MATCH * 2 + 1 < inend
                and same[(i - MAX_MATCH) & MASK] > MAX_MATCH):
            symbolcost = costmodel(MAX_MATCH, 1, costcontext)
            for _k in range(MAX_MATCH):
                costs[j + MAX_MATCH] = costs[j] + symbolcost
                length_array[j + MAX_MATCH] = MAX_MATCH
                i += 1
                j += 1
                update_hash(in_, i, inend, h)

        dist, leng = find_longest_match(s, h, in_, i, inend, MAX_MATCH, sublen)

        # Literal. (The C guard "i + 1 <= inend" is always true here.)
        newcost = costmodel(in_[i], 0, costcontext) + costs[j]
        if newcost < costs[j + 1]:
            costs[j + 1] = newcost
            length_array[j + 1] = 1
        # Lengths.
        kend = leng if leng < inend - i else inend - i
        cj = costs[j]
        mincostaddcostj = mincost + cj
        for k in range(3, kend + 1):
            ck = costs[j + k]
            if ck <= mincostaddcostj:
                continue
            newcost = costmodel(k, sublen[k], costcontext) + cj
            if newcost < ck:
                costs[j + k] = newcost
                length_array[j + k] = k
        i += 1


def _best_lengths_stat(s, in_, instart, inend, stats, mincost,
                       length_array, h, costs):
    """Main loop of GetBestLengths (squeeze.c) with GetCostStat inlined.

    GetCostStat(k, d) is lbits + dbits + ll_symbols[lsym] + d_symbols[dsym],
    i.e. ((int + int) + double) + double; the result is then added to
    costs[j]. The same sequence of operations is done here with table lookups.
    """
    MAX_MATCH = ZOPFLI_MAX_MATCH
    MASK = ZOPFLI_WINDOW_MASK
    ll_symbols = stats.ll_symbols
    d_symbols = stats.d_symbols
    len_extra = _LEN_EXTRA
    dist_extra = _DIST_EXTRA
    dist_symbol = _DIST_SYMBOL
    len_symbol = _LEN_SYMBOL
    flm = find_longest_match
    uh = update_hash
    sublen = [0] * 259
    same = h.same
    i = instart
    while i < inend:
        j = i - instart
        uh(in_, i, inend, h)

        # ZOPFLI_SHORTCUT_LONG_REPETITIONS
        if (same[i & MASK] > 516 and i > instart + 259 and i + 517 < inend
                and same[(i - MAX_MATCH) & MASK] > MAX_MATCH):
            symbolcost = get_cost_stat(MAX_MATCH, 1, stats)
            for _k in range(MAX_MATCH):
                costs[j + MAX_MATCH] = costs[j] + symbolcost
                length_array[j + MAX_MATCH] = MAX_MATCH
                i += 1
                j += 1
                uh(in_, i, inend, h)

        dist, leng = flm(s, h, in_, i, inend, MAX_MATCH, sublen)

        cj = costs[j]
        # Literal.
        newcost = ll_symbols[in_[i]] + cj
        if newcost < costs[j + 1]:
            costs[j + 1] = newcost
            length_array[j + 1] = 1
        # Lengths.
        kend = inend - i
        if leng < kend:
            kend = leng
        if kend >= 3:
            mincostaddcostj = mincost + cj
            for k in range(3, kend + 1):
                jk = j + k
                ck = costs[jk]
                if ck <= mincostaddcostj:
                    continue
                d = sublen[k]
                # GetCostStat(k, d), evaluated in full for every k as in C:
                # lbits + dbits + ll_symbols[lsym] + d_symbols[dsym].
                newcost = (len_extra[k] + dist_extra[d] + ll_symbols[len_symbol[k]]
                           + d_symbols[dist_symbol[d]] + cj)
                if newcost < ck:
                    costs[jk] = newcost
                    length_array[jk] = k
        i += 1


def _best_lengths_fixed(s, in_, instart, inend, mincost,
                        length_array, h, costs):
    """Main loop of GetBestLengths (squeeze.c) with GetCostFixed inlined.

    GetCostFixed returns an integer number of bits (converted to double), so
    the integer table sums below are exact and the only rounding step is the
    double addition to costs[j], as in C.
    """
    MAX_MATCH = ZOPFLI_MAX_MATCH
    MASK = ZOPFLI_WINDOW_MASK
    fixed_lit = _FIXED_LIT
    fixed_len = _FIXED_LEN
    dist_extra = _DIST_EXTRA
    flm = find_longest_match
    uh = update_hash
    sublen = [0] * 259
    same = h.same
    i = instart
    while i < inend:
        j = i - instart
        uh(in_, i, inend, h)

        # ZOPFLI_SHORTCUT_LONG_REPETITIONS
        if (same[i & MASK] > 516 and i > instart + 259 and i + 517 < inend
                and same[(i - MAX_MATCH) & MASK] > MAX_MATCH):
            symbolcost = get_cost_fixed(MAX_MATCH, 1, None)
            for _k in range(MAX_MATCH):
                costs[j + MAX_MATCH] = costs[j] + symbolcost
                length_array[j + MAX_MATCH] = MAX_MATCH
                i += 1
                j += 1
                uh(in_, i, inend, h)

        dist, leng = flm(s, h, in_, i, inend, MAX_MATCH, sublen)

        cj = costs[j]
        # Literal.
        newcost = fixed_lit[in_[i]] + cj
        if newcost < costs[j + 1]:
            costs[j + 1] = newcost
            length_array[j + 1] = 1
        # Lengths.
        kend = inend - i
        if leng < kend:
            kend = leng
        if kend >= 3:
            mincostaddcostj = mincost + cj
            for k in range(3, kend + 1):
                jk = j + k
                ck = costs[jk]
                if ck <= mincostaddcostj:
                    continue
                newcost = (fixed_len[k] + dist_extra[sublen[k]]) + cj
                if newcost < ck:
                    costs[jk] = newcost
                    length_array[jk] = k
        i += 1


def trace_backwards(size, length_array, path):
    """Port of TraceBackwards (squeeze.c).

    path: list, appended to (ZOPFLI_APPEND_DATA) and then mirrored in place.
    """
    index = size
    if size == 0:
        return
    append = path.append
    while True:
        length = length_array[index]
        append(length)
        assert length <= index
        assert length <= ZOPFLI_MAX_MATCH
        assert length != 0
        index -= length
        if index == 0:
            break

    # Mirror result.
    path.reverse()


def follow_path(s, in_, instart, inend, path, pathsize, store, h):
    """Port of FollowPath (squeeze.c).

    The assertion-only ZopfliVerifyLenDist call and the unused
    total_length_test counter are omitted (no effect on output).
    """
    windowstart = instart - ZOPFLI_WINDOW_SIZE if instart > ZOPFLI_WINDOW_SIZE else 0

    if instart == inend:
        return

    reset_hash(ZOPFLI_WINDOW_SIZE, h)
    warmup_hash(in_, windowstart, inend, h)
    for i in range(windowstart, instart):
        update_hash(in_, i, inend, h)

    uh = update_hash
    flm = find_longest_match
    store_lld = store_lit_len_dist
    pos = instart
    for i in range(pathsize):
        length = path[i]
        assert pos < inend

        uh(in_, pos, inend, h)

        # Add to output.
        if length >= ZOPFLI_MIN_MATCH:
            # Get the distance by recalculating longest match. The found length
            # should match the length from the path.
            dist, _dummy_length = flm(s, h, in_, pos, inend, length, None)
            store_lld(length, dist, pos, store)
        else:
            length = 1
            store_lld(in_[pos], 0, pos, store)

        for j in range(1, length):
            uh(in_, pos + j, inend, h)

        pos += length


def calculate_statistics(stats):
    """Port of CalculateStatistics (squeeze.c)."""
    tree.calculate_entropy(stats.litlens, ZOPFLI_NUM_LL, stats.ll_symbols)
    tree.calculate_entropy(stats.dists, ZOPFLI_NUM_D, stats.d_symbols)


def get_statistics(store, stats):
    """Port of GetStatistics (squeeze.c)."""
    litlens = stats.litlens
    dists = stats.dists
    slitlens = store.litlens
    sdists = store.dists
    len_symbol = _LEN_SYMBOL
    dist_symbol = _DIST_SYMBOL
    for i in range(store.size):
        d = sdists[i]
        if d == 0:
            litlens[slitlens[i]] += 1
        else:
            litlens[len_symbol[slitlens[i]]] += 1
            dists[dist_symbol[d]] += 1
    litlens[256] = 1  # End symbol.

    calculate_statistics(stats)


def lz77_optimal_run(s, in_, instart, inend, path, length_array, costmodel,
                     costcontext, store, h, costs):
    """Port of LZ77OptimalRun (squeeze.c).

    path: list (the C path/pathsize pair); it is emptied and refilled.
    Returns the cost according to the cost model (not the actual cost).
    """
    cost = get_best_lengths(s, in_, instart, inend, costmodel, costcontext,
                            length_array, h, costs)
    del path[:]
    trace_backwards(inend - instart, length_array, path)
    follow_path(s, in_, instart, inend, path, len(path), store, h)
    assert cost < ZOPFLI_LARGE_FLOAT
    return cost


def lz77_optimal(s, in_, instart, inend, numiterations, store):
    """Port of ZopfliLZ77Optimal (squeeze.c)."""
    # Dist to get to here with smallest cost.
    blocksize = inend - instart
    length_array = [0] * (blocksize + 1)
    path = []
    h = Hash(ZOPFLI_WINDOW_SIZE)
    costs = array('f', bytes(4 * (blocksize + 1)))
    bestcost = ZOPFLI_LARGE_FLOAT
    lastcost = 0
    # Try randomizing the costs a bit once the size stabilizes.
    ran_state = RanState()
    lastrandomstep = -1
    stats = SymbolStats()
    beststats = SymbolStats()
    laststats = SymbolStats()
    currentstore = LZ77Store(in_)
    options = s.options

    # Do regular deflate, then loop multiple shortest path runs, each time using
    # the statistics of the previous run.

    # Initial run.
    lz77_greedy(s, in_, instart, inend, currentstore, h)
    get_statistics(currentstore, stats)

    # Repeat statistics with each time the cost model from the previous stat
    # run.
    for i in range(numiterations):
        currentstore = LZ77Store(in_)
        lz77_optimal_run(s, in_, instart, inend, path, length_array,
                         get_cost_stat, stats, currentstore, h, costs)
        cost = deflate.calculate_block_size(currentstore, 0, currentstore.size, 2)
        if options.verbose_more or (options.verbose and cost < bestcost):
            sys.stderr.write("Iteration %d: %d bit\n" % (i, int(cost)))
        if cost < bestcost:
            # Copy to the output store.
            copy_lz77_store(currentstore, store)
            copy_stats(stats, beststats)
            bestcost = cost
        copy_stats(stats, laststats)
        clear_stat_freqs(stats)
        get_statistics(currentstore, stats)
        if lastrandomstep != -1:
            # This makes it converge slower but better. Do it only once the
            # randomness kicks in so that if the user does few iterations, it
            # gives a better result sooner.
            add_weighed_stat_freqs(stats, 1.0, laststats, 0.5, stats)
            calculate_statistics(stats)
        if i > 5 and cost == lastcost:
            copy_stats(beststats, stats)
            randomize_stat_freqs(ran_state, stats)
            calculate_statistics(stats)
            lastrandomstep = i
        lastcost = cost


def lz77_optimal_fixed(s, in_, instart, inend, store):
    """Port of ZopfliLZ77OptimalFixed (squeeze.c)."""
    blocksize = inend - instart
    length_array = [0] * (blocksize + 1)
    path = []
    h = Hash(ZOPFLI_WINDOW_SIZE)
    costs = array('f', bytes(4 * (blocksize + 1)))

    s.blockstart = instart
    s.blockend = inend

    # Shortest path for fixed tree This one should give the shortest possible
    # result for fixed tree, no repeated runs are needed since the tree is known.
    lz77_optimal_run(s, in_, instart, inend, path, length_array,
                     get_cost_fixed, None, store, h, costs)
