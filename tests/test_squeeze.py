"""Tests for zopfli_pure.squeeze against the C reference harness.

The harness (tools/harness/squeeze/harness.c) unity-builds the reference
squeeze.c/blocksplitter.c so the static functions can be called directly.
Floating-point values are compared bit-exactly (via float.hex()).
"""

import os
import random
import sys
from array import array

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _squeeze_harness import (INPUTS, INPUTS_BY_NAME, parse_stores, require_modules,
                              run, store_tuple)

NUM_LL = 288
NUM_D = 32


def _sq():
    return require_modules("squeeze")[0]


def _hexes(tokens):
    """C %a strings -> canonical float.hex() strings."""
    return [float.fromhex(t).hex() for t in tokens]


def _random_counts(rng, zero_frac=0.3, maxv=5000):
    ll = [0 if rng.random() < zero_frac else rng.randrange(1, maxv)
          for _ in range(NUM_LL)]
    d = [0 if rng.random() < zero_frac else rng.randrange(1, maxv)
         for _ in range(NUM_D)]
    return ll, d


COUNT_SETS = []
_rng = random.Random(99)
for _z, _m in [(0.0, 10), (0.3, 5000), (0.8, 100), (0.95, 3), (0.5, 10 ** 7)]:
    COUNT_SETS.append(_random_counts(_rng, _z, _m))
COUNT_SETS.append(([0] * NUM_LL, [0] * NUM_D))
COUNT_SETS.append(([1] * NUM_LL, [1] * NUM_D))


# ---------------------------------------------------------------------------
# Isolated pieces: PRNG, randomization, stats arithmetic, cost models, trace.
# ---------------------------------------------------------------------------

def test_ran_sequence():
    sq = _sq()
    out, _ = run("ran", 20000)
    expected = [int(x) for x in out.split()]
    st = sq.RanState()
    got = [sq.ran(st) for _ in range(20000)]
    assert got == expected


@pytest.mark.parametrize("idx", range(len(COUNT_SETS)))
def test_randomize_stat_freqs(idx):
    sq = _sq()
    ll, d = COUNT_SETS[idx]
    out, _ = run("randomize", "FILE", 6, text=" ".join(map(str, ll + d)))
    rows = [list(map(int, line.split())) for line in out.splitlines()]
    stats = sq.SymbolStats()
    stats.litlens[:] = ll
    stats.dists[:] = d
    rs = sq.RanState()
    for row in rows:
        sq.randomize_stat_freqs(rs, stats)
        assert stats.litlens + stats.dists == row


@pytest.mark.parametrize("idx", range(len(COUNT_SETS) - 1))
def test_add_weighed_stat_freqs(idx):
    sq = _sq()
    a = COUNT_SETS[idx]
    b = COUNT_SETS[idx + 1]
    out, _ = run("addweighed", "FILE", text=" ".join(map(str, a[0] + a[1] + b[0] + b[1])))
    s1 = sq.SymbolStats()
    s1.litlens[:] = a[0]
    s1.dists[:] = a[1]
    s2 = sq.SymbolStats()
    s2.litlens[:] = b[0]
    s2.dists[:] = b[1]
    sq.add_weighed_stat_freqs(s1, 1.0, s2, 0.5, s1)
    assert s1.litlens + s1.dists == list(map(int, out.split()))


def _expected_model_costs(sq, model, ctx):
    dists = [1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13, 16, 17, 24, 25, 32, 33, 48, 49, 64,
             65, 96, 97, 128, 129, 192, 193, 256, 257, 384, 385, 512, 513, 768,
             769, 1024, 1025, 1536, 1537, 2048, 2049, 3072, 3073, 4096, 4097,
             6144, 6145, 8192, 8193, 12288, 12289, 16384, 16385, 24576, 24577,
             32767, 32768]
    lits = [model(l, 0, ctx).hex() for l in range(256)]
    lens = [model(l, d, ctx).hex() for l in range(3, 259) for d in dists]
    mincost = sq.get_cost_model_min_cost(model, ctx).hex()
    return lits, lens, mincost


