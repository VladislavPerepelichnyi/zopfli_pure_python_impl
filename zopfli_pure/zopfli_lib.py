"""Port of zopfli_lib.c (ZopfliCompress)."""

from .util import ZOPFLI_FORMAT_GZIP, ZOPFLI_FORMAT_ZLIB, ZOPFLI_FORMAT_DEFLATE
from .bitwriter import BitWriter
from . import deflate as _deflate
from .gzip_container import gzip_compress
from .zlib_container import zlib_compress


def compress_format(options, output_type, in_):
    """Port of ZopfliCompress (zopfli_lib.c). Returns the compressed bytes."""
    if output_type == ZOPFLI_FORMAT_GZIP:
        return gzip_compress(options, in_)
    elif output_type == ZOPFLI_FORMAT_ZLIB:
        return zlib_compress(options, in_)
    elif output_type == ZOPFLI_FORMAT_DEFLATE:
        w = BitWriter(bytearray(), 0)
        _deflate.deflate(options, 2, 1, in_, len(in_), w)  # Dynamic block
        return bytes(w.out)
    else:
        raise AssertionError("unknown output_type %r" % (output_type,))
