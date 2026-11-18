"""Public API of zopfli_pure.compress compared with py-zopfli's
zopfli.zopfli.compress: positional/keyword arguments, defaults, input types,
return type, and which calls raise which exception type.

Deliberate extension (docs/PORTING_SPEC.md): zopfli_pure also accepts
bytearray and memoryview (py-zopfli rejects them with TypeError); the result
must equal the oracle's output for the same bytes.
"""

import array

import pytest

from port import compress_fn

zopfli_oracle = pytest.importorskip("zopfli.zopfli")

DATA = b"abcabcabd" * 30 + bytes(range(200)) * 2 + b"x" * 300
SMALL = b"Hello, Hello, Hello!"


class Index3(object):
    def __index__(self):
        return 3


def outcome(f, args, kwargs):
    try:
        r = f(*args, **kwargs)
    except Exception as e:  # compare exception *types*
        return ("exc", type(e))
    return ("ok", r)


CALLS = [
    ("bytes", (SMALL,), {}),
    ("bytes_empty", (b"",), {}),
    ("str", ("héllo €",), {}),
    ("str_empty", ("",), {}),
    ("kw_data", (), dict(data=SMALL)),
    ("all_kw", (DATA,), dict(verbose=0, numiterations=2, blocksplitting=1,
                             blocksplittinglast=0, blocksplittingmax=3,
                             gzip_mode=1)),
    ("pos_1", (DATA, 0), {}),
    ("pos_2", (DATA, 0, 2), {}),
    ("pos_3", (DATA, 0, 2, 0), {}),
    ("pos_4", (DATA, 0, 2, 1, 0), {}),
    ("pos_5", (DATA, 0, 2, 1, 0, 3), {}),
    ("pos_6", (DATA, 0, 2, 1, 0, 3, 1), {}),
    ("pos_7_too_many", (DATA, 0, 2, 1, 0, 3, 1, 0), {}),
    ("pos_and_kw_dup", (DATA, 0), dict(verbose=0)),
    ("no_args", (), {}),
    ("bad_kw", (SMALL,), dict(foo=1)),
    ("kw_s", (), dict(s=SMALL)),
    ("gzip_true", (SMALL,), dict(gzip_mode=True)),
    ("gzip_2", (SMALL,), dict(gzip_mode=2)),
    ("index_obj", (DATA,), dict(numiterations=Index3())),
    ("bool_iter", (DATA,), dict(numiterations=True)),
    ("int_input", (5,), {}),
    ("none_input", (None,), {}),
    ("list_input", ([1, 2, 3],), {}),
    ("float_iter", (SMALL,), dict(numiterations=1.5)),
    ("str_iter", (SMALL,), dict(numiterations="1")),
    ("none_iter", (SMALL,), dict(numiterations=None)),
    ("float_gzip", (SMALL,), dict(gzip_mode=1.0)),
    ("none_gzip", (SMALL,), dict(gzip_mode=None)),
    ("overflow_iter", (SMALL,), dict(numiterations=2 ** 31)),
    ("overflow_iter_neg", (SMALL,), dict(numiterations=-2 ** 31 - 1)),
    ("overflow_bsmax", (SMALL,), dict(blocksplittingmax=2 ** 31)),
    ("overflow_gzip", (SMALL,), dict(gzip_mode=2 ** 31)),
    ("overflow_gzip64", (SMALL,), dict(gzip_mode=2 ** 64)),
    ("overflow_verbose", (SMALL,), dict(verbose=2 ** 31)),
    ("overflow_blocksplitting", (SMALL,), dict(blocksplitting=2 ** 63)),
    ("zero_iter", (DATA,), dict(numiterations=0)),
    ("neg_iter", (DATA,), dict(numiterations=-5)),
    ("neg_bsmax", (DATA,), dict(blocksplittingmax=-1, numiterations=1)),
    ("surrogate_str", ("\udc80",), {}),
    ("array_input", (array.array("H", [1, 2, 3]),), {}),
]


@pytest.mark.parametrize("name,args,kwargs", CALLS, ids=[c[0] for c in CALLS])
def test_matches_oracle(name, args, kwargs):
    f = compress_fn()
    got = outcome(f, args, kwargs)
    want = outcome(zopfli_oracle.compress, args, kwargs)
    if want[0] == "exc":
        assert got[0] == "exc", "oracle raises %s, port returned %r" % (
            want[1].__name__, got[1][:20])
        assert issubclass(got[1], want[1]) or got[1] is want[1], \
            "oracle raises %s, port raises %s" % (want[1].__name__,
                                                  got[1].__name__)
    else:
        assert got[0] == "ok", "oracle returns, port raises %s" % (
            got[1].__name__,)
        assert type(got[1]) is bytes
        assert got[1] == want[1]


@pytest.mark.parametrize("make", [bytearray, memoryview,
                                  lambda b: memoryview(bytearray(b))],
                         ids=["bytearray", "memoryview", "memoryview_rw"])
def test_bytes_like_extension(make):
    f = compress_fn()
    r = f(make(DATA), numiterations=2)
    assert type(r) is bytes
    assert r == zopfli_oracle.compress(DATA, numiterations=2)


def test_noncontiguous_memoryview():
    """Either rejected, or compressed as its bytes."""
    f = compress_fn()
    mv = memoryview(DATA)[::2]
    try:
        r = f(mv, numiterations=1)
    except (TypeError, ValueError, BufferError):
        return
    assert r == zopfli_oracle.compress(mv.tobytes(), numiterations=1)


def test_defaults():
    import inspect
    f = compress_fn()
    try:
        sig = inspect.signature(f)
    except (TypeError, ValueError):
        pytest.skip("no signature")
    defaults = {k: p.default for k, p in sig.parameters.items()
                if p.default is not inspect.Parameter.empty}
    assert defaults == dict(verbose=0, numiterations=15, blocksplitting=1,
                            blocksplittinglast=0, blocksplittingmax=15,
                            gzip_mode=0)
    assert f(SMALL) == f(SMALL, verbose=0, numiterations=15, blocksplitting=1,
                         blocksplittinglast=0, blocksplittingmax=15,
                         gzip_mode=0)


def test_does_not_mutate_input():
    f = compress_fn()
    ba = bytearray(DATA)
    f(ba, numiterations=1)
    assert ba == bytearray(DATA)


def test_verbose_writes_stderr(capfd):
    """verbose=1 prints to stderr (same text as C); stdout stays clean."""
    f = compress_fn()
    r = f(DATA, numiterations=2, verbose=1)
    out, err = capfd.readouterr()
    assert out == ""
    assert r == zopfli_oracle.compress(DATA, numiterations=2)
    zopfli_oracle.compress(DATA, numiterations=2, verbose=1)
    out2, err2 = capfd.readouterr()
    assert err == err2
