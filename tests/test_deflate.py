"""Tests for zopfli_pure.deflate (port of deflate.c).

Compared against the reference C (unity build in tools/harness/deflate, needs
gcc) and against py-zopfli (the oracle). Each test skips cleanly when gcc, the
oracle, or a dependency module is missing.
"""
import os
import random
import subprocess
import sys
import zlib

import pytest

from _deflate_harness import (HARNESS, ROOT, checks, need_c, need_oracle,
                              need_package)


@pytest.mark.oracle
def test_isolated_against_c_with_standins():
    """deflate.py + containers with every dependency replaced by the C."""
    need_c()
    need_oracle()
    p = subprocess.run([sys.executable, os.path.join(HARNESS, "checks.py"), "--quick"],
                       cwd=ROOT, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout[-3000:] + p.stderr[-3000:]
    assert "ALL OK" in p.stdout


@pytest.mark.oracle
def test_optimize_huffman_for_rle():
    c = checks()
    c.check_optimize(300)
    assert c.counts["optimize_huffman_for_rle"] == 900


@pytest.mark.oracle
def test_encode_tree_all_flag_combinations():
    c = checks()
    c.check_trees(40)
    assert c.counts["encode_tree output"] == 40 * 8


@pytest.mark.oracle
def test_block_sizes():
    c = checks()
    c.check_block_sizes(30)


@pytest.mark.oracle
def test_add_lz77_block_and_auto_type():
    c = checks()
    c.check_add_blocks(30)


@pytest.mark.oracle
def test_non_compressed_blocks():
    c = checks()
    c.check_non_compressed()


@pytest.mark.oracle
def test_end_to_end_small():
    need_oracle()
    c = checks()
    c.check_end_to_end(4)


@pytest.mark.oracle
@pytest.mark.slow
def test_end_to_end_second_split_pass():
    """Mixed data with several blocks, so the second (LZ77) split pass runs."""
    need_oracle()
    c = checks()
    c.check_large([0], base=12000)


ROUNDTRIP = {
    "empty": b"",
    "one_byte": b"x",
    "small_text": b"Zopfli is a compression library programmed in C.\n" * 3,
    "runs": b"a" * 300 + b"b" * 300 + b"\x00" * 1000,
    "random_binary": bytes(random.Random(1).randrange(256) for _ in range(3000)),
}


@pytest.mark.oracle
@pytest.mark.parametrize("name", sorted(ROUNDTRIP))
@pytest.mark.parametrize("gzip_mode", [0, 1])
def test_roundtrip_and_oracle(name, gzip_mode):
    need_oracle()
    need_package()
    import zopfli.zopfli
    import zopfli_pure
    data = ROUNDTRIP[name]
    got = zopfli_pure.compress(data, gzip_mode=gzip_mode)
    assert got == zopfli.zopfli.compress(data, gzip_mode=gzip_mode)
    assert zlib.decompress(got, 31 if gzip_mode else 15) == data


@pytest.mark.oracle
def test_block_type_choice():
    """Incompressible data gives stored blocks, short inputs fixed blocks."""
    need_package()
    from _inflate import block_types
    import zopfli_pure
    raw = ROUNDTRIP["random_binary"]
    stream = zopfli_pure.compress(raw)[2:-4]
    assert set(block_types(stream)) == {0}
    for short in (b"x", b"abc", b"hello hello"):
        assert block_types(zopfli_pure.compress(short)[2:-4]) == [1]
    assert block_types(zopfli_pure.compress(b"")[2:-4]) == [1]
    text = ROUNDTRIP["small_text"] * 40
    assert 2 in block_types(zopfli_pure.compress(text, numiterations=2)[2:-4])


@pytest.mark.oracle
@pytest.mark.parametrize("kw", [
    dict(numiterations=1), dict(numiterations=5, blocksplitting=0),
    dict(blocksplittingmax=1), dict(blocksplittingmax=0, numiterations=2),
    dict(blocksplittinglast=1, numiterations=2),
])
def test_options_match_oracle(kw):
    need_oracle()
    need_package()
    import zopfli.zopfli
    import zopfli_pure
    rnd = random.Random(7)
    data = (b"".join(rnd.choice([b"alpha ", b"beta ", b"gamma ", b"\n"])
                     for _ in range(400))
            + bytes(rnd.randrange(256) for _ in range(800)))
    for gz in (0, 1):
        assert zopfli_pure.compress(data, gzip_mode=gz, **kw) == \
            zopfli.zopfli.compress(data, gzip_mode=gz, **kw)
