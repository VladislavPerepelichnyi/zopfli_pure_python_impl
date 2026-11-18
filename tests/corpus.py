"""Deterministic named test inputs for the zopfli_pure test suite.

Every input is generated from a fixed seed (or read from the reference source
tree), so test ids and expected outputs are stable across runs and machines.
Nothing is downloaded.

Each :class:`Case` has a ``name``, a ``size`` class and lazily built ``data``:

* ``tiny``    <= 300 bytes
* ``small``   <= ~6 KB          (default runs, all option combinations)
* ``medium``  <= ~40 KB         (default runs, few option combinations)
* ``large``   > 40 KB           (marked slow: only with ZOPFLI_PURE_SLOW=1)

Pure Python is roughly 100x slower than C, so tests pick from these classes
with :func:`cases` (e.g. ``cases("tiny", "small")``) and use
:func:`params` to get ``pytest.param`` objects with the right marks/ids.
"""

import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)

SIZE_CLASSES = ("tiny", "small", "medium", "large")


# --------------------------------------------------------------------- PRNG

class Rng(object):
    """Small deterministic PRNG (xorshift64*), independent of `random`'s
    implementation details so the corpus never changes between Python
    versions."""

    def __init__(self, seed):
        self.s = (seed * 0x9E3779B97F4A7C15 + 0x632BE59BD9B4E019) \
            & 0xFFFFFFFFFFFFFFFF or 1

    def next(self):
        x = self.s
        x ^= (x >> 12)
        x ^= (x << 25) & 0xFFFFFFFFFFFFFFFF
        x ^= (x >> 27)
        self.s = x
        return (x * 0x2545F4914F6CDD1D) & 0xFFFFFFFFFFFFFFFF

    def below(self, n):
        return (self.next() >> 11) % n

    def bytes(self, n):
        out = bytearray(n)
        for i in range(n):
            out[i] = self.next() >> 56
        return bytes(out)

    def choice(self, seq):
        return seq[self.below(len(seq))]


# ---------------------------------------------------------------- generators

def random_bytes(n, seed=1):
    return Rng(seed).bytes(n)


def run(n, byte=0x61):
    return bytes([byte]) * n


def periodic(period, n, seed=None):
    """n bytes repeating a pseudo-random pattern of the given period."""
    pat = Rng(1000 + period if seed is None else seed).bytes(period)
    reps = n // period + 1
    return (pat * reps)[:n]


_WORDS = (
    "the of and to in is was that for it with as his on be at by had are but "
    "from or have an they which one you were her all she there would their we "
    "him been has when who will more no if out so said what up its about into "
    "than them can only other new some could time these two may then do first "
    "any my now such like our over man me even most made after also did many "
    "before must through back years where much your way well down should "
    "because each just those people how too little state good very make world "
    "still own see men work long get here between both life being under never "
    "day same another know while last might us great old year off come since "
    "against go came right used take three compression huffman deflate block "
    "window match length distance literal symbol tree iteration squeeze"
).split()


def pseudo_text(n, seed=7):
    """Deterministic English-like text: sentences of common words."""
    r = Rng(seed)
    out = []
    size = 0
    while size < n:
        k = 4 + r.below(14)
        words = [r.choice(_WORDS) for _ in range(k)]
        s = " ".join(words)
        s = s[0].upper() + s[1:]
        s += r.choice([". ", ". ", ". ", ", ", "? ", "! ", ".\n", ".\n\n"])
        out.append(s)
        size += len(s)
    return "".join(out).encode("ascii")[:n]


# Public domain: Abraham Lincoln, Gettysburg Address (Bliss copy), 1863.
GETTYSBURG = (
    "Four score and seven years ago our fathers brought forth on this "
    "continent, a new nation, conceived in Liberty, and dedicated to the "
    "proposition that all men are created equal.\n\n"
    "Now we are engaged in a great civil war, testing whether that nation, or "
    "any nation so conceived and so dedicated, can long endure. We are met on "
    "a great battle-field of that war. We have come to dedicate a portion of "
    "that field, as a final resting place for those who here gave their lives "
    "that that nation might live. It is altogether fitting and proper that we "
    "should do this.\n\n"
    "But, in a larger sense, we can not dedicate -- we can not consecrate -- "
    "we can not hallow -- this ground. The brave men, living and dead, who "
    "struggled here, have consecrated it, far above our poor power to add or "
    "detract. The world will little note, nor long remember what we say here, "
    "but it can never forget what they did here. It is for us the living, "
    "rather, to be dedicated here to the unfinished work which they who fought "
    "here have thus far so nobly advanced. It is rather for us to be here "
    "dedicated to the great task remaining before us -- that from these "
    "honored dead we take increased devotion to that cause for which they gave "
    "the last full measure of devotion -- that we here highly resolve that "
    "these dead shall not have died in vain -- that this nation, under God, "
    "shall have a new birth of freedom -- and that government of the people, "
    "by the people, for the people, shall not perish from the earth.\n"
).encode("ascii")


