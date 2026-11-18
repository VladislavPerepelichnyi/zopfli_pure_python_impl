/*
C harness for the tree/katajainen/bitwriter ports (tests/test_tree.py).

Unity build: deflate.c is #included so its static bit writers (AddBit,
AddBits, AddHuffmanBits) are reachable. The other reference sources are
compiled and linked unchanged. Every function here is a thin, flat wrapper
for ctypes.
*/
#include <stdlib.h>
#include <string.h>

#include "deflate.c"
#include "katajainen.h"
#include "tree.h"

int h_length_limited_code_lengths(const size_t* frequencies, int n,
                                  int maxbits, unsigned* bitlengths) {
  return ZopfliLengthLimitedCodeLengths(frequencies, n, maxbits, bitlengths);
}

void h_calculate_bit_lengths(const size_t* count, size_t n, int maxbits,
                             unsigned* bitlengths) {
  ZopfliCalculateBitLengths(count, n, maxbits, bitlengths);
}

void h_lengths_to_symbols(const unsigned* lengths, size_t n, unsigned maxbits,
                          unsigned* symbols) {
  ZopfliLengthsToSymbols(lengths, n, maxbits, symbols);
}

void h_calculate_entropy(const size_t* count, size_t n, double* bitlengths) {
  ZopfliCalculateEntropy(count, n, bitlengths);
}

/*
Runs a sequence of bit writer operations on an output buffer that starts as
a copy of init[0..initsize) with bit pointer bp0.
ops: nops triples (kind, symbol, length); kind 0 = AddBit(symbol),
1 = AddBits(symbol, length), 2 = AddHuffmanBits(symbol, length).
Writes the result to result (capacity rescap) and returns its size, or
(size_t)-1 if it does not fit. *bp_out receives the final bit pointer.
*/
size_t h_bitwriter(const unsigned char* init, size_t initsize, unsigned bp0,
                   const unsigned* ops, size_t nops, unsigned char* result,
                   size_t rescap, unsigned* bp_out) {
  unsigned char bp = (unsigned char)bp0;
  unsigned char* out = 0;
  size_t outsize = 0;
  size_t i;
  for (i = 0; i < initsize; i++) ZOPFLI_APPEND_DATA(init[i], &out, &outsize);
  for (i = 0; i < nops; i++) {
    unsigned kind = ops[3 * i], symbol = ops[3 * i + 1], length = ops[3 * i + 2];
    if (kind == 0) AddBit((int)symbol, &bp, &out, &outsize);
    else if (kind == 1) AddBits(symbol, length, &bp, &out, &outsize);
    else AddHuffmanBits(symbol, length, &bp, &out, &outsize);
  }
  *bp_out = bp;
  if (outsize > rescap) {
    free(out);
    return (size_t)-1;
  }
  if (outsize) memcpy(result, out, outsize);
  free(out);
  return outsize;
}
