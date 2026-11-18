"""Shared helpers for test_squeeze.py and test_blocksplitter.py.

Runs the C reference harness (tools/harness/squeeze) and builds the test inputs.
"""

import importlib
import os
import random
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "harness", "squeeze"))


def _load_build(path, name):
    # Load build.py by path under a unique name: tools/harness/squeeze and
    # tools/harness/deflate both have a build.py, and a plain "import build"
    # returns whichever one was imported first in the pytest session.
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_build = _load_build(os.path.join(ROOT, "tools", "harness", "squeeze", "build.py"),
                     "_zopfli_squeeze_harness_build")

_BIN = []


def harness_bin():
    """Path of the compiled harness; skips the test if it cannot be built."""
    if not _BIN:
        try:
            _BIN.append(_build.build())
        except (OSError, subprocess.CalledProcessError) as e:  # pragma: no cover
            _BIN.append(None)
            sys.stderr.write("squeeze harness build failed: %s\n" % e)
    if _BIN[0] is None:
        pytest.skip("gcc or the zopfli reference sources are not available")
    return _BIN[0]


def run(*args, data=None, text=None):
    """Runs the harness. data (bytes) or text (str) is written to a temp file
    whose path replaces the "FILE" placeholder argument. Returns (out, err)."""
    exe = harness_bin()
    path = None
    try:
        if data is not None or text is not None:
            fd, path = tempfile.mkstemp(prefix="sqz_")
            with os.fdopen(fd, "wb") as f:
                f.write(data if data is not None else text.encode())
            args = [path if a == "FILE" else a for a in args]
        p = subprocess.run([exe] + [str(a) for a in args],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           check=True)
        return p.stdout.decode(), p.stderr.decode()
    finally:
        if path:
            os.unlink(path)


def require_modules(*names):
    """Imports zopfli_pure.<name> for each name, skipping if a dependency is
    not merged yet. Returns the modules."""
    mods = []
    for n in names:
        try:
            mods.append(importlib.import_module("zopfli_pure." + n))
        except ImportError as e:
            pytest.skip("dependency not available yet: %s" % e)
    return mods


def parse_stores(out):
    """Parses every "store N" section of harness output into
    [(litlens, dists, pos), ...]."""
    lines = out.splitlines()
    stores = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("store "):
            n = int(lines[i].split()[1])
            rows = [tuple(map(int, l.split())) for l in lines[i + 1:i + 1 + n]]
            stores.append(([r[0] for r in rows], [r[1] for r in rows],
                           [r[2] for r in rows]))
            i += n + 1
        else:
            i += 1
    return stores


def store_tuple(store):
    return (list(store.litlens), list(store.dists), list(store.pos))


def _text(rng, n):
    words = ("the quick brown fox jumps over lazy dog zopfli deflate huffman "
             "tree block split squeeze cost model entropy literal length "
             "distance window hash chain match cache iteration").split()
    out = []
    size = 0
    while size < n:
        w = rng.choice(words)
        if rng.random() < 0.1:
            w = w.capitalize() + ","
        out.append(w)
        size += len(w) + 1
    return " ".join(out).encode()[:n]


def make_inputs():
    """Named test inputs: (name, data, instart, inend)."""
    rng = random.Random(1234)
    text3k = _text(rng, 3000)
    rand2k = bytes(rng.getrandbits(8) for _ in range(2000))
    runs = (b"a" * 1500 + b"b" * 3 + b"a" * 700 + b"xyz" * 20 + b"c" * 600
            + bytes(range(256)) + b"\x00" * 1200)
    periodic = (b"abcdefghij" * 150 + b"0123456789abcdef" * 100)
    mixed = text3k[:1000] + rand2k[:500] + b"q" * 800 + text3k[1000:2200]
    big = (_text(rng, 20000) + bytes(rng.getrandbits(8) for _ in range(6000))
           + b"z" * 2000 + _text(rng, 12000))  # 40000 bytes
    return [
        ("empty", b"", 0, 0),
        ("one", b"a", 0, 1),
        ("two", b"ab", 0, 2),
        ("three", b"aaa", 0, 3),
        ("tiny", b"abcabcabcabcab", 0, 14),
        ("runs", runs, 0, len(runs)),
        ("periodic", periodic, 0, len(periodic)),
        ("text", text3k, 0, len(text3k)),
        ("random", rand2k, 0, len(rand2k)),
        ("mixed", mixed, 0, len(mixed)),
        ("text_instart", text3k, 1000, 2600),
        ("runs_instart", runs, 1400, 3500),
        ("big_window", big, 34000, 36500),   # instart > ZOPFLI_WINDOW_SIZE
        ("big_tail", big, len(big) - 4000, len(big)),
    ]


INPUTS = make_inputs()
INPUTS_BY_NAME = {n: (d, s, e) for (n, d, s, e) in INPUTS}
