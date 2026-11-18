"""Pure-Python port of Google's Zopfli compressor.

Public API: compress(), a drop-in equivalent of py-zopfli's
zopfli.zopfli.compress (src/zopflimodule.c, py-zopfli 0.4.3).
"""

__all__ = ["compress"]

_INT_MIN = -0x80000000
_INT_MAX = 0x7FFFFFFF


def _as_c_int(value):
    """Converts an argument like PyArg_ParseTuple's "i" format (C int)."""
    if isinstance(value, float):
        raise TypeError("'float' object cannot be interpreted as an integer")
    try:
        index = type(value).__index__
    except AttributeError:
        raise TypeError("'%s' object cannot be interpreted as an integer"
                        % type(value).__name__) from None
    value = index(value)
    if value > _INT_MAX:
        raise OverflowError("signed integer is greater than maximum")
    if value < _INT_MIN:
        raise OverflowError("signed integer is less than minimum")
    return value


def _as_bytes(data):
    """Converts data like the "s#" format: str is UTF-8 encoded.

    "s#" also takes read-only bytes-like objects; writable ones (bytearray,
    writable memoryview, ...) are accepted here as well, a deliberate
    extension.
    """
    if isinstance(data, str):
        return data.encode("utf-8")
    if isinstance(data, bytes):
        return bytes(data)
    try:
        view = memoryview(data)
    except TypeError:
        raise TypeError("argument 1 must be str or bytes-like object, not %s"
                        % type(data).__name__) from None
    return view.tobytes()


def compress(data, verbose=0, numiterations=15, blocksplitting=1,
             blocksplittinglast=0, blocksplittingmax=15, gzip_mode=0):
    """Compresses data with Zopfli into a zlib stream (gzip if gzip_mode).

    Mirrors zopfli_compress in py-zopfli's zopflimodule.c: options start from
    ZopfliInitOptions and are overridden by the keyword arguments, then
    ZopfliCompress is called with ZOPFLI_FORMAT_GZIP or ZOPFLI_FORMAT_ZLIB.
    """
    from .util import Options, ZOPFLI_FORMAT_GZIP, ZOPFLI_FORMAT_ZLIB
    from .zopfli_lib import compress_format

    in_ = _as_bytes(data)
    options = Options()
    options.verbose = _as_c_int(verbose)
    options.numiterations = _as_c_int(numiterations)
    options.blocksplitting = _as_c_int(blocksplitting)
    options.blocksplittinglast = _as_c_int(blocksplittinglast)
    options.blocksplittingmax = _as_c_int(blocksplittingmax)
    gzip_mode = _as_c_int(gzip_mode)

    output_type = ZOPFLI_FORMAT_GZIP if gzip_mode else ZOPFLI_FORMAT_ZLIB
    return compress_format(options, output_type, in_)
