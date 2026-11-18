"""Port of lz77.c: LZ77 store, longest match finder and greedy LZ77.

Built with ZOPFLI_LONGEST_MATCH_CACHE, ZOPFLI_HASH_SAME, ZOPFLI_HASH_SAME_HASH
and ZOPFLI_LAZY_MATCHING on (ZOPFLI_MAX_CHAIN_HITS = 8192 < window size, so the
chain counter is compiled in). See docs/notes/lz77.md for the porting notes.
"""

from .util import (ZOPFLI_MAX_MATCH, ZOPFLI_MIN_MATCH, ZOPFLI_NUM_LL,
                   ZOPFLI_NUM_D, ZOPFLI_WINDOW_SIZE, ZOPFLI_WINDOW_MASK,
                   ZOPFLI_MAX_CHAIN_HITS, ZOPFLI_CACHE_LENGTH)
from .symbols import LENGTH_SYMBOL, DIST_SYMBOL
from .cache import (LongestMatchCache, max_cached_sublen, cache_to_sublen,
                    sublen_to_cache)
from .hash import reset_hash, warmup_hash, update_hash


class LZ77Store(object):
    """Port of ZopfliLZ77Store (lz77.h); constructor is ZopfliInitLZ77Store.

    litlens: literal byte or match length; dists: 0 for a literal, else the
    distance; pos: position in data where the command begins; ll_symbol /
    d_symbol: the deflate symbols; ll_counts / d_counts: cumulative histograms
    wrapping around per chunk of ZOPFLI_NUM_LL (resp. ZOPFLI_NUM_D) symbols.
    ``size`` is a read-only property equal to ``len(litlens)``.
    """

    __slots__ = ("litlens", "dists", "pos", "ll_symbol", "d_symbol",
                 "ll_counts", "d_counts", "data")

    def __init__(self, data):
        self.litlens = []
        self.dists = []
        self.pos = []
        self.data = data
        self.ll_symbol = []
        self.d_symbol = []
        self.ll_counts = []
        self.d_counts = []

    @property
    def size(self):
        return len(self.litlens)


def init_lz77_store(data, store):
    """Port of ZopfliInitLZ77Store (lz77.c). Re-initializes ``store`` in place."""
    store.litlens = []
    store.dists = []
    store.pos = []
    store.data = data
    store.ll_symbol = []
    store.d_symbol = []
    store.ll_counts = []
    store.d_counts = []


def clean_lz77_store(store):
    """Port of ZopfliCleanLZ77Store (lz77.c). Empties the arrays."""
    init_lz77_store(store.data, store)


def ceil_div(a, b):
    """Port of CeilDiv (lz77.c, static)."""
    return (a + b - 1) // b


def copy_lz77_store(source, dest):
    """Port of ZopfliCopyLZ77Store (lz77.c). Overwrites ``dest`` with a copy."""
    size = len(source.litlens)
    llsize = ZOPFLI_NUM_LL * ceil_div(size, ZOPFLI_NUM_LL)
    dsize = ZOPFLI_NUM_D * ceil_div(size, ZOPFLI_NUM_D)
    dest.data = source.data
    dest.litlens = source.litlens[:size]
    dest.dists = source.dists[:size]
    dest.pos = source.pos[:size]
    dest.ll_symbol = source.ll_symbol[:size]
    dest.d_symbol = source.d_symbol[:size]
    dest.ll_counts = source.ll_counts[:llsize]
    dest.d_counts = source.d_counts[:dsize]


