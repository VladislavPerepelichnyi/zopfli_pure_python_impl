"""Run individual stages of the pure-Python port with the same setup as the
C shim (tools/ref_shim.c), and localise end-to-end mismatches.

Each ``py_*`` function mirrors the ``ref.*`` function of the same name, so a
test can compare them directly. They skip the calling test (via port.need) if
the module is not merged yet.

``localize(data, **opts)`` walks the ZopfliDeflatePart pipeline for the first
master block and returns a list of human-readable findings, one per stage
whose Python output differs from C. Downstream stages are fed the *C*
intermediate results, so each finding is attributable to one function.
"""

import ref
from port import first_diff, need, options, describe_bytes_diff

WINDOW_SIZE = 32768
MASTER_BLOCK_SIZE = 1000000


def _opts(o):
    return options(**o)


def store_arrays(store):
    n = store.size
    return list(store.litlens[:n]), list(store.dists[:n]), list(store.pos[:n])


def py_store_from_arrays(data, litlens, dists, pos):
    lz77 = need("lz77", "LZ77Store", "store_lit_len_dist")
    st = lz77.LZ77Store(data)
    add = lz77.store_lit_len_dist
    for ll, d, p in zip(litlens, dists, pos):
        add(ll, d, p, st)
    return st


def py_store_from_ref(data, refstore):
    return py_store_from_arrays(data, refstore.litlens, refstore.dists,
                                refstore.pos)


def py_lz77_greedy(data, instart=0, inend=None, add_lmc=0, **opts):
    lz77 = need("lz77", "LZ77Store", "BlockState", "lz77_greedy")
    hashm = need("hash", "Hash")
    if inend is None:
        inend = len(data)
    s = lz77.BlockState(_opts(opts), instart, inend, add_lmc)
    store = lz77.LZ77Store(data)
    h = hashm.Hash(WINDOW_SIZE)
    lz77.lz77_greedy(s, data, instart, inend, store, h)
    return store


def py_lz77_optimal(data, instart=0, inend=None, numiterations=15, **opts):
    lz77 = need("lz77", "LZ77Store", "BlockState")
    sq = need("squeeze", "lz77_optimal")
    if inend is None:
        inend = len(data)
    o = dict(opts)
    o.setdefault("numiterations", numiterations)
    s = lz77.BlockState(_opts(o), instart, inend, 1)
    store = lz77.LZ77Store(data)
    sq.lz77_optimal(s, data, instart, inend, numiterations, store)
    return store


def py_lz77_optimal_fixed(data, instart=0, inend=None, **opts):
    lz77 = need("lz77", "LZ77Store", "BlockState")
    sq = need("squeeze", "lz77_optimal_fixed")
    if inend is None:
        inend = len(data)
    s = lz77.BlockState(_opts(opts), instart, inend, 1)
    store = lz77.LZ77Store(data)
    sq.lz77_optimal_fixed(s, data, instart, inend, store)
    return store


def py_find_longest_match_scan(data, positions, instart=0, inend=None,
                               limit=258):
    """FindLongestMatch at each of `positions` (ascending), hash prepared as
    in ref_find_longest_match. Yields (pos, distance, length, sublen)."""
    lz77 = need("lz77", "BlockState", "find_longest_match")
    hashm = need("hash", "Hash", "warmup_hash", "update_hash")
    if inend is None:
        inend = len(data)
    s = lz77.BlockState(_opts({}), instart, inend, 0)
    h = hashm.Hash(WINDOW_SIZE)
    hashm.reset_hash(WINDOW_SIZE, h)
    windowstart = instart - WINDOW_SIZE if instart > WINDOW_SIZE else 0
    hashm.warmup_hash(data, windowstart, inend, h)
    i = windowstart
    for p in positions:
        while i <= p:
            hashm.update_hash(data, i, inend, h)
            i += 1
        sublen = [0] * 259
        dist, length = lz77.find_longest_match(s, h, data, p, inend, limit,
                                               sublen)
        yield p, dist, length, sublen


