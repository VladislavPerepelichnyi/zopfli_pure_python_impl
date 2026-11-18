"""Port of util.h / util.c and the public part of zopfli.h.

Only the constants and the options struct live here. The configuration
``#define``s of util.h (ZOPFLI_LONGEST_MATCH_CACHE, ZOPFLI_HASH_SAME,
ZOPFLI_HASH_SAME_HASH, ZOPFLI_SHORTCUT_LONG_REPETITIONS, ZOPFLI_LAZY_MATCHING)
are all on in the reference build; the port implements only those code paths,
so they are not represented as flags. ``ZOPFLI_APPEND_DATA`` becomes
``list.append``.
"""

# Minimum and maximum length that can be encoded in deflate.
ZOPFLI_MAX_MATCH = 258
ZOPFLI_MIN_MATCH = 3

# Number of distinct literal/length and distance symbols in DEFLATE.
ZOPFLI_NUM_LL = 288
ZOPFLI_NUM_D = 32

# The window size for deflate. Must be a power of two.
ZOPFLI_WINDOW_SIZE = 32768
# The window mask used to wrap indices into the window.
ZOPFLI_WINDOW_MASK = ZOPFLI_WINDOW_SIZE - 1

# Huge, non-smart blocks the input is divided into (0 disables them).
ZOPFLI_MASTER_BLOCK_SIZE = 1000000

# Used to initialize costs for example.
ZOPFLI_LARGE_FLOAT = 1e30

# For the longest match cache: entries per position (3 bytes each).
ZOPFLI_CACHE_LENGTH = 8

# Limit of the hash chain hits for a hash value.
ZOPFLI_MAX_CHAIN_HITS = 8192

# ZopfliFormat (zopfli.h).
ZOPFLI_FORMAT_GZIP = 0
ZOPFLI_FORMAT_ZLIB = 1
ZOPFLI_FORMAT_DEFLATE = 2


class Options(object):
    """Port of ZopfliOptions (zopfli.h) with ZopfliInitOptions defaults (util.c)."""

    verbose = 0
    verbose_more = 0
    numiterations = 15
    blocksplitting = 1
    blocksplittinglast = 0
    blocksplittingmax = 15

    def __init__(self, verbose=0, verbose_more=0, numiterations=15,
                 blocksplitting=1, blocksplittinglast=0, blocksplittingmax=15):
        # Whether to print output.
        self.verbose = verbose
        # Whether to print more detailed output.
        self.verbose_more = verbose_more
        # Maximum amount of times to rerun forward and backward pass to
        # optimize LZ77 compression cost.
        self.numiterations = numiterations
        # If true, splits the data in multiple deflate blocks.
        self.blocksplitting = blocksplitting
        # No longer used, left for compatibility.
        self.blocksplittinglast = blocksplittinglast
        # Maximum amount of blocks to split into (0 for unlimited).
        self.blocksplittingmax = blocksplittingmax

    def __repr__(self):
        return ("Options(verbose=%d, verbose_more=%d, numiterations=%d, "
                "blocksplitting=%d, blocksplittinglast=%d, blocksplittingmax=%d)"
                % (self.verbose, self.verbose_more, self.numiterations,
                   self.blocksplitting, self.blocksplittinglast,
                   self.blocksplittingmax))


def init_options(options):
    """Port of ZopfliInitOptions (util.c). Resets ``options`` to the defaults."""
    options.verbose = 0
    options.verbose_more = 0
    options.numiterations = 15
    options.blocksplitting = 1
    options.blocksplittinglast = 0
    options.blocksplittingmax = 15
