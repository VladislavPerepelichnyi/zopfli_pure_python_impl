# Upstream findings

Bugs and questionable behaviour found in the reference C implementation
(google/zopfli @ df1517dd, = zopfli-1.0.3) while porting it.

Format of each entry: number, `file:line`, description, whether it affects output,
and how the Python port handles it (the port reproduces upstream output unless stated).


## Findings from the lz77 / hash / cache port (branch `lz77`)

(Numbers may need renumbering when branches are merged.)

### 1. `lz77.c:363` — distance read from a stale `sublen[0]` on a "no match" cache hit

In `TryGetFromLongestMatchCache`, a cache entry with `length == 0` (position
known to have no match) is served when `sublen != NULL` by
`ZopfliCacheToSublen(..., 0, sublen)` (which returns immediately because
`length < 3`) followed by `*distance = sublen[*length]`, i.e. `sublen[0]`.
That element is whatever the caller's buffer held: in `ZopfliLZ77Greedy`
(`dummysublen`) and `GetBestLengths` (`sublen`) it is an uninitialized stack
array, so the returned distance is indeterminate.
**Output:** not affected. Greedy only feeds it into
`GetLengthScore(0, dist)`, which is 0 or -1, both below `ZOPFLI_MIN_MATCH`;
`GetBestLengths` only uses `sublen[k]` for `3 <= k <= leng`.
**Port:** reproduces the read (`distance = sublen[length]`); the Python
buffers are zero-initialized, so the port returns 0 or the stale value of its
own buffer. The C harness uses the same zero-initialized, reused buffer on
both sides, so results compare equal.

### 2. `lz77.c:471` — `if (dist > 0)` in `ZopfliFindLongestMatch` is always true

`dist` starts as `pp - p` (with `p < pp`) or `ZOPFLI_WINDOW_SIZE - p + pp`
(with `p > pp`; `p == pp` gives 32768 and the loop does not run) and only
grows, so it is always >= 1 inside the loop. Dead check.
**Output:** none. **Port:** kept for fidelity.

### 3. `cache.c:91-102` — `ZopfliCacheToSublen` ignores its `length` argument

Apart from the `length < 3` early return, the parameter is shadowed by the
loop-local `unsigned length` and the function always fills
`sublen[0 .. ZopfliMaxCachedSublen()]`, also when the caller (the cache path in
`TryGetFromLongestMatchCache`) asked for a shorter, limit-truncated length.
It also writes `sublen[0..2]`.
**Output:** none (callers only read up to the requested length).
**Port:** reproduces the full fill.

### 4. `lz77.c:297-331` — `GetMatch` type-punned 8-byte loads; `arrayend_safe` before the array

`*((size_t*)scan) == *((size_t*)match)` is an unaligned, strict-aliasing
violating load (py-zopfli's bundled copy replaces it with `memcpy`). In
`ZopfliFindLongestMatch`, `arrayend_safe = arrayend - 8` points before the
start of `array` when `pos + limit < 8`, which is undefined pointer
arithmetic (never dereferenced, since `scan < safe_end` is then false).
**Output:** none in practice. **Port:** compares bytes/slices; the resulting
match length is identical.

### 5. `lz77.c:160-166` — `ZopfliLZ77GetByteRange` wraps if positions decrease

`pos[lend-1] + len - pos[lstart]` is `size_t`; it would wrap if a store held
non-monotonic positions. Every store built by zopfli has increasing absolute
positions (also after `ZopfliAppendLZ77Store` across master blocks), so the
wrap is unreachable. **Port:** no masking (per the spec, only reachable wraps
are reproduced).

### 6. Comments that do not match the code

* `lz77.c:288-296`: `GetMatch` "Returns the last byte after scan, which is
  still equal" — it returns the first position that differs (or `end`).
* `lz77.c:94-97`: `ZopfliStoreLitLenDist` "context must be a
  ZopfliLZ77Store*" — there is no `context` parameter (left over from a
  callback-based API).
* `lz77.c:422`: `unsigned dist = 0; /* Not unsigned short on purpose. */` but
  `bestdist`, the output and the sublen entries are `unsigned short`; this is
  fine because `dist < ZOPFLI_WINDOW_SIZE` whenever it is stored.

**Output:** none.