def store_lit_len_dist(length, dist, pos, store):
    """Port of ZopfliStoreLitLenDist (lz77.c).

    Appends the length and distance to the LZ77 arrays of the store.
    """
    origsize = len(store.litlens)
    llstart = ZOPFLI_NUM_LL * (origsize // ZOPFLI_NUM_LL)
    dstart = ZOPFLI_NUM_D * (origsize // ZOPFLI_NUM_D)

    # Everytime the index wraps around, a new cumulative histogram is made:
    # we're keeping one histogram value per LZ77 symbol rather than a full
    # histogram for each to save memory.
    if origsize % ZOPFLI_NUM_LL == 0:
        ll_counts = store.ll_counts
        if origsize == 0:
            ll_counts.extend([0] * ZOPFLI_NUM_LL)
        else:
            ll_counts.extend(ll_counts[origsize - ZOPFLI_NUM_LL:origsize])
    if origsize % ZOPFLI_NUM_D == 0:
        d_counts = store.d_counts
        if origsize == 0:
            d_counts.extend([0] * ZOPFLI_NUM_D)
        else:
            d_counts.extend(d_counts[origsize - ZOPFLI_NUM_D:origsize])

    store.litlens.append(length)
    store.dists.append(dist)
    store.pos.append(pos)
    assert length < 259

    if dist == 0:
        store.ll_symbol.append(length)
        store.d_symbol.append(0)
        store.ll_counts[llstart + length] += 1
    else:
        lsym = LENGTH_SYMBOL[length]
        dsym = DIST_SYMBOL[dist]
        store.ll_symbol.append(lsym)
        store.d_symbol.append(dsym)
        store.ll_counts[llstart + lsym] += 1
        store.d_counts[dstart + dsym] += 1


def append_lz77_store(store, target):
    """Port of ZopfliAppendLZ77Store (lz77.c)."""
    litlens = store.litlens
    dists = store.dists
    pos = store.pos
    for i in range(len(litlens)):
        store_lit_len_dist(litlens[i], dists[i], pos[i], target)


def lz77_get_byte_range(lz77, lstart, lend):
    """Port of ZopfliLZ77GetByteRange (lz77.c).

    Gets the amount of raw bytes that this range of LZ77 symbols spans.
    """
    l = lend - 1
    if lstart == lend:
        return 0
    return (lz77.pos[l] + (1 if lz77.dists[l] == 0 else lz77.litlens[l])
            - lz77.pos[lstart])


def lz77_get_histogram_at(lz77, lpos, ll_counts, d_counts):
    """Port of ZopfliLZ77GetHistogramAt (lz77.c, static).

    The real histogram is created by using the histogram for this chunk, but
    all superfluous values of this chunk subtracted.
    """
    llpos = ZOPFLI_NUM_LL * (lpos // ZOPFLI_NUM_LL)
    dpos = ZOPFLI_NUM_D * (lpos // ZOPFLI_NUM_D)
    size = len(lz77.litlens)
    ll_counts[0:ZOPFLI_NUM_LL] = lz77.ll_counts[llpos:llpos + ZOPFLI_NUM_LL]
    ll_symbol = lz77.ll_symbol
    end = llpos + ZOPFLI_NUM_LL
    if end > size:
        end = size
    for i in range(lpos + 1, end):
        ll_counts[ll_symbol[i]] -= 1
    d_counts[0:ZOPFLI_NUM_D] = lz77.d_counts[dpos:dpos + ZOPFLI_NUM_D]
    dists = lz77.dists
    d_symbol = lz77.d_symbol
    end = dpos + ZOPFLI_NUM_D
    if end > size:
        end = size
    for i in range(lpos + 1, end):
        if dists[i] != 0:
            d_counts[d_symbol[i]] -= 1


def lz77_get_histogram(lz77, lstart, lend, ll_counts, d_counts):
    """Port of ZopfliLZ77GetHistogram (lz77.c).

    Gets the histogram of lit/len and dist symbols in the given range, using
    the cumulative histograms, so faster than adding one by one for large
    range. Does not add the one end symbol of value 256. Fills the
    caller-provided ``ll_counts`` (288) and ``d_counts`` (32) lists in place.
    """
    if lstart + ZOPFLI_NUM_LL * 3 > lend:
        ll_counts[0:ZOPFLI_NUM_LL] = [0] * ZOPFLI_NUM_LL
        d_counts[0:ZOPFLI_NUM_D] = [0] * ZOPFLI_NUM_D
        ll_symbol = lz77.ll_symbol
        d_symbol = lz77.d_symbol
        dists = lz77.dists
        for i in range(lstart, lend):
            ll_counts[ll_symbol[i]] += 1
            if dists[i] != 0:
                d_counts[d_symbol[i]] += 1
    else:
        # Subtract the cumulative histograms at the end and the start to get
        # the histogram for this range.
        lz77_get_histogram_at(lz77, lend - 1, ll_counts, d_counts)
        if lstart > 0:
            ll_counts2 = [0] * ZOPFLI_NUM_LL
            d_counts2 = [0] * ZOPFLI_NUM_D
            lz77_get_histogram_at(lz77, lstart - 1, ll_counts2, d_counts2)

            for i in range(ZOPFLI_NUM_LL):
                ll_counts[i] -= ll_counts2[i]
            for i in range(ZOPFLI_NUM_D):
                d_counts[i] -= d_counts2[i]


class BlockState(object):
    """Port of ZopfliBlockState (lz77.h); constructor is ZopfliInitBlockState.

    ``lmc`` is a LongestMatchCache covering [blockstart, blockend) if
    ``add_lmc``, else None.
    """

    __slots__ = ("options", "lmc", "blockstart", "blockend")

    def __init__(self, options, blockstart, blockend, add_lmc):
        self.options = options
        self.blockstart = blockstart
        self.blockend = blockend
        if add_lmc:
            self.lmc = LongestMatchCache(blockend - blockstart)
        else:
            self.lmc = None


def clean_block_state(s):
    """Port of ZopfliCleanBlockState (lz77.c)."""
    s.lmc = None


def get_length_score(length, distance):
    """Port of GetLengthScore (lz77.c, static).

    At 1024, the distance uses 9+ extra bits and this seems to be the sweet
    spot on tested files.
    """
    return length - 1 if distance > 1024 else length


def verify_len_dist(data, datasize, pos, dist, length):
    """Port of ZopfliVerifyLenDist (lz77.c). Assertion helper only."""
    assert pos + length <= datasize
    assert dist <= pos or length == 0
    assert data[pos - dist:pos - dist + length] == data[pos:pos + length]


def get_match(array, scan, match, end):
    """Port of GetMatch (lz77.c, static), on indices instead of pointers.

    Returns the index after the last byte from ``scan`` that equals the
    corresponding byte from ``match``, stopping at ``end``. The C compares 8
    bytes at a time while ``scan < end - 8`` and then byte by byte; the result
    is the same as a plain byte-by-byte comparison, which is what is done here.
    """
    while scan != end and array[scan] == array[match]:
        scan += 1
        match += 1
    return scan


def try_get_from_longest_match_cache(s, pos, limit, sublen):
    """Port of TryGetFromLongestMatchCache (lz77.c, static).

    Returns ``(found, limit, distance, length)``: ``found`` is 1 if the values
    came from the cache (then distance/length are set), else 0 and ``limit``
    may have been lowered. (find_longest_match inlines this logic; this
    function is kept for reference and tests.)
    """
    lmc = s.lmc
    lmcpos = pos - s.blockstart
    if lmc is None:
        return 0, limit, None, None
    clen = lmc.length[lmcpos]
    cache_available = clen == 0 or lmc.dist[lmcpos] != 0
    limit_ok_for_cache = cache_available and (
        limit == ZOPFLI_MAX_MATCH or clen <= limit
        or (sublen is not None
            and max_cached_sublen(lmc, lmcpos, clen) >= limit))
    if limit_ok_for_cache and cache_available:
        if sublen is None or clen <= max_cached_sublen(lmc, lmcpos, clen):
            length = clen
            if length > limit:
                length = limit
            if sublen is not None:
                cache_to_sublen(lmc, lmcpos, length, sublen)
                distance = sublen[length]
                if limit == ZOPFLI_MAX_MATCH and length >= ZOPFLI_MIN_MATCH:
                    assert sublen[length] == lmc.dist[lmcpos]
            else:
                distance = lmc.dist[lmcpos]
            return 1, limit, distance, length
        # Can't use much of the cache, since the "sublens" need to be
        # calculated, but at least we already know when to stop.
        limit = clen
    return 0, limit, None, None


def store_in_longest_match_cache(s, pos, limit, sublen, distance, length):
    """Port of StoreInLongestMatchCache (lz77.c, static)."""
    lmc = s.lmc
    if lmc is None:
        return
    lmcpos = pos - s.blockstart
    cache_available = lmc.length[lmcpos] == 0 or lmc.dist[lmcpos] != 0
    if limit == ZOPFLI_MAX_MATCH and sublen is not None and not cache_available:
        assert lmc.length[lmcpos] == 1 and lmc.dist[lmcpos] == 0
        lmc.dist[lmcpos] = 0 if length < ZOPFLI_MIN_MATCH else distance
        lmc.length[lmcpos] = 0 if length < ZOPFLI_MIN_MATCH else length
        assert not (lmc.length[lmcpos] == 1 and lmc.dist[lmcpos] == 0)
        sublen_to_cache(sublen, lmcpos, length, lmc)


def find_longest_match(s, h, array, pos, size, limit, sublen):
    """Port of ZopfliFindLongestMatch (lz77.c).

    Finds the longest match (length and corresponding distance) for LZ77
    compression. ``sublen`` is a list of at least 259 ints (filled in place:
    for each length, the smallest distance required to reach it) or None.
    Returns ``(distance, length)``.
    """
    lmc = s.lmc
    if lmc is not None:
        # TryGetFromLongestMatchCache, inlined.
        lmcpos = pos - s.blockstart
        clen = lmc.length[lmcpos]
        # Length > 0 and dist 0 is invalid combination, which indicates on
        # purpose that this cache value is not filled in yet.
        if clen == 0 or lmc.dist[lmcpos] != 0:  # cache_available
            if (limit == ZOPFLI_MAX_MATCH or clen <= limit
                    or (sublen is not None
                        and max_cached_sublen(lmc, lmcpos, clen) >= limit)):
                if (sublen is None
                        or clen <= max_cached_sublen(lmc, lmcpos, clen)):
                    length = clen
                    if length > limit:
                        length = limit
                    if sublen is not None:
                        cache_to_sublen(lmc, lmcpos, length, sublen)
                        distance = sublen[length]
                    else:
                        distance = lmc.dist[lmcpos]
                    return distance, length
                # Can't use much of the cache, since the "sublens" need to be
                # calculated, but at least we already know when to stop.
                limit = clen

    if size - pos < ZOPFLI_MIN_MATCH:
        # The rest of the code assumes there are at least ZOPFLI_MIN_MATCH
        # bytes to try.
        return 0, 0

    if pos + limit > size:
        limit = size - pos
    arrayend = pos + limit

    hpos = pos & ZOPFLI_WINDOW_MASK
    hprev = h.prev
    hsame = h.same
    same0 = hsame[hpos]
    val2 = h.val2
    hashval2 = h.hashval2
    on_hash2 = False
    c0 = array[pos]

    bestdist = 0
    bestlength = 1
    chain_counter = ZOPFLI_MAX_CHAIN_HITS  # For quitting early.

    pp = h.head[h.val]  # During the whole loop, p == hprev[pp].
    p = hprev[pp]

    dist = pp - p if p < pp else ((ZOPFLI_WINDOW_SIZE - p) + pp)

    # Go through all distances.
    while dist < ZOPFLI_WINDOW_SIZE:
        if dist > 0:
            mpos = pos - dist
            # Testing the byte at position bestlength first, goes slightly
            # faster.
            if (pos + bestlength >= size
                    or array[pos + bestlength] == array[mpos + bestlength]):
                scan = pos
                match = mpos
                if same0 > 2 and c0 == array[mpos]:
                    same1 = hsame[mpos & ZOPFLI_WINDOW_MASK]
                    same = same0 if same0 < same1 else same1
                    if same > limit:
                        same = limit
                    scan += same
                    match += same
                # GetMatch, inlined.
                while scan != arrayend and array[scan] == array[match]:
                    scan += 1
                    match += 1
                currentlength = scan - pos  # The found length.

                if currentlength > bestlength:
                    if sublen is not None:
                        sublen[bestlength + 1:currentlength + 1] = (
                            [dist] * (currentlength - bestlength))
                    bestdist = dist
                    bestlength = currentlength
                    if currentlength >= limit:
                        break

        # Switch to the other hash once this will be more efficient.
        if (not on_hash2 and bestlength >= same0
                and val2 == hashval2[p]):
            # Now use the hash that encodes the length and first byte.
            hprev = h.prev2
            on_hash2 = True

        pp = p
        p = hprev[p]
        if p == pp:
            break  # Uninited prev value.

        dist += pp - p if p < pp else ((ZOPFLI_WINDOW_SIZE - p) + pp)

        chain_counter -= 1
        if chain_counter <= 0:
            break

    if lmc is not None:
        # StoreInLongestMatchCache, inlined.
        if (limit == ZOPFLI_MAX_MATCH and sublen is not None
                and not (lmc.length[lmcpos] == 0 or lmc.dist[lmcpos] != 0)):
            if bestlength < ZOPFLI_MIN_MATCH:
                lmc.dist[lmcpos] = 0
                lmc.length[lmcpos] = 0
            else:
                lmc.dist[lmcpos] = bestdist
                lmc.length[lmcpos] = bestlength
            sublen_to_cache(sublen, lmcpos, bestlength, lmc)

    return bestdist, bestlength


def lz77_greedy(s, in_, instart, inend, store, h):
    """Port of ZopfliLZ77Greedy (lz77.c).

    Does LZ77 using an algorithm similar to gzip, with lazy matching, rather
    than with the slow but better "squeeze" implementation. The result is
    appended to ``store``. If instart is larger than 0, it uses values before
    instart as starting dictionary.
    """
    windowstart = (instart - ZOPFLI_WINDOW_SIZE
                   if instart > ZOPFLI_WINDOW_SIZE else 0)
    dummysublen = [0] * 259

    # Lazy matching.
    prev_length = 0
    prev_match = 0
    match_available = 0

    if instart == inend:
        return

    reset_hash(ZOPFLI_WINDOW_SIZE, h)
    warmup_hash(in_, windowstart, inend, h)
    for i in range(windowstart, instart):
        update_hash(in_, i, inend, h)

    i = instart
    while i < inend:
        update_hash(in_, i, inend, h)

        dist, leng = find_longest_match(s, h, in_, i, inend, ZOPFLI_MAX_MATCH,
                                        dummysublen)
        lengthscore = leng - 1 if dist > 1024 else leng

        # Lazy matching.
        prevlengthscore = prev_length - 1 if prev_match > 1024 else prev_length
        if match_available:
            match_available = 0
            if lengthscore > prevlengthscore + 1:
                store_lit_len_dist(in_[i - 1], 0, i - 1, store)
                if lengthscore >= ZOPFLI_MIN_MATCH and leng < ZOPFLI_MAX_MATCH:
                    match_available = 1
                    prev_length = leng
                    prev_match = dist
                    i += 1
                    continue
            else:
                # Add previous to output.
                leng = prev_length
                dist = prev_match
                lengthscore = prevlengthscore
                # Add to output.
                verify_len_dist(in_, inend, i - 1, dist, leng)
                store_lit_len_dist(leng, dist, i - 1, store)
                for _ in range(2, leng):
                    assert i < inend
                    i += 1
                    update_hash(in_, i, inend, h)
                i += 1
                continue
        elif lengthscore >= ZOPFLI_MIN_MATCH and leng < ZOPFLI_MAX_MATCH:
            match_available = 1
            prev_length = leng
            prev_match = dist
            i += 1
            continue
        # End of lazy matching.

        # Add to output.
        if lengthscore >= ZOPFLI_MIN_MATCH:
            verify_len_dist(in_, inend, i, dist, leng)
            store_lit_len_dist(leng, dist, i, store)
        else:
            leng = 1
            store_lit_len_dist(in_[i], 0, i, store)
        for _ in range(1, leng):
            assert i < inend
            i += 1
            update_hash(in_, i, inend, h)
        i += 1