@pytest.mark.parametrize("idx", range(len(COUNT_SETS)))
def test_cost_models(idx):
    """GetCostStat / GetCostFixed / GetCostModelMinCost on synthetic stats.

    Symbol costs are arbitrary doubles (not entropies) so the arithmetic of the
    cost model is tested independently of tree.calculate_entropy."""
    sq = _sq()
    rng = random.Random(idx)
    ll, d = COUNT_SETS[idx]
    llsym = [rng.uniform(0.0, 20.0) for _ in range(NUM_LL)]
    dsym = [rng.uniform(0.0, 20.0) for _ in range(NUM_D)]
    text = " ".join(map(str, ll + d)) + " " + " ".join(x.hex() for x in llsym + dsym)
    out, _ = run("costs", "FILE", text=text)
    lines = out.splitlines()
    assert len(lines) == 6
    stats = sq.SymbolStats()
    stats.litlens[:] = ll
    stats.dists[:] = d
    stats.ll_symbols[:] = llsym
    stats.d_symbols[:] = dsym
    for model, ctx, (l0, l1, l2) in ((sq.get_cost_stat, stats, lines[0:3]),
                                     (sq.get_cost_fixed, None, lines[3:6])):
        lits, lens, mincost = _expected_model_costs(sq, model, ctx)
        assert lits == _hexes(l0.split())
        assert lens == _hexes(l1.split())
        assert mincost == float.fromhex(l2).hex()


@pytest.mark.parametrize("idx", range(len(COUNT_SETS)))
def test_calculate_statistics(idx):
    sq = _sq()
    ll, d = COUNT_SETS[idx]
    out, _ = run("entropy", "FILE", text=" ".join(map(str, ll + d)))
    stats = sq.SymbolStats()
    stats.litlens[:] = ll
    stats.dists[:] = d
    sq.calculate_statistics(stats)
    assert [x.hex() for x in stats.ll_symbols + stats.d_symbols] == _hexes(out.split())


def _random_length_array(rng, size):
    """A valid length_array (every backward chain reaches 0)."""
    la = [0] * (size + 1)
    for i in range(1, size + 1):
        if i >= 3 and rng.random() < 0.6:
            la[i] = rng.randint(3, min(i, 258))
        else:
            la[i] = 1
    return la


@pytest.mark.parametrize("size", [0, 1, 2, 5, 100, 1000, 5000])
def test_trace_backwards(size):
    sq = _sq()
    la = _random_length_array(random.Random(size), size)
    out, _ = run("trace", "FILE", text="%d %s" % (size, " ".join(map(str, la))))
    path = []
    sq.trace_backwards(size, la, path)
    assert path == list(map(int, out.split()))


# ---------------------------------------------------------------------------
# End-to-end: GetBestLengths, LZ77Optimal, LZ77OptimalFixed.
# ---------------------------------------------------------------------------

def _block_state(instart, inend, add_lmc=1):
    util, lz77 = require_modules("util", "lz77")
    return lz77.BlockState(util.Options(), instart, inend, add_lmc)


def _py_best_lengths(sq, data, instart, inend, model, iters, generic=False):
    """Mirror of the harness "best" command."""
    lz77, hashm = require_modules("lz77", "hash")
    s = _block_state(instart, inend)
    h = hashm.Hash(32768)
    blocksize = inend - instart
    la = [0] * (blocksize + 1)
    costs = array('f', [0.0]) * (blocksize + 1)
    if model == 1:
        stats = sq.SymbolStats()
        store = lz77.LZ77Store(data)
        lz77.lz77_greedy(s, data, instart, inend, store, h)
        sq.get_statistics(store, stats)
        path = []
        for _ in range(iters):
            store = lz77.LZ77Store(data)
            sq.lz77_optimal_run(s, data, instart, inend, path, la, sq.get_cost_stat,
                                stats, store, h, costs)
            sq.clear_stat_freqs(stats)
            sq.get_statistics(store, stats)
        fn, ctx = sq.get_cost_stat, stats
    else:
        fn, ctx = sq.get_cost_fixed, None
    if generic:
        f0 = fn
        fn = lambda a, b, c: f0(a, b, c)  # noqa: E731  (forces the generic path)
    cost = sq.get_best_lengths(s, data, instart, inend, fn, ctx, la, h, costs)
    return cost, la, costs


BEST_CASES = [(n, m, it) for n in ("tiny", "runs", "periodic", "text", "random",
                                   "text_instart", "runs_instart", "big_window")
              for (m, it) in ((0, 0), (1, 0), (1, 2))]


@pytest.mark.parametrize("name,model,iters", BEST_CASES)
def test_get_best_lengths(name, model, iters):
    sq = _sq()
    data, instart, inend = INPUTS_BY_NAME[name]
    out, _ = run("best", "FILE", instart, inend, model, iters, data=data)
    lines = out.splitlines()
    cost, la, costs = _py_best_lengths(sq, data, instart, inend, model, iters)
    assert cost.hex() == float.fromhex(lines[0]).hex()
    assert la == list(map(int, lines[1].split()))
    assert [c.hex() for c in costs] == _hexes(lines[2].split())


@pytest.mark.parametrize("name,model", [("runs", 0), ("runs", 1), ("text", 1),
                                        ("text_instart", 0)])
