"""Port of blocksplitter.c: choosing deflate block boundaries.

deflate imports this module and this module calls
deflate.calculate_block_size_auto_type, so deflate is imported as a module and
looked up at call time (see PORTING_SPEC.md, "Import cycles").
"""

import sys

from . import deflate
from .hash import Hash
from .lz77 import BlockState, LZ77Store, lz77_greedy
from .util import ZOPFLI_LARGE_FLOAT, ZOPFLI_WINDOW_SIZE


def find_minimum(f, context, start, end):
    """Port of FindMinimum (blocksplitter.c).

    Finds the minimum of f(i, context) for i in [start, end).
    Returns (index, smallest) where smallest is the C *smallest out-parameter.
    """
    if end - start < 1024:
        best = ZOPFLI_LARGE_FLOAT
        result = start
        for i in range(start, end):
            v = f(i, context)
            if v < best:
                best = v
                result = i
        return result, best
    else:
        # Try to find minimum faster by recursively checking multiple points.
        NUM = 9  # Good value: 9.
        p = [0] * NUM
        vp = [0.0] * NUM
        lastbest = ZOPFLI_LARGE_FLOAT
        pos = start

        while True:
            if end - start <= NUM:
                break

            step = (end - start) // (NUM + 1)
            for i in range(NUM):
                p[i] = start + (i + 1) * step
                vp[i] = f(p[i], context)
            besti = 0
            best = vp[0]
            for i in range(1, NUM):
                if vp[i] < best:
                    best = vp[i]
                    besti = i
            if best > lastbest:
                break

            start = start if besti == 0 else p[besti - 1]
            end = end if besti == NUM - 1 else p[besti + 1]

            pos = p[besti]
            lastbest = best
        return pos, lastbest


def estimate_cost(lz77, lstart, lend):
    """Port of EstimateCost (blocksplitter.c)."""
    return deflate.calculate_block_size_auto_type(lz77, lstart, lend)


class SplitCostContext(object):
    """Port of struct SplitCostContext (blocksplitter.c)."""

    __slots__ = ("lz77", "start", "end")

    def __init__(self, lz77=None, start=0, end=0):
        self.lz77 = lz77
        self.start = start
        self.end = end


def split_cost(i, context):
    """Port of SplitCost (blocksplitter.c)."""
    c = context
    return estimate_cost(c.lz77, c.start, i) + estimate_cost(c.lz77, i, c.end)


def add_sorted(value, out):
    """Port of AddSorted (blocksplitter.c). out: list, modified in place."""
    out.append(value)
    outsize = len(out)
    i = 0
    while i + 1 < outsize:
        if out[i] > value:
            j = outsize - 1
            while j > i:
                out[j] = out[j - 1]
                j -= 1
            out[i] = value
            break
        i += 1


def print_block_split_points(lz77, lz77splitpoints, nlz77points):
    """Port of PrintBlockSplitPoints (blocksplitter.c); writes to stderr."""
    splitpoints = []
    # The input is given as lz77 indices, but we want to see the uncompressed
    # index values.
    pos = 0
    if nlz77points > 0:
        dists = lz77.dists
        litlens = lz77.litlens
        for i in range(lz77.size):
            length = 1 if dists[i] == 0 else litlens[i]
            if lz77splitpoints[len(splitpoints)] == i:
                splitpoints.append(pos)
                if len(splitpoints) == nlz77points:
                    break
            pos += length
    assert len(splitpoints) == nlz77points

    parts = ["block split points: "]
    for sp in splitpoints:
        parts.append("%d " % sp)
    parts.append("(hex:")
    for sp in splitpoints:
        parts.append(" %x" % sp)
    parts.append(")\n")
    sys.stderr.write("".join(parts))


def find_largest_splittable_block(lz77size, done, splitpoints, npoints):
    """Port of FindLargestSplittableBlock (blocksplitter.c).

    Returns (found, lstart, lend); lstart/lend are None when nothing is found
    (the C code leaves its out-parameters untouched in that case).
    """
    longest = 0
    found = 0
    lstart = None
    lend = None
    for i in range(npoints + 1):
        start = 0 if i == 0 else splitpoints[i - 1]
        end = lz77size - 1 if i == npoints else splitpoints[i]
        if not done[start] and end - start > longest:
            lstart = start
            lend = end
            found = 1
            longest = end - start
    return found, lstart, lend


def block_split_lz77(options, lz77, maxblocks):
    """Port of ZopfliBlockSplitLZ77 (blocksplitter.c).

    Returns the list of split points (LZ77 indices), replacing the C
    splitpoints/npoints out-parameters.
    """
    splitpoints = []
    numblocks = 1

    if lz77.size < 10:
        return splitpoints  # This code fails on tiny files.

    done = bytearray(lz77.size)

    lstart = 0
    lend = lz77.size
    while True:
        if maxblocks > 0 and numblocks >= maxblocks:
            break

        c = SplitCostContext(lz77, lstart, lend)
        assert lstart < lend
        llpos, splitcost = find_minimum(split_cost, c, lstart + 1, lend)

        assert llpos > lstart
        assert llpos < lend

        origcost = estimate_cost(lz77, lstart, lend)

        if splitcost > origcost or llpos == lstart + 1 or llpos == lend:
            done[lstart] = 1
        else:
            add_sorted(llpos, splitpoints)
            numblocks += 1

        found, nstart, nend = find_largest_splittable_block(
            lz77.size, done, splitpoints, len(splitpoints))
        if not found:
            break  # No further split will probably reduce compression.
        lstart = nstart
        lend = nend

        if lend - lstart < 10:
            break

    if options.verbose:
        print_block_split_points(lz77, splitpoints, len(splitpoints))

    return splitpoints


def block_split(options, in_, instart, inend, maxblocks):
    """Port of ZopfliBlockSplit (blocksplitter.c).

    Returns the list of split points as positions in the uncompressed input.
    """
    store = LZ77Store(in_)
    s = BlockState(options, instart, inend, 0)
    h = Hash(ZOPFLI_WINDOW_SIZE)

    splitpoints = []

    # Unintuitively, Using a simple LZ77 method here instead of ZopfliLZ77Optimal
    # results in better blocks.
    lz77_greedy(s, in_, instart, inend, store, h)

    lz77splitpoints = block_split_lz77(options, store, maxblocks)
    nlz77points = len(lz77splitpoints)

    # Convert LZ77 positions to positions in the uncompressed input.
    pos = instart
    if nlz77points > 0:
        dists = store.dists
        litlens = store.litlens
        for i in range(store.size):
            length = 1 if dists[i] == 0 else litlens[i]
            if lz77splitpoints[len(splitpoints)] == i:
                splitpoints.append(pos)
                if len(splitpoints) == nlz77points:
                    break
            pos += length
    assert len(splitpoints) == nlz77points

    return splitpoints


def block_split_simple(in_, instart, inend, blocksize):
    """Port of ZopfliBlockSplitSimple (blocksplitter.c)."""
    splitpoints = []
    i = instart
    while i < inend:
        splitpoints.append(i)
        i += blocksize
    return splitpoints
