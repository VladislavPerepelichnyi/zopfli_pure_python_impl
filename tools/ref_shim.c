/*
ref_shim.c: flat C entry points into the reference Zopfli library, for ctypes.

Compiled together with the unmodified reference sources into libzopfli_ref.so
(see tools/build_reference.py). Every function takes plain integers / pointers
so that tests/ref.py can call it with ctypes without mirroring C structs.

LZ77 stores are returned as opaque handles (ZopfliLZ77Store*). Use
ref_store_size / ref_store_export to copy them out as flat arrays
(litlens, dists, pos) and ref_store_free to release them. A store can also be
rebuilt from flat arrays (ref_store_from_arrays), so that C stages such as
ZopfliCalculateBlockSize can be evaluated on a store produced by the Python
port.

Memory returned through `unsigned char** out` / `size_t** points` must be
released with ref_free.
*/

#include <stdlib.h>
#include <string.h>

#include "blocksplitter.h"
#include "deflate.h"
#include "hash.h"
#include "katajainen.h"
#include "lz77.h"
#include "squeeze.h"
#include "tree.h"
#include "util.h"
#include "zopfli.h"

/* Public in deflate.c, not declared in deflate.h. */
void OptimizeHuffmanForRle(int length, size_t* counts);

#define OPTS_PARAMS int verbose, int verbose_more, int numiterations, \
    int blocksplitting, int blocksplittinglast, int blocksplittingmax

static void make_options(ZopfliOptions* o, OPTS_PARAMS) {
  ZopfliInitOptions(o);
  o->verbose = verbose;
  o->verbose_more = verbose_more;
  o->numiterations = numiterations;
  o->blocksplitting = blocksplitting;
  o->blocksplittinglast = blocksplittinglast;
  o->blocksplittingmax = blocksplittingmax;
}

#define OPTS_ARGS verbose, verbose_more, numiterations, blocksplitting, \
    blocksplittinglast, blocksplittingmax

void ref_free(void* p) { free(p); }

int ref_version(void) { return 1; }

/* ---------------------------------------------------------------- compress */

/* ZopfliCompress: format 0 = gzip, 1 = zlib, 2 = raw deflate. */
void ref_compress(OPTS_PARAMS, int format,
                  const unsigned char* in, size_t insize,
                  unsigned char** out, size_t* outsize) {
  ZopfliOptions o;
  make_options(&o, OPTS_ARGS);
  *out = 0;
  *outsize = 0;
  ZopfliCompress(&o, (ZopfliFormat)format, in, insize, out, outsize);
}

/* ZopfliDeflate with an explicit btype (0, 1, 2) and final flag. */
void ref_deflate(OPTS_PARAMS, int btype, int final,
                 const unsigned char* in, size_t insize,
                 unsigned char** out, size_t* outsize) {
  ZopfliOptions o;
  unsigned char bp = 0;
  make_options(&o, OPTS_ARGS);
  *out = 0;
  *outsize = 0;
  ZopfliDeflate(&o, btype, final, in, insize, &bp, out, outsize);
}

/* ZopfliDeflatePart on [instart, inend) of in, starting at bit pointer 0. */
void ref_deflate_part(OPTS_PARAMS, int btype, int final,
                      const unsigned char* in, size_t instart, size_t inend,
                      unsigned char** out, size_t* outsize) {
  ZopfliOptions o;
  unsigned char bp = 0;
  make_options(&o, OPTS_ARGS);
  *out = 0;
  *outsize = 0;
  ZopfliDeflatePart(&o, btype, final, in, instart, inend, &bp, out, outsize);
}

/* ------------------------------------------------------------------ stores */

static ZopfliLZ77Store* new_store(const unsigned char* in) {
  ZopfliLZ77Store* store = (ZopfliLZ77Store*)malloc(sizeof(*store));
  ZopfliInitLZ77Store(in, store);
  return store;
}

void ref_store_free(ZopfliLZ77Store* store) {
  if (!store) return;
  ZopfliCleanLZ77Store(store);
  free(store);
}

size_t ref_store_size(const ZopfliLZ77Store* store) { return store->size; }

void ref_store_export(const ZopfliLZ77Store* store, unsigned short* litlens,
                      unsigned short* dists, size_t* pos) {
  size_t i;
  for (i = 0; i < store->size; i++) {
    litlens[i] = store->litlens[i];
    dists[i] = store->dists[i];
    pos[i] = store->pos[i];
  }
}