def _reference_source(name):
    """Read a file from the reference C tree, or None if unavailable."""
    cands = []
    env = os.environ.get("ZOPFLI_REFERENCE_DIR")
    if env:
        cands += [os.path.join(env, "src", "zopfli", name), os.path.join(env, name)]
    d = _REPO
    while True:
        cands.append(os.path.join(d, "zopfli_reference", "src", "zopfli", name))
        p = os.path.dirname(d)
        if p == d:
            break
        d = p
    for c in cands:
        if os.path.isfile(c):
            with open(c, "rb") as f:
                return f.read()
    return None


def source_code(name="deflate.c"):
    """A C source file from the reference tree (falls back to this file)."""
    data = _reference_source(name)
    if data is None:
        with open(os.path.abspath(__file__), "rb") as f:
            data = f.read()
    return data


def mixed_text_binary(n, seed=11):
    """Alternating chunks of text and random/structured binary."""
    r = Rng(seed)
    out = bytearray()
    i = 0
    while len(out) < n:
        k = 50 + r.below(400)
        kind = i % 3
        if kind == 0:
            out += pseudo_text(k, seed=seed + i)
        elif kind == 1:
            out += r.bytes(k)
        else:
            # little-endian increasing 32-bit integers (structured binary)
            base = r.below(1 << 20)
            for j in range(k // 4):
                v = base + 3 * j
                out += bytes((v & 255, (v >> 8) & 255, (v >> 16) & 255, v >> 24))
        i += 1
    return bytes(out[:n])


def multi_block(n, seed=21):
    """Segments with very different statistics, so block splitting splits."""
    r = Rng(seed)
    segs = []
    size = 0
    i = 0
    while size < n:
        k = n // 6 + r.below(n // 6 + 1)
        kind = i % 4
        if kind == 0:
            s = pseudo_text(k, seed=seed + i)
        elif kind == 1:
            s = bytes(r.choice(b"ACGT") for _ in range(k))
        elif kind == 2:
            s = r.bytes(k)
        else:
            s = periodic(1 + r.below(40), k, seed=seed + i)
        segs.append(s)
        size += len(s)
        i += 1
    return b"".join(segs)[:n]


def dna(n, seed=5):
    r = Rng(seed)
    return bytes(r.choice(b"ACGT") for _ in range(n))


def sparse(n, seed=9, density=50):
    """Mostly zeros with a few random bytes (1 in `density`)."""
    r = Rng(seed)
    out = bytearray(n)
    for i in range(n):
        if r.below(density) == 0:
            out[i] = 1 + r.below(255)
    return bytes(out)


def text_near(n, seed=3):
    """Text-like data of exactly n bytes (for window/size boundaries)."""
    return pseudo_text(n, seed=seed)


# ---------------------------------------------------------------------- cases

class Case(object):
    __slots__ = ("name", "size", "_fn", "_data")

    def __init__(self, name, size, fn):
        assert size in SIZE_CLASSES, size
        self.name = name
        self.size = size
        self._fn = fn
        self._data = None

    @property
    def data(self):
        if self._data is None:
            d = self._fn()
            self._data = bytes(d)
        return self._data

    def __repr__(self):
        return "Case(%r, %r)" % (self.name, self.size)


CASES = []


def _add(name, size, fn):
    CASES.append(Case(name, size, fn))


# tiny
_add("empty", "tiny", lambda: b"")
for _b in (0x00, 0x01, 0x41, 0x7f, 0x80, 0xff):
    _add("byte_%02x" % _b, "tiny", (lambda b=_b: bytes([b])))
_add("two_ab", "tiny", lambda: b"ab")
_add("two_aa", "tiny", lambda: b"aa")
_add("three_abc", "tiny", lambda: b"abc")
_add("three_aaa", "tiny", lambda: b"aaa")
_add("four_aaaa", "tiny", lambda: b"aaaa")
_add("abab_7", "tiny", lambda: b"abababa")
_add("all_bytes", "tiny", lambda: bytes(range(256)))
_add("all_bytes_rev", "tiny", lambda: bytes(range(255, -1, -1)))
_add("run_3", "tiny", lambda: run(3))
_add("run_10", "tiny", lambda: run(10))
_add("run_258", "tiny", lambda: run(258))
_add("run_259", "tiny", lambda: run(259, 0))
_add("run_260", "tiny", lambda: run(260, 0xff))
_add("hello", "tiny", lambda: b"Hello, World!\n")
_add("random_100", "tiny", lambda: random_bytes(100, seed=100))
_add("text_200", "tiny", lambda: pseudo_text(200, seed=200))
for _p in (1, 2, 3, 7, 13):
    _add("periodic_%d_n120" % _p, "tiny", (lambda p=_p: periodic(p, 120)))

# small
_add("run_1000", "small", lambda: run(1000))
_add("run_516", "small", lambda: run(516, 7))   # 2 * 258
_add("run_517", "small", lambda: run(517, 7))
_add("all_bytes_x4", "small", lambda: bytes(range(256)) * 4)
_add("gettysburg", "small", lambda: GETTYSBURG)
_add("text_1k", "small", lambda: pseudo_text(1024, seed=1))
_add("text_5k", "small", lambda: pseudo_text(5000, seed=2))
_add("random_1000", "small", lambda: random_bytes(1000, seed=1000))
_add("random_4000", "small", lambda: random_bytes(4000, seed=4000))
_add("source_4k", "small", lambda: source_code("deflate.c")[:4096])
_add("source_tree_c", "small", lambda: source_code("tree.c"))
_add("mixed_3k", "small", lambda: mixed_text_binary(3000))
_add("multi_block_6k", "small", lambda: multi_block(6000))
_add("dna_3k", "small", lambda: dna(3000))
_add("sparse_4k", "small", lambda: sparse(4096))
_add("run_then_text", "small", lambda: run(600, 0x20) + pseudo_text(1500, 4) + run(300, 0))
for _p in (4, 5, 8, 16, 31, 32, 64, 100, 127, 128, 255, 256, 257, 258, 259,
           260, 299, 300):
    _add("periodic_%d" % _p, "small", (lambda p=_p: periodic(p, max(600, 3 * p + 17))))

# medium
_add("text_20k", "medium", lambda: pseudo_text(20000, seed=20))
_add("source_deflate_c", "medium", lambda: source_code("deflate.c"))
_add("source_lz77_c", "medium", lambda: source_code("lz77.c"))
_add("random_20k", "medium", lambda: random_bytes(20000, seed=20000))
_add("mixed_20k", "medium", lambda: mixed_text_binary(20000, seed=12))
_add("multi_block_24k", "medium", lambda: multi_block(24000, seed=22))
_add("run_40000", "medium", lambda: run(40000))
_add("periodic_300_20k", "medium", lambda: periodic(300, 20000))

# large (slow)
_add("text_32767", "large", lambda: text_near(32767))
_add("text_32768", "large", lambda: text_near(32768))
_add("text_32769", "large", lambda: text_near(32769))
_add("text_33000", "large", lambda: text_near(33000))
_add("mixed_65535", "large", lambda: mixed_text_binary(65535, seed=13))
_add("mixed_65536", "large", lambda: mixed_text_binary(65536, seed=13))
_add("mixed_65537", "large", lambda: mixed_text_binary(65537, seed=13))
_add("text_100k", "large", lambda: pseudo_text(100000, seed=100))
_add("multi_block_120k", "large", lambda: multi_block(120000, seed=23))
_add("random_70k", "large", lambda: random_bytes(70000, seed=70000))
_add("all_source", "large", lambda: b"".join(
    source_code(n) for n in ("blocksplitter.c", "cache.c", "deflate.c",
                             "hash.c", "katajainen.c", "lz77.c", "squeeze.c",
                             "tree.c")))

BY_NAME = dict((c.name, c) for c in CASES)
assert len(BY_NAME) == len(CASES), "duplicate case names"


def get(name):
    return BY_NAME[name]


def cases(*sizes):
    """Cases whose size class is in `sizes` (all if none given)."""
    if not sizes:
        return list(CASES)
    for s in sizes:
        assert s in SIZE_CLASSES, s
    return [c for c in CASES if c.size in sizes]


def params(*sizes, **kw):
    """pytest.param(case, id=name), with the `slow` mark on large cases.

    Extra keyword `extra_marks` adds marks to every param.
    """
    import pytest
    extra = kw.pop("extra_marks", ())
    assert not kw
    out = []
    for c in cases(*sizes):
        marks = list(extra)
        if c.size == "large":
            marks.append(pytest.mark.slow)
        out.append(pytest.param(c, id=c.name, marks=marks))
    return out


def all_periods_params(length_fn=lambda p: 3 * p + 17):
    """Periodic inputs for every period 1..300 (marked slow)."""
    import pytest
    return [pytest.param(periodic(p, length_fn(p)), id="period_%d" % p,
                         marks=[pytest.mark.slow]) for p in range(1, 301)]
