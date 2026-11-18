"""Port of cache.c: the longest match cache used by find_longest_match.

ZOPFLI_LONGEST_MATCH_CACHE is on and ZOPFLI_CACHE_LENGTH is 8 in the reference
build. ``length`` and ``dist`` are ``unsigned short`` in C; every stored value
is a match length (0..258) or distance (0..32768), so plain lists of ints are
exact. ``sublen`` is the C ``unsigned char`` array of
``ZOPFLI_CACHE_LENGTH * 3 * blocksize`` bytes: entry ``j`` of position ``pos``
lives at ``sublen[(8 * pos + j) * 3 : ... + 3]`` as (length - 3, dist low byte,
dist high byte).
"""

from .util import ZOPFLI_CACHE_LENGTH


class LongestMatchCache(object):
    """Port of ZopfliLongestMatchCache (cache.h); constructor is ZopfliInitCache."""

    __slots__ = ("length", "dist", "sublen")

    def __init__(self, blocksize):
        # length > 0 and dist 0 is invalid combination, which indicates on
        # purpose that this cache value is not filled in yet.
        self.length = [1] * blocksize
        self.dist = [0] * blocksize
        # Rather large amount of memory.
        self.sublen = bytearray(ZOPFLI_CACHE_LENGTH * 3 * blocksize)


def init_cache(blocksize, lmc):
    """Port of ZopfliInitCache (cache.c)."""
    lmc.length = [1] * blocksize
    lmc.dist = [0] * blocksize
    lmc.sublen = bytearray(ZOPFLI_CACHE_LENGTH * 3 * blocksize)


def clean_cache(lmc):
    """Port of ZopfliCleanCache (cache.c)."""
    lmc.length = lmc.dist = lmc.sublen = None


def sublen_to_cache(sublen, pos, length, lmc):
    """Port of ZopfliSublenToCache (cache.c). Stores sublen array in the cache."""
    j = 0
    bestlength = 0

    cache = lmc.sublen
    base = ZOPFLI_CACHE_LENGTH * pos * 3
    if length < 3:
        return
    for i in range(3, length + 1):
        if i == length or sublen[i] != sublen[i + 1]:
            d = sublen[i]
            o = base + j * 3
            cache[o] = i - 3
            cache[o + 1] = d % 256
            cache[o + 2] = (d >> 8) % 256
            bestlength = i
            j += 1
            if j >= ZOPFLI_CACHE_LENGTH:
                break
    if j < ZOPFLI_CACHE_LENGTH:
        assert bestlength == length
        cache[base + (ZOPFLI_CACHE_LENGTH - 1) * 3] = bestlength - 3
    else:
        assert bestlength <= length
    assert bestlength == max_cached_sublen(lmc, pos, length)


def cache_to_sublen(lmc, pos, length, sublen):
    """Port of ZopfliCacheToSublen (cache.c). Extracts sublen array from the cache.

    Like the C, this fills ``sublen[0..maxlength]`` regardless of ``length``
    (``length`` is only checked against 3).
    """
    maxlength = max_cached_sublen(lmc, pos, length)
    prevlength = 0
    if length < 3:
        return
    cache = lmc.sublen
    o = ZOPFLI_CACHE_LENGTH * pos * 3
    for _ in range(ZOPFLI_CACHE_LENGTH):
        clength = cache[o] + 3
        dist = cache[o + 1] + 256 * cache[o + 2]
        # for (i = prevlength; i <= length; i++) sublen[i] = dist;
        if clength >= prevlength:
            sublen[prevlength:clength + 1] = [dist] * (clength + 1 - prevlength)
        if clength == maxlength:
            break
        prevlength = clength + 1
        o += 3


def max_cached_sublen(lmc, pos, length):
    """Port of ZopfliMaxCachedSublen (cache.c).

    Returns the length up to which could be stored in the cache.
    """
    cache = lmc.sublen
    o = ZOPFLI_CACHE_LENGTH * pos * 3
    if cache[o + 1] == 0 and cache[o + 2] == 0:
        return 0  # No sublen cached.
    return cache[o + (ZOPFLI_CACHE_LENGTH - 1) * 3] + 3