def py_block_split_lz77(store, maxblocks, **opts):
    bs = need("blocksplitter", "block_split_lz77")
    return list(bs.block_split_lz77(_opts(opts), store, maxblocks))


def py_block_split(data, instart=0, inend=None, maxblocks=15, **opts):
    bs = need("blocksplitter", "block_split")
    if inend is None:
        inend = len(data)
    return list(bs.block_split(_opts(opts), data, instart, inend, maxblocks))


def py_calculate_block_size(store, lstart, lend, btype):
    d = need("deflate", "calculate_block_size")
    return d.calculate_block_size(store, lstart, lend, btype)


def py_calculate_block_size_auto_type(store, lstart, lend):
    d = need("deflate", "calculate_block_size_auto_type")
    return d.calculate_block_size_auto_type(store, lstart, lend)


def py_deflate(data, btype=2, final=1, **opts):
    d = need("deflate", "deflate")
    bw = need("bitwriter", "BitWriter")
    w = bw.BitWriter()
    d.deflate(_opts(opts), btype, final, data, len(data), w)
    return bytes(w.out)


def py_deflate_part(data, instart, inend, btype=2, final=1, **opts):
    d = need("deflate", "deflate_part")
    bw = need("bitwriter", "BitWriter")
    w = bw.BitWriter()
    d.deflate_part(_opts(opts), btype, final, data, instart, inend, w)
    return bytes(w.out)


# ------------------------------------------------------------- comparisons

def describe_store_diff(py_arrays, c_arrays, label):
    """None if equal, else a message naming the first differing LZ77 index."""
    pl, pd, pp = py_arrays
    cl, cd, cp = c_arrays
    py_t = list(zip(pl, pd, pp))
    c_t = list(zip(cl, cd, cp))
    i = first_diff(py_t, c_t)
    if i is None:
        return None
    lo = max(0, i - 2)
    return ("%s differs at LZ77 index %d (py size %d, C size %d); "
            "(litlen, dist, pos) py[%d:%d]=%s C[%d:%d]=%s" % (
                label, i, len(py_t), len(c_t), lo, i + 3, py_t[lo:i + 3],
                lo, i + 3, c_t[lo:i + 3]))


