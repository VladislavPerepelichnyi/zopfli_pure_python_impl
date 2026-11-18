"""Round-trip tests: the output of zopfli_pure decompresses to the input.

These need no oracle, so they also catch problems in configurations where
py-zopfli is unavailable. zlib mode is checked with zlib.decompress, gzip mode
with gzip.decompress, raw deflate (compress_format(..., 2, ...)) with
zlib.decompress(..., -15).
"""

import gzip
import zlib

import pytest

import corpus
from port import compress, compress_format

FORMAT_GZIP, FORMAT_ZLIB, FORMAT_DEFLATE = 0, 1, 2


@pytest.mark.parametrize("case", corpus.params("tiny"))
@pytest.mark.parametrize("gzip_mode", [0, 1])
def test_roundtrip_tiny(case, gzip_mode):
    out = compress(case.data, gzip_mode=gzip_mode)
    if gzip_mode:
        assert gzip.decompress(out) == case.data
    else:
        assert zlib.decompress(out) == case.data


@pytest.mark.parametrize("case", corpus.params("small", "medium"))
def test_roundtrip_1_iteration(case):
    out = compress(case.data, numiterations=1)
    assert zlib.decompress(out) == case.data


@pytest.mark.parametrize("case", corpus.params("tiny", "small"))
def test_roundtrip_gzip_2_iterations(case):
    out = compress(case.data, numiterations=2, gzip_mode=1)
    assert gzip.decompress(out) == case.data


@pytest.mark.parametrize("case", corpus.params("large"))
def test_roundtrip_large(case):
    out = compress(case.data, numiterations=15)
    assert zlib.decompress(out) == case.data


@pytest.mark.parametrize("opts", [
    dict(numiterations=1, blocksplitting=0),
    dict(numiterations=2, blocksplittingmax=0),
    dict(numiterations=2, blocksplittingmax=1),
    dict(numiterations=5, blocksplittingmax=3),
    dict(numiterations=1, blocksplittinglast=1),
], ids=lambda o: ",".join("%s=%s" % kv for kv in sorted(o.items())))
@pytest.mark.parametrize("name", ["dna_then_text", "gettysburg",
                                  "all_bytes_x4"])
def test_roundtrip_options(name, opts):
    data = corpus.get(name).data
    assert zlib.decompress(compress(data, **opts)) == data
    assert gzip.decompress(compress(data, gzip_mode=1, **opts)) == data


@pytest.mark.parametrize("case", corpus.params("tiny") + [
    pytest.param(corpus.get(n), id=n) for n in ("text_1k", "random_4000",
                                                "src_then_random")])
def test_roundtrip_formats(case):
    data = case.data
    raw = compress_format(FORMAT_DEFLATE, data, numiterations=2)
    assert zlib.decompress(bytes(raw), -15) == data
    z = compress_format(FORMAT_ZLIB, data, numiterations=2)
    assert zlib.decompress(bytes(z)) == data
    assert bytes(z)[2:-4] == bytes(raw)
    g = compress_format(FORMAT_GZIP, data, numiterations=2)
    assert gzip.decompress(bytes(g)) == data


def test_roundtrip_str():
    text = "héllo wörld € \U0001F600 " * 30
    assert zlib.decompress(compress(text, numiterations=2)).decode("utf-8") == text


def test_zlib_header_and_adler():
    data = corpus.get("text_1k").data
    out = compress(data, numiterations=1)
    assert out[:2] == b"\x78\xda"
    assert int.from_bytes(out[-4:], "big") == zlib.adler32(data)


def test_gzip_header_and_trailer():
    data = corpus.get("text_1k").data
    out = compress(data, numiterations=1, gzip_mode=1)
    assert out[:10] == b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\x03"
    assert int.from_bytes(out[-8:-4], "little") == zlib.crc32(data)
    assert int.from_bytes(out[-4:], "little") == len(data) & 0xFFFFFFFF


try:
    from hypothesis import given, strategies as st
except ImportError:  # pragma: no cover
    given = None

if given is not None:
    @given(data=st.binary(max_size=400),
           numiterations=st.sampled_from([1, 2, 3]),
           blocksplitting=st.sampled_from([0, 1]),
           gzip_mode=st.sampled_from([0, 1]))
    def test_property_roundtrip(data, numiterations, blocksplitting, gzip_mode):
        out = compress(data, numiterations=numiterations,
                       blocksplitting=blocksplitting, gzip_mode=gzip_mode)
        if gzip_mode:
            assert gzip.decompress(out) == data
        else:
            assert zlib.decompress(out) == data
