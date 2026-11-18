/*
C oracle for zopfli_pure.{hash,cache,lz77,symbols}: a unity build of the
reference hash.c, cache.c, lz77.c and util.c (so the static functions are
reachable), exported as a shared library for ctypes (tests/test_lz77.py).

Build (done automatically by the tests):
  gcc -O1 -g -shared -fPIC -I<ref>/src/zopfli \
      tools/harness/lz77/lz77_harness.c -o tools/build/lz77_harness.so
Asserts stay enabled (no NDEBUG), so any upstream assert failure aborts.
*/
#include "util.c"
#include "hash.c"
#include "cache.c"
#include "lz77.c"

#include <stdint.h>

/* ---- symbols.h ---- */
int hs_dist_extra_bits(int d) { return ZopfliGetDistExtraBits(d); }
int hs_dist_extra_bits_value(int d) { return ZopfliGetDistExtraBitsValue(d); }
int hs_dist_symbol(int d) { return ZopfliGetDistSymbol(d); }
int hs_length_extra_bits(int l) { return ZopfliGetLengthExtraBits(l); }
int hs_length_extra_bits_value(int l) { return ZopfliGetLengthExtraBitsValue(l); }
int hs_length_symbol(int l) { return ZopfliGetLengthSymbol(l); }
int hs_length_symbol_extra_bits(int s) { return ZopfliGetLengthSymbolExtraBits(s); }
int hs_dist_symbol_extra_bits(int s) { return ZopfliGetDistSymbolExtraBits(s); }

/* ---- hash.c ---- */
ZopfliHash* hh_new(void) {
  ZopfliHash* h = (ZopfliHash*)malloc(sizeof(ZopfliHash));
  ZopfliAllocHash(ZOPFLI_WINDOW_SIZE, h);
  ZopfliResetHash(ZOPFLI_WINDOW_SIZE, h);
  return h;
}
void hh_free(ZopfliHash* h) { ZopfliCleanHash(h); free(h); }
void hh_reset(ZopfliHash* h) { ZopfliResetHash(ZOPFLI_WINDOW_SIZE, h); }
void hh_warmup(const unsigned char* a, size_t pos, size_t end, ZopfliHash* h) {
  ZopfliWarmupHash(a, pos, end, h);
}
void hh_update(const unsigned char* a, size_t pos, size_t end, ZopfliHash* h) {
  ZopfliUpdateHash(a, pos, end, h);
}
/* Reset + warmup + update windowstart..instart-1, as greedy/squeeze do. */
void hh_prepare(const unsigned char* in, size_t instart, size_t inend,
                ZopfliHash* h) {
  size_t i;
  size_t windowstart = instart > ZOPFLI_WINDOW_SIZE
      ? instart - ZOPFLI_WINDOW_SIZE : 0;
  ZopfliResetHash(ZOPFLI_WINDOW_SIZE, h);
  ZopfliWarmupHash(in, windowstart, inend, h);
  for (i = windowstart; i < instart; i++) ZopfliUpdateHash(in, i, inend, h);
}
int hh_val(ZopfliHash* h) { return h->val; }
int hh_val2(ZopfliHash* h) { return h->val2; }
int* hh_head(ZopfliHash* h) { return h->head; }
int* hh_head2(ZopfliHash* h) { return h->head2; }
int* hh_hashval(ZopfliHash* h) { return h->hashval; }
int* hh_hashval2(ZopfliHash* h) { return h->hashval2; }
unsigned short* hh_prev(ZopfliHash* h) { return h->prev; }
unsigned short* hh_prev2(ZopfliHash* h) { return h->prev2; }
unsigned short* hh_same(ZopfliHash* h) { return h->same; }

/* ---- lz77.c: block state / longest match ---- */
static ZopfliOptions g_options;

