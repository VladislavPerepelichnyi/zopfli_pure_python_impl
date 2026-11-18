"""Tests for zopfli_pure.blocksplitter against the C reference harness."""

import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _squeeze_harness import (INPUTS, INPUTS_BY_NAME, require_modules,  # noqa: E402
                              run)


def _bs():
    return require_modules("blocksplitter")[0]


def _synth(k, x):
    """Python twin of SynthF in harness.c (all values exact in double)."""
    if k == 0:
        a = x - 777 if x > 777 else 777 - x
        return float(a * a)
    if k == 1:
        return float((x * 2654435761) % 100003)
    if k == 2:
        return float(x - 5000 if x > 5000 else 5000 - x) * 0.5 + float((x * 40503) % 977)
    if k == 3:
        return 42.0
    if k == 4:
        return 1e6 - float(x)
    if k == 5:
        return float(x) * 0.25
    return 1.0 if x % 1000 == 3 else 2e30


FINDMIN_CASES = [(k, s, e) for k in range(7)
                 for (s, e) in ((0, 0), (5, 6), (0, 10), (1, 1023), (1, 1024),
                                (0, 1025), (100, 5000), (3, 20000), (1, 65537),
                                (4000, 4013), (0, 123457))]


@pytest.mark.parametrize("k,start,end", FINDMIN_CASES)
def test_find_minimum(k, start, end):
    bs = _bs()
    out, _ = run("findmin", k, start, end)
    idx, smallest = out.split()
    got = bs.find_minimum(lambda i, c: _synth(c, i), k, start, end)
    assert got[0] == int(idx)
    assert got[1].hex() == float.fromhex(smallest).hex()


def test_add_sorted():
    bs = _bs()
    rng = random.Random(5)
    out = []
    ref = []
    for _ in range(200):
        v = rng.randrange(1000)
        bs.add_sorted(v, out)
        ref.append(v)
        # AddSorted inserts before the first strictly greater element.
        assert out == sorted(ref)


def test_block_split_simple():
    bs = _bs()
    assert bs.block_split_simple(b"", 0, 0, 10) == []
    assert bs.block_split_simple(b"x" * 25, 3, 25, 10) == [3, 13, 23]
    assert bs.block_split_simple(b"x" * 20, 0, 20, 10) == [0, 10]


def _points(out):
    lines = out.split()
    assert lines[0] == "split"
    n = int(lines[1])
    return [int(x) for x in lines[2:2 + n]]


SPLIT_INPUTS = [n for (n, _d, _s, _e) in INPUTS] + ["big_full"]


def _input(name):
    if name == "big_full":
        data = INPUTS_BY_NAME["big_tail"][0]
        return data, 0, len(data)
    return INPUTS_BY_NAME[name]


# block_split on large inputs is dominated by calculate_block_size_auto_type
# (thousands of Huffman tree builds), so the most expensive combinations are
# limited to keep the suite fast: maxblocks 0 and 15 do the same work when the
# block count stays below 15, so 15 is only run on the smaller inputs.
_EXPENSIVE = ("mixed", "big_full", "big_tail")
SPLIT_CASES = ([(n, mb) for n in SPLIT_INPUTS for mb in (0, 1, 3)]
               + [(n, 15) for n in SPLIT_INPUTS if n not in _EXPENSIVE])


@pytest.mark.parametrize("name,maxblocks", SPLIT_CASES)
def test_block_split(name, maxblocks):
    bs = _bs()
    util, = require_modules("util")
    data, instart, inend = _input(name)
    out, _ = run("split", "FILE", instart, inend, maxblocks, 0, data=data)
    got = bs.block_split(util.Options(), data, instart, inend, maxblocks)
    assert got == _points(out)


@pytest.mark.parametrize("name", ["text", "big_window"])
def test_block_split_verbose(name, capsys):
    bs = _bs()
    util, = require_modules("util")
    data, instart, inend = _input(name)
    out, err = run("split", "FILE", instart, inend, 15, 1, data=data)
    capsys.readouterr()
    got = bs.block_split(util.Options(verbose=1), data, instart, inend, 15)
    assert got == _points(out)
    assert capsys.readouterr().err == err


SPLIT_LZ77_CASES = ([(n, mb, 0) for n in ("runs", "text", "random",
                                          "runs_instart", "big_tail")
                     for mb in (0, 1, 3, 15)]
                    + [(n, mb, 2) for n in ("text", "big_tail")
                       for mb in (0, 3)])


@pytest.mark.parametrize("name,maxblocks,numiter", SPLIT_LZ77_CASES)
def test_block_split_lz77(name, maxblocks, numiter):
    bs = _bs()
    util, lz77, hashm, squeeze = require_modules("util", "lz77", "hash", "squeeze")
    data, instart, inend = _input(name)
    out, err = run("splitlz77", "FILE", instart, inend, maxblocks, numiter, 1,
                   data=data)
    opts = util.Options()
    store = lz77.LZ77Store(data)
    if numiter == 0:
        s = lz77.BlockState(opts, instart, inend, 0)
        lz77.lz77_greedy(s, data, instart, inend, store, hashm.Hash(32768))
    else:
        s = lz77.BlockState(opts, instart, inend, 1)
        squeeze.lz77_optimal(s, data, instart, inend, numiter, store)
    assert bs.block_split_lz77(opts, store, maxblocks) == _points(out)


def test_block_split_lz77_verbose(capsys):
    bs = _bs()
    util, lz77, hashm = require_modules("util", "lz77", "hash")
    data, instart, inend = _input("text")
    out, err = run("splitlz77", "FILE", instart, inend, 0, 0, 1, data=data)
    store = lz77.LZ77Store(data)
    s = lz77.BlockState(util.Options(), instart, inend, 0)
    lz77.lz77_greedy(s, data, instart, inend, store, hashm.Hash(32768))
    capsys.readouterr()
    assert bs.block_split_lz77(util.Options(verbose=1), store, 0) == _points(out)
    assert capsys.readouterr().err == err