/* Exports ll_symbol, d_symbol (size entries each) and the chunked cumulative
histograms ll_counts, d_counts (llsize = ZOPFLI_NUM_LL * ceil(size / NUM_LL),
dsize = ZOPFLI_NUM_D * ceil(size / NUM_D) entries). */
void ref_store_export_symbols(const ZopfliLZ77Store* store,
                              unsigned short* ll_symbol,
                              unsigned short* d_symbol,
                              size_t* ll_counts, size_t* d_counts) {
  size_t i;
  size_t llsize = ZOPFLI_NUM_LL * ((store->size + ZOPFLI_NUM_LL - 1) / ZOPFLI_NUM_LL);
  size_t dsize = ZOPFLI_NUM_D * ((store->size + ZOPFLI_NUM_D - 1) / ZOPFLI_NUM_D);
  for (i = 0; i < store->size; i++) {
    ll_symbol[i] = store->ll_symbol[i];
    d_symbol[i] = store->d_symbol[i];
  }
  for (i = 0; i < llsize; i++) ll_counts[i] = store->ll_counts[i];
  for (i = 0; i < dsize; i++) d_counts[i] = store->d_counts[i];
}

/* Builds a store from flat arrays via ZopfliStoreLitLenDist. `in` must stay
alive as long as the store is used. */
ZopfliLZ77Store* ref_store_from_arrays(const unsigned char* in,
                                       const unsigned short* litlens,
                                       const unsigned short* dists,
                                       const size_t* pos, size_t n) {
  size_t i;
  ZopfliLZ77Store* store = new_store(in);
  for (i = 0; i < n; i++) {
    ZopfliStoreLitLenDist(litlens[i], dists[i], pos[i], store);
  }
  return store;
}

/* ZopfliLZ77GetHistogram over [lstart, lend). */
void ref_lz77_get_histogram(const ZopfliLZ77Store* store, size_t lstart,
                            size_t lend, size_t* ll_counts, size_t* d_counts) {
  ZopfliLZ77GetHistogram(store, lstart, lend, ll_counts, d_counts);
}

size_t ref_lz77_get_byte_range(const ZopfliLZ77Store* store, size_t lstart,
                               size_t lend) {
  return ZopfliLZ77GetByteRange(store, lstart, lend);
}

/* ZopfliLZ77Greedy on [instart, inend) with a fresh block state and hash,
like ZopfliBlockSplit does (add_lmc = 0 there). */
ZopfliLZ77Store* ref_lz77_greedy(OPTS_PARAMS, int add_lmc,
                                 const unsigned char* in, size_t instart,
                                 size_t inend) {
  ZopfliOptions o;
  ZopfliBlockState s;
  ZopfliHash hash;
  ZopfliLZ77Store* store = new_store(in);
  make_options(&o, OPTS_ARGS);
  ZopfliInitBlockState(&o, instart, inend, add_lmc, &s);
  ZopfliAllocHash(ZOPFLI_WINDOW_SIZE, &hash);
  ZopfliLZ77Greedy(&s, in, instart, inend, store, &hash);
  ZopfliCleanHash(&hash);
  ZopfliCleanBlockState(&s);
  return store;
}

/* ZopfliLZ77Optimal on [instart, inend), block state with lmc, as in
ZopfliDeflatePart. */
ZopfliLZ77Store* ref_lz77_optimal(OPTS_PARAMS, int lz77_numiterations,
                                  const unsigned char* in, size_t instart,
                                  size_t inend) {
  ZopfliOptions o;
  ZopfliBlockState s;
  ZopfliLZ77Store* store = new_store(in);
  make_options(&o, OPTS_ARGS);
  ZopfliInitBlockState(&o, instart, inend, 1, &s);
  ZopfliLZ77Optimal(&s, in, instart, inend, lz77_numiterations, store);
  ZopfliCleanBlockState(&s);
  return store;
}

/* ZopfliLZ77OptimalFixed on [instart, inend), as in ZopfliDeflatePart
(btype 1). */
ZopfliLZ77Store* ref_lz77_optimal_fixed(OPTS_PARAMS,
                                        const unsigned char* in,
                                        size_t instart, size_t inend) {
  ZopfliOptions o;
  ZopfliBlockState s;
  ZopfliLZ77Store* store = new_store(in);
  make_options(&o, OPTS_ARGS);
  ZopfliInitBlockState(&o, instart, inend, 1, &s);
  ZopfliLZ77OptimalFixed(&s, in, instart, inend, store);
  ZopfliCleanBlockState(&s);
  return store;
}