ZopfliBlockState* hb_new(size_t blockstart, size_t blockend, int add_lmc) {
  ZopfliBlockState* s = (ZopfliBlockState*)malloc(sizeof(ZopfliBlockState));
  ZopfliInitOptions(&g_options);
  ZopfliInitBlockState(&g_options, blockstart, blockend, add_lmc, s);
  return s;
}
void hb_free(ZopfliBlockState* s) { ZopfliCleanBlockState(s); free(s); }
int hb_has_lmc(ZopfliBlockState* s) { return s->lmc != 0; }
unsigned short* hb_lmc_length(ZopfliBlockState* s) { return s->lmc->length; }
unsigned short* hb_lmc_dist(ZopfliBlockState* s) { return s->lmc->dist; }
unsigned char* hb_lmc_sublen(ZopfliBlockState* s) { return s->lmc->sublen; }

/* Returns dist | (length << 16). sublen may be NULL. */
uint32_t hb_find(ZopfliBlockState* s, const ZopfliHash* h,
                 const unsigned char* array, size_t pos, size_t size,
                 size_t limit, unsigned short* sublen) {
  unsigned short dist, length;
  ZopfliFindLongestMatch(s, h, array, pos, size, limit, sublen, &dist, &length);
  return (uint32_t)dist | ((uint32_t)length << 16);
}

/* ---- cache.c ---- */
void hc_sublen_to_cache(const unsigned short* sublen, size_t pos,
                        size_t length, ZopfliBlockState* s) {
  ZopfliSublenToCache(sublen, pos, length, s->lmc);
}
void hc_cache_to_sublen(ZopfliBlockState* s, size_t pos, size_t length,
                        unsigned short* sublen) {
  ZopfliCacheToSublen(s->lmc, pos, length, sublen);
}
unsigned hc_max_cached_sublen(ZopfliBlockState* s, size_t pos, size_t length) {
  return ZopfliMaxCachedSublen(s->lmc, pos, length);
}

/* ---- lz77.c: store ---- */
ZopfliLZ77Store* hl_new(const unsigned char* data) {
  ZopfliLZ77Store* st = (ZopfliLZ77Store*)malloc(sizeof(ZopfliLZ77Store));
  ZopfliInitLZ77Store(data, st);
  return st;
}
void hl_free(ZopfliLZ77Store* st) { ZopfliCleanLZ77Store(st); free(st); }
size_t hl_size(ZopfliLZ77Store* st) { return st->size; }
unsigned short* hl_litlens(ZopfliLZ77Store* st) { return st->litlens; }
unsigned short* hl_dists(ZopfliLZ77Store* st) { return st->dists; }
size_t* hl_pos(ZopfliLZ77Store* st) { return st->pos; }
unsigned short* hl_ll_symbol(ZopfliLZ77Store* st) { return st->ll_symbol; }
unsigned short* hl_d_symbol(ZopfliLZ77Store* st) { return st->d_symbol; }
size_t* hl_ll_counts(ZopfliLZ77Store* st) { return st->ll_counts; }
size_t* hl_d_counts(ZopfliLZ77Store* st) { return st->d_counts; }
void hl_store(unsigned short length, unsigned short dist, size_t pos,
              ZopfliLZ77Store* st) {
  ZopfliStoreLitLenDist(length, dist, pos, st);
}
void hl_copy(ZopfliLZ77Store* src, ZopfliLZ77Store* dst) {
  ZopfliCopyLZ77Store(src, dst);
}
void hl_append(ZopfliLZ77Store* src, ZopfliLZ77Store* dst) {
  ZopfliAppendLZ77Store(src, dst);
}
size_t hl_byte_range(ZopfliLZ77Store* st, size_t lstart, size_t lend) {
  return ZopfliLZ77GetByteRange(st, lstart, lend);
}
void hl_histogram(ZopfliLZ77Store* st, size_t lstart, size_t lend,
                  size_t* ll_counts, size_t* d_counts) {
  ZopfliLZ77GetHistogram(st, lstart, lend, ll_counts, d_counts);
}
void hl_greedy(ZopfliBlockState* s, const unsigned char* in, size_t instart,
               size_t inend, ZopfliLZ77Store* st, ZopfliHash* h) {
  ZopfliLZ77Greedy(s, in, instart, inend, st, h);
}