def test_get_best_lengths_generic_path(name, model):
    """The specialised loops give the same result as the generic one."""
    sq = _sq()
    data, instart, inend = INPUTS_BY_NAME[name]
    a = _py_best_lengths(sq, data, instart, inend, model, 1)
    b = _py_best_lengths(sq, data, instart, inend, model, 1, generic=True)
    assert a[0].hex() == b[0].hex()
    assert a[1] == b[1]
    assert a[2].tobytes() == b[2].tobytes()


def _run_optimal(sq, data, instart, inend, numiter, monkeypatch, verbose=0):
    lz77, deflate, util = require_modules("lz77", "deflate", "util")
    trace = []
    orig_run = sq.lz77_optimal_run
    orig_bs = deflate.calculate_block_size

    def run_hook(*a):
        c = orig_run(*a)
        trace.append(["run", c])
        return c

    def bs_hook(*a):
        c = orig_bs(*a)
        if trace and len(trace[-1]) == 2:
            trace[-1].append(c)
            trace[-1].append(a[0].size)
        return c

    monkeypatch.setattr(sq, "lz77_optimal_run", run_hook)
    monkeypatch.setattr(deflate, "calculate_block_size", bs_hook)
    opts = util.Options(verbose=verbose & 1, verbose_more=(verbose >> 1) & 1)
    s = lz77.BlockState(opts, instart, inend, 1)
    store = lz77.LZ77Store(data)
    sq.lz77_optimal(s, data, instart, inend, numiter, store)
    monkeypatch.undo()
    return trace, store


OPT_CASES = ([(n, it) for (n, _d, _s, _e) in INPUTS for it in (1, 2)]
             + [(n, 5) for n in ("tiny", "runs", "text", "random", "big_window")]
             + [(n, 15) for n in ("tiny", "runs", "periodic", "text",
                                  "mixed", "runs_instart")])


@pytest.mark.parametrize("name,numiter", OPT_CASES)
def test_lz77_optimal(name, numiter, monkeypatch):
    sq = _sq()
    data, instart, inend = INPUTS_BY_NAME[name]
    out, _ = run("optimal", "FILE", instart, inend, numiter, 0, data=data)
    c_iters = [l.split() for l in out.splitlines() if l.startswith("iter ")]
    c_instr, c_real = parse_stores(out)
    assert c_instr == c_real  # the instrumented C copy matches the real one
    trace, store = _run_optimal(sq, data, instart, inend, numiter, monkeypatch)
    assert len(trace) == numiter == len(c_iters)
    for (_tag, runcost, blockcost, size), ci in zip(trace, c_iters):
        assert runcost.hex() == float.fromhex(ci[2]).hex()
        assert blockcost.hex() == float.fromhex(ci[3]).hex()
        assert size == int(ci[4])
    assert store_tuple(store) == c_real


def test_lz77_optimal_randomization_reached(monkeypatch):
    """At least one 15-iteration case repeats a cost after iteration 5, so the
    RandomizeStatFreqs / AddWeighedStatFreqs branch is exercised."""
    sq = _sq()
    data, instart, inend = INPUTS_BY_NAME["text"]
    trace, _ = _run_optimal(sq, data, instart, inend, 15, monkeypatch)
    costs = [t[2] for t in trace]
    assert any(i > 5 and costs[i] == costs[i - 1] for i in range(1, len(costs)))


@pytest.mark.parametrize("verbose", [1, 2, 3])
def test_lz77_optimal_verbose(verbose, monkeypatch, capsys):
    sq = _sq()
    data, instart, inend = INPUTS_BY_NAME["text"]
    _out, err = run("optimal", "FILE", instart, inend, 8, verbose, data=data)
    capsys.readouterr()
    _run_optimal(sq, data, instart, inend, 8, monkeypatch, verbose=verbose)
    assert capsys.readouterr().err == err


FIXED_CASES = [n for (n, _d, _s, _e) in INPUTS] + ["big_full"]


@pytest.mark.parametrize("name", FIXED_CASES)
def test_lz77_optimal_fixed(name):
    sq = _sq()
    lz77, = require_modules("lz77")
    if name == "big_full":
        data = INPUTS_BY_NAME["big_tail"][0]
        instart, inend = 0, len(data)
    else:
        data, instart, inend = INPUTS_BY_NAME[name]
    out, _ = run("fixed", "FILE", instart, inend, data=data)
    expected, = parse_stores(out)
    s = _block_state(instart, inend)
    store = lz77.LZ77Store(data)
    sq.lz77_optimal_fixed(s, data, instart, inend, store)
    assert store_tuple(store) == expected