def localize(data, **opts):
    """Return a list of findings (strings) for the first master block of
    ZopfliDeflate(btype=2) on `data` with options `opts`. Empty if every
    checked stage matches. Stages that are not ported yet are reported as
    'skipped'."""
    import pytest
    data = bytes(data)
    o = dict(ref.DEFAULT_OPTIONS)
    o.update(opts)
    findings = []
    end = min(len(data), MASTER_BLOCK_SIZE)
    if len(data) > MASTER_BLOCK_SIZE:
        findings.append("note: only the first master block [0, %d) is "
                        "localised" % end)

    def stage(name, fn):
        try:
            msg = fn()
        except pytest.skip.Exception as e:
            findings.append("%s: skipped (%s)" % (name, e))
            return
        except Exception as e:  # report crashes as findings
            findings.append("%s: raised %s: %s" % (name, type(e).__name__, e))
            return
        if msg:
            findings.append("%s: %s" % (name, msg))

    c_split = []
    if o["blocksplitting"]:
        c_greedy = ref.lz77_greedy(data, 0, end, **o)
        stage("lz77_greedy", lambda: describe_store_diff(
            store_arrays(py_lz77_greedy(data, 0, end, **o)),
            (c_greedy.litlens, c_greedy.dists, c_greedy.pos),
            "greedy store [0,%d)" % end))

        def split_lz77_check():
            py_pts = py_block_split_lz77(py_store_from_ref(data, c_greedy),
                                         o["blocksplittingmax"], **o)
            c_pts = ref.block_split_lz77(c_greedy, o["blocksplittingmax"], **o)
            if py_pts != c_pts:
                return ("on the C greedy store: py %s, C %s"
                        % (py_pts, c_pts))
        stage("block_split_lz77 (first pass)", split_lz77_check)

        c_split = ref.block_split(data, 0, end, o["blocksplittingmax"], **o)

        def split_check():
            py_pts = py_block_split(data, 0, end, o["blocksplittingmax"], **o)
            if py_pts != c_split:
                return "byte split points py %s, C %s" % (py_pts, c_split)
        stage("block_split", split_check)

    # options without numiterations, for the lz77_optimal helpers that take
    # it as an explicit argument
    oi = dict((k, v) for k, v in o.items() if k != "numiterations")
    bounds = [0] + c_split + [end]
    c_all = ([], [], [])
    c_blocks = []
    for bi in range(len(bounds) - 1):
        a, b = bounds[bi], bounds[bi + 1]
        c_opt = ref.lz77_optimal(data, a, b, o["numiterations"], **oi)
        c_blocks.append(c_opt)
        for k in range(3):
            c_all[k].extend((c_opt.litlens, c_opt.dists, c_opt.pos)[k])

        def opt_check(a=a, b=b, c_opt=c_opt, bi=bi):
            msg = describe_store_diff(
                store_arrays(py_lz77_optimal(data, a, b, o["numiterations"], **oi)),
                (c_opt.litlens, c_opt.dists, c_opt.pos),
                "optimal store block %d [%d,%d) numiterations=%d"
                % (bi, a, b, o["numiterations"]))
            if msg and o["numiterations"] > 1:
                # find the first iteration count at which it diverges
                for it in range(1, o["numiterations"]):
                    c_it = ref.lz77_optimal(data, a, b, it, **oi)
                    if describe_store_diff(
                            store_arrays(py_lz77_optimal(data, a, b, it, **oi)),
                            (c_it.litlens, c_it.dists, c_it.pos), ""):
                        msg += "; first diverges with numiterations=%d" % it
                        break
            return msg
        stage("lz77_optimal block %d" % bi, opt_check)

        def size_check(c_opt=c_opt):
            py_store = py_store_from_ref(data, c_opt)
            n = c_opt.size
            out = []
            for bt in (0, 1, 2):
                pv = py_calculate_block_size(py_store, 0, n, bt)
                cv = ref.calculate_block_size(c_opt, 0, n, bt)
                if pv != cv:
                    out.append("btype %d py %s C %s" % (bt, float(pv).hex(), cv.hex()))
            pv = py_calculate_block_size_auto_type(py_store, 0, n)
            cv = ref.calculate_block_size_auto_type(c_opt, 0, n)
            if pv != cv:
                out.append("auto py %s C %s" % (float(pv).hex(), cv.hex()))
            return "; ".join(out) if out else None
        stage("calculate_block_size block %d (C store)" % bi, size_check)

    if o["blocksplitting"] and len(c_split) > 1:
        def split2_check():
            c_store = ref.store_from_arrays(data, *c_all)
            py_pts = py_block_split_lz77(py_store_from_arrays(data, *c_all),
                                         o["blocksplittingmax"], **o)
            c_pts = ref.block_split_lz77(c_store, o["blocksplittingmax"], **o)
            if py_pts != c_pts:
                return ("on the concatenated C optimal store: py %s, C %s"
                        % (py_pts, c_pts))
        stage("block_split_lz77 (second pass)", split2_check)

    def deflate_check():
        py_out = py_deflate_part(data, 0, end, 2, 1, **o)
        c_out = ref.deflate_part(data, 0, end, 2, 1, **o)
        if py_out != c_out:
            return describe_bytes_diff(py_out, c_out, "deflate_part output")
    stage("deflate_part [0,%d)" % end, deflate_check)
    return findings


def localize_report(data, **opts):
    try:
        f = localize(data, **opts)
    except Exception as e:  # never hide the original failure
        return "\n(localize failed: %s: %s)" % (type(e).__name__, e)
    if not f:
        return "\nlocalize: all checked stages match C (container/bitwriter issue?)"
    return "\nlocalize:\n  " + "\n  ".join(f)