/* ZopfliFindLongestMatch at `pos` after a fresh hash has been warmed up and
updated for every position in [instart, pos], exactly like the start of
ZopfliLZ77Greedy. No lmc. Returns length; *distance set. sublen (259 entries)
may be NULL. */
unsigned ref_find_longest_match(const unsigned char* in, size_t instart,
                                size_t inend, size_t pos, size_t limit,
                                unsigned short* sublen,
                                unsigned short* distance) {
  ZopfliOptions o;
  ZopfliBlockState s;
  ZopfliHash hash;
  unsigned short length = 0;
  size_t i;
  size_t windowstart = instart > ZOPFLI_WINDOW_SIZE
      ? instart - ZOPFLI_WINDOW_SIZE : 0;
  ZopfliInitOptions(&o);
  ZopfliInitBlockState(&o, instart, inend, 0, &s);
  ZopfliAllocHash(ZOPFLI_WINDOW_SIZE, &hash);
  ZopfliResetHash(ZOPFLI_WINDOW_SIZE, &hash);
  ZopfliWarmupHash(in, windowstart, inend, &hash);
  for (i = windowstart; i <= pos; i++) {
    ZopfliUpdateHash(in, i, inend, &hash);
  }
  ZopfliFindLongestMatch(&s, &hash, in, pos, inend, limit, sublen, distance,
                         &length);
  ZopfliCleanHash(&hash);
  ZopfliCleanBlockState(&s);
  return length;
}

/* -------------------------------------------------------------- deflate.c */

double ref_calculate_block_size(const ZopfliLZ77Store* store, size_t lstart,
                                size_t lend, int btype) {
  return ZopfliCalculateBlockSize(store, lstart, lend, btype);
}

double ref_calculate_block_size_auto_type(const ZopfliLZ77Store* store,
                                          size_t lstart, size_t lend) {
  return ZopfliCalculateBlockSizeAutoType(store, lstart, lend);
}

void ref_optimize_huffman_for_rle(int length, size_t* counts) {
  OptimizeHuffmanForRle(length, counts);
}

/* -------------------------------------------------------- blocksplitter.c */

void ref_block_split_lz77(OPTS_PARAMS, const ZopfliLZ77Store* store,
                          size_t maxblocks, size_t** points, size_t* npoints) {
  ZopfliOptions o;
  make_options(&o, OPTS_ARGS);
  *points = 0;
  *npoints = 0;
  ZopfliBlockSplitLZ77(&o, store, maxblocks, points, npoints);
}

void ref_block_split(OPTS_PARAMS, const unsigned char* in, size_t instart,
                     size_t inend, size_t maxblocks, size_t** points,
                     size_t* npoints) {
  ZopfliOptions o;
  make_options(&o, OPTS_ARGS);
  *points = 0;
  *npoints = 0;
  ZopfliBlockSplit(&o, in, instart, inend, maxblocks, points, npoints);
}

void ref_block_split_simple(const unsigned char* in, size_t instart,
                            size_t inend, size_t blocksize, size_t** points,
                            size_t* npoints) {
  *points = 0;
  *npoints = 0;
  ZopfliBlockSplitSimple(in, instart, inend, blocksize, points, npoints);
}

/* ------------------------------------------------------ katajainen / tree */

int ref_length_limited_code_lengths(const size_t* frequencies, int n,
                                    int maxbits, unsigned* bitlengths) {
  return ZopfliLengthLimitedCodeLengths(frequencies, n, maxbits, bitlengths);
}

void ref_calculate_bit_lengths(const size_t* count, size_t n, int maxbits,
                               unsigned* bitlengths) {
  ZopfliCalculateBitLengths(count, n, maxbits, bitlengths);
}

void ref_lengths_to_symbols(const unsigned* lengths, size_t n,
                            unsigned maxbits, unsigned* symbols) {
  ZopfliLengthsToSymbols(lengths, n, maxbits, symbols);
}

void ref_calculate_entropy(const size_t* count, size_t n, double* bitlengths) {
  ZopfliCalculateEntropy(count, n, bitlengths);
}
