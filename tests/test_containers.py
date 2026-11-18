"""Tests for zlib_container.py, gzip_container.py, zopfli_lib.py and compress()."""
import ast
import os
import random
import subprocess
import sys
import zlib

import pytest

from _deflate_harness import HARNESS, ROOT, checks, need_c, need_oracle, need_package

MY_MODULES = ("deflate.py", "zlib_container.py", "gzip_container.py",
              "zopfli_lib.py", "__init__.py")
ALLOWED = {"math", "array", "sys", "struct"}


@pytest.mark.parametrize("fname", MY_MODULES)
def test_pure_python_imports(fname):
    path = os.path.join(ROOT, "zopfli_pure", fname)
    tree = ast.parse(open(path).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.split(".")[0] in ALLOWED, a.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            assert node.module.split(".")[0] in ALLOWED, node.module


def _containers():
    """Imports the containers; they only need deflate's import chain."""
    need_package()
    from zopfli_pure import gzip_container, zlib_container
    return zlib_container, gzip_container


def test_adler32_and_crc_against_stdlib():
    zc, gc = _containers()
    rnd = random.Random(3)
    for n in (0, 1, 5549, 5550, 5551, 5552, 5553, 65535, 65536, 70000):
        data = bytes(rnd.randrange(256) for _ in range(n))
        assert zc.adler32(data, n) == zlib.adler32(data)
        assert gc.crc(data, n) == zlib.crc32(data)
        ff = b"\xff" * n
        assert zc.adler32(ff, n) == zlib.adler32(ff)


@pytest.mark.oracle
def test_adler32_crc_against_c():
    c = checks()
    c.check_checksums(10)
    assert c.counts["adler32"] == c.counts["crc32"] > 60


def test_headers_and_trailers():
    need_package()
    import zopfli_pure
    data = b"hello zopfli " * 5
    z = zopfli_pure.compress(data)
    assert z[:2] == b"\x78\xda"
    assert z[-4:] == zlib.adler32(data).to_bytes(4, "big")
    g = zopfli_pure.compress(data, gzip_mode=1)
    assert g[:10] == bytes([31, 139, 8, 0, 0, 0, 0, 0, 2, 3])
    assert g[-8:-4] == zlib.crc32(data).to_bytes(4, "little")
    assert g[-4:] == len(data).to_bytes(4, "little")
    assert z[2:-4] == g[10:-8]


@pytest.mark.oracle
def test_compress_format_deflate_against_c():
    need_c()
    c = checks()
    from zopfli_pure.util import ZOPFLI_FORMAT_DEFLATE, ZOPFLI_FORMAT_GZIP, ZOPFLI_FORMAT_ZLIB
    for data in (b"", b"q", b"abcabcabcabd" * 20):
        o = c.Options(numiterations=3)
        for fmt in (ZOPFLI_FORMAT_GZIP, ZOPFLI_FORMAT_ZLIB, ZOPFLI_FORMAT_DEFLATE):
            got = c.zopfli_lib.compress_format(o, fmt, data)
            assert got == c.cref.compress(o, fmt, data)
        assert zlib.decompress(c.zopfli_lib.compress_format(o, ZOPFLI_FORMAT_DEFLATE,
                                                            data), -15) == data


@pytest.mark.oracle
def test_input_types_match_oracle():
    need_oracle()
    need_package()
    import zopfli.zopfli
    import zopfli_pure
    text = "héllo wörld € " * 4
    want = zopfli.zopfli.compress(text.encode("utf-8"))
    assert zopfli.zopfli.compress(text) == want
    assert zopfli_pure.compress(text) == want
    raw = text.encode("utf-8")
    assert zopfli_pure.compress(bytearray(raw)) == want
    assert zopfli_pure.compress(memoryview(raw)) == want
    assert zopfli_pure.compress(data=raw, numiterations=15) == want
    # positional options, in py-zopfli's order
    assert zopfli_pure.compress(raw, 0, 3, 1, 0, 15, 1) == \
        zopfli.zopfli.compress(raw, 0, 3, 1, 0, 15, 1)
    assert zopfli_pure.compress(raw, gzip_mode=True) == \
        zopfli.zopfli.compress(raw, gzip_mode=True)


@pytest.mark.oracle
@pytest.mark.parametrize("kwargs", [
    dict(numiterations=1.5), dict(verbose="x"), dict(gzip_mode=2 ** 31),
    dict(blocksplittingmax=-2 ** 31 - 1),
])
def test_bad_arguments_raise_like_oracle(kwargs):
    need_oracle()
    need_package()
    import zopfli.zopfli
    import zopfli_pure
    with pytest.raises(Exception) as want:
        zopfli.zopfli.compress(b"abc", **kwargs)
    with pytest.raises(type(want.value)):
        zopfli_pure.compress(b"abc", **kwargs)


def test_bad_data_type():
    need_package()
    import zopfli_pure
    for bad in (None, 3, 1.0, [1, 2]):
        with pytest.raises(TypeError):
            zopfli_pure.compress(bad)


@pytest.mark.oracle
def test_verbose_output_matches_oracle():
    """stderr of verbose=1 (all modules' messages) equals py-zopfli's."""
    need_oracle()
    c = checks()
    c.check_verbose(big=5000)
