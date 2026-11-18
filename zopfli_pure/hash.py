"""Port of hash.c: the sliding hash used by the LZ77 match finder.

Built with ZOPFLI_HASH_SAME and ZOPFLI_HASH_SAME_HASH on, so the struct has the
second hash chain (head2/prev2/hashval2/val2) and the ``same`` array.

C storage types and how the port keeps them exact:

* ``head``/``head2``/``hashval``/``hashval2`` are ``int``; every stored value
  is -1 or in [0, 32767], so plain Python ints are exact.
* ``prev``/``prev2`` are ``unsigned short``; stored values are window indices
  (< 32768), so no truncation can happen.
* ``same`` is ``unsigned short``; ``ZopfliUpdateHash`` caps ``amount`` at
  ``(unsigned short)(-1)`` = 65535 before storing it, so no truncation either.
* ``val2 = ((same - ZOPFLI_MIN_MATCH) & 255) ^ val`` is computed in ``int``
  (``same`` is promoted); Python's ``&`` on a negative int behaves like two's
  complement, so ``same < 3`` gives the same value as in C.
"""

from .util import ZOPFLI_MIN_MATCH, ZOPFLI_WINDOW_MASK

HASH_SHIFT = 5
HASH_MASK = 32767


class Hash(object):
    """Port of ZopfliHash (hash.h).

    The constructor does ZopfliAllocHash followed by ZopfliResetHash (the C
    code always resets before first use; allocating already reset memory is
    harmless).
    """

    __slots__ = ("head", "prev", "hashval", "val",
                 "head2", "prev2", "hashval2", "val2", "same")

    def __init__(self, window_size):
        self.head = None      # Hash value to index of its most recent occurrence.
        self.prev = None      # Index to index of prev. occurrence of same hash.
        self.hashval = None   # Index to hash value at this index.
        self.val = 0          # Current hash value.
        self.head2 = None
        self.prev2 = None
        self.hashval2 = None
        self.val2 = 0
        self.same = None      # Amount of repetitions of same byte after this.
        # ZopfliAllocHash only allocates; users call ZopfliResetHash themselves
        # (Greedy, GetBestLengths, FollowPath), so no reset here.
        alloc_hash(window_size, self)


def alloc_hash(window_size, h):
    """Port of ZopfliAllocHash (hash.c). Allocates the arrays (zero-filled)."""
    h.head = [0] * 65536
    h.prev = [0] * window_size
    h.hashval = [0] * window_size
    h.same = [0] * window_size
    h.head2 = [0] * 65536
    h.prev2 = [0] * window_size
    h.hashval2 = [0] * window_size


def reset_hash(window_size, h):
    """Port of ZopfliResetHash (hash.c).

    Rebuilds every array, which both allocates (if needed) and resets them.
    """
    h.val = 0
    h.head = [-1] * 65536  # -1 indicates no head so far.
    # If prev[j] == j, then prev[j] is uninitialized.
    h.prev = list(range(window_size))
    h.hashval = [-1] * window_size

    h.same = [0] * window_size

    h.val2 = 0
    h.head2 = [-1] * 65536
    h.prev2 = list(range(window_size))
    h.hashval2 = [-1] * window_size


def clean_hash(h):
    """Port of ZopfliCleanHash (hash.c). Drops the arrays."""
    h.head = h.prev = h.hashval = None
    h.head2 = h.prev2 = h.hashval2 = None
    h.same = None


def update_hash_value(h, c):
    """Port of UpdateHashValue (hash.c, static)."""
    h.val = ((h.val << HASH_SHIFT) ^ c) & HASH_MASK


def update_hash(array, pos, end, h):
    """Port of ZopfliUpdateHash (hash.c).

    Updates the hash values based on the current position in the array. All
    calls to this must be made for consecutive bytes.
    """
    hpos = pos & ZOPFLI_WINDOW_MASK

    # UpdateHashValue, inlined.
    val = ((h.val << HASH_SHIFT)
           ^ (array[pos + 2] if pos + ZOPFLI_MIN_MATCH <= end else 0)) & HASH_MASK
    h.val = val
    hashval = h.hashval
    head = h.head
    hashval[hpos] = val
    hh = head[val]
    if hh != -1 and hashval[hh] == val:
        h.prev[hpos] = hh
    else:
        h.prev[hpos] = hpos
    head[val] = hpos

    # Update "same".
    same = h.same
    amount = 0
    s = same[(pos - 1) & ZOPFLI_WINDOW_MASK]
    if s > 1:
        amount = s - 1
    c = array[pos]
    while (pos + amount + 1 < end and c == array[pos + amount + 1]
           and amount < 65535):
        amount += 1
    same[hpos] = amount

    # ZOPFLI_HASH_SAME_HASH: the second hash.
    val2 = ((amount - ZOPFLI_MIN_MATCH) & 255) ^ val
    h.val2 = val2
    hashval2 = h.hashval2
    head2 = h.head2
    hashval2[hpos] = val2
    hh = head2[val2]
    if hh != -1 and hashval2[hh] == val2:
        h.prev2[hpos] = hh
    else:
        h.prev2[hpos] = hpos
    head2[val2] = hpos


def warmup_hash(array, pos, end, h):
    """Port of ZopfliWarmupHash (hash.c).

    Fills in the initial values in the hash, before update_hash can be used
    correctly.
    """
    update_hash_value(h, array[pos + 0])
    if pos + 1 < end:
        update_hash_value(h, array[pos + 1])
