"""Helpers to reach the (possibly incomplete) zopfli_pure port from tests.

While the port is being written module by module, a test that needs a module
which has not been merged yet is *skipped* (with the missing module named in
the reason). A module that exists but fails to import for another reason
(syntax error, a name missing from a sibling module, ...) makes the test
*fail*, because that is a real bug.
"""

import pytest

_compress_cache = {}
_DEFAULTS = dict(verbose=0, numiterations=15, blocksplitting=1,
                 blocksplittinglast=0, blocksplittingmax=15, gzip_mode=0)


def need(modname, *attrs):
    """Import zopfli_pure.<modname> (or zopfli_pure if modname is "") and
    return it; skip if it (or one of `attrs`) does not exist yet."""
    full = "zopfli_pure" + ("." + modname if modname else "")
    try:
        mod = __import__(full, fromlist=["_"])
    except ModuleNotFoundError as e:
        if e.name and (e.name == "zopfli_pure" or e.name.startswith("zopfli_pure.")):
            pytest.skip("%s not available yet (%s)" % (full, e))
        raise
    for a in attrs:
        if not hasattr(mod, a):
            pytest.skip("%s.%s not available yet" % (full, a))
    return mod


def compress_fn():
    return need("", "compress").compress


def options(**kw):
    """zopfli_pure.util.Options with keyword overrides."""
    util = need("util", "Options")
    return util.Options(**kw)


def compress(data, **opts):
    """zopfli_pure.compress(data, **opts), memoised per session so that the
    round-trip and oracle tests can share the (slow) pure-Python result."""
    fn = compress_fn()
    full = dict(_DEFAULTS)
    full.update(opts)
    if set(full) == set(_DEFAULTS) and all(
            type(v) in (int, bool) for v in full.values()):
        # normalise so that equal calls share results
        full = dict((k, int(v)) for k, v in full.items())
    key = (bytes(data) if not isinstance(data, str) else data,
           tuple(sorted(full.items())))
    r = _compress_cache.get(key)
    if r is None:
        r = fn(data, **opts)
        if len(_compress_cache) > 2000:
            _compress_cache.clear()
        _compress_cache[key] = r
    return r


def compress_format(fmt, data, **opts):
    """zopfli_pure.zopfli_lib.compress_format(Options(**opts), fmt, data)."""
    lib = need("zopfli_lib", "compress_format")
    return lib.compress_format(options(**opts), fmt, data)


def first_diff(a, b):
    """Index of the first differing element of two sequences (or the shorter
    length if one is a prefix of the other), None if equal."""
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    if len(a) != len(b):
        return n
    return None


def describe_bytes_diff(got, want, label="output"):
    i = first_diff(got, want)
    if i is None:
        return "%s identical" % label
    lo = max(0, i - 4)
    return ("%s differs at byte %d (got len %d, want len %d): "
            "got[%d:%d]=%s want[%d:%d]=%s" % (
                label, i, len(got), len(want), lo, i + 8,
                bytes(got[lo:i + 8]).hex(), lo, i + 8,
                bytes(want[lo:i + 8]).hex()))
