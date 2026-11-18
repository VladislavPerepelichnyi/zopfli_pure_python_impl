/*
C reference harness for zopfli_pure.squeeze and zopfli_pure.blocksplitter.

Unity build: squeeze.c and blocksplitter.c are #included so that their static
functions are reachable; the other reference .c files are compiled and linked
separately (see build.py next to this file).

Usage: harness <command> [args...]   (all output on stdout, verbose on stderr)

  ran N                           N outputs of Ran() from InitRanState.
  randomize FILE ROUNDS           FILE: 288+32 counts. Applies
                                  RandomizeStatFreqs ROUNDS times (one RanState),
                                  printing the 320 counts after each round.
  costs FILE                      FILE: 288+32 counts then 288+32 symbol costs
                                  (hex doubles). Prints GetCostStat for every
                                  literal, for every (length, dist-symbol-start)
                                  and some odd distances, GetCostFixed likewise,
                                  and GetCostModelMinCost for both models.
  entropy FILE                    FILE: 288+32 counts. Prints CalculateStatistics
                                  result (hex doubles).
  addweighed FILE                 FILE: 2 x (288+32) counts. Prints
                                  AddWeighedStatFreqs(a, 1.0, b, 0.5, a).
  trace FILE                      FILE: size, then size+1 lengths. Prints the
                                  TraceBackwards path.
  findmin K START END             FindMinimum on synthetic function K.
  best FILE INSTART INEND MODEL ITER
                                  MODEL 0: GetCostFixed, 1: GetCostStat with the
                                  stats of the greedy store after ITER optimal
                                  runs. Prints the cost and the length_array.
  optimal FILE INSTART INEND NUMITER VERBOSE
                                  Instrumented copy of ZopfliLZ77Optimal:
                                  per-iteration run cost and block cost, then
                                  the final store; then the store produced by
                                  the real ZopfliLZ77Optimal.
  fixed FILE INSTART INEND        ZopfliLZ77OptimalFixed store.
  split FILE INSTART INEND MAXBLOCKS VERBOSE
                                  ZopfliBlockSplit split points.
  splitlz77 FILE INSTART INEND MAXBLOCKS NUMITER VERBOSE
                                  ZopfliBlockSplitLZ77 on the greedy store
                                  (NUMITER 0) or the ZopfliLZ77Optimal store.
*/

#include "squeeze.c"
#include "blocksplitter.c"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned char* ReadFile(const char* name, size_t* size) {
  FILE* f = fopen(name, "rb");
  unsigned char* data;
  long n;
  if (!f) { perror(name); exit(2); }
  fseek(f, 0, SEEK_END);
  n = ftell(f);
  fseek(f, 0, SEEK_SET);
  data = (unsigned char*)malloc(n + 1);
  if (n > 0 && fread(data, 1, n, f) != (size_t)n) { perror(name); exit(2); }
  fclose(f);
  *size = (size_t)n;
  return data;
}

static FILE* OpenText(const char* name) {
  FILE* f = fopen(name, "r");
  if (!f) { perror(name); exit(2); }
  return f;
}

static void ReadCounts(FILE* f, SymbolStats* st) {
  size_t i;
  for (i = 0; i < ZOPFLI_NUM_LL; i++) {
    if (fscanf(f, "%zu", &st->litlens[i]) != 1) exit(3);
  }
  for (i = 0; i < ZOPFLI_NUM_D; i++) {
    if (fscanf(f, "%zu", &st->dists[i]) != 1) exit(3);
  }
}

static void PrintCounts(const SymbolStats* st) {
  size_t i;
  for (i = 0; i < ZOPFLI_NUM_LL; i++) printf("%zu ", st->litlens[i]);
  for (i = 0; i < ZOPFLI_NUM_D; i++) printf("%zu ", st->dists[i]);
  printf("\n");
}

static void PrintSymbolCosts(const SymbolStats* st) {
  size_t i;
  for (i = 0; i < ZOPFLI_NUM_LL; i++) printf("%a ", st->ll_symbols[i]);
  for (i = 0; i < ZOPFLI_NUM_D; i++) printf("%a ", st->d_symbols[i]);
  printf("\n");
}

static void PrintStore(const ZopfliLZ77Store* store) {
  size_t i;
  printf("store %zu\n", store->size);
  for (i = 0; i < store->size; i++) {
    printf("%u %u %zu\n", store->litlens[i], store->dists[i], store->pos[i]);
  }
}

static const int kDists[] = {
  1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13, 16, 17, 24, 25, 32, 33, 48, 49, 64, 65,
  96, 97, 128, 129, 192, 193, 256, 257, 384, 385, 512, 513, 768, 769, 1024,
  1025, 1536, 1537, 2048, 2049, 3072, 3073, 4096, 4097, 6144, 6145, 8192, 8193,
  12288, 12289, 16384, 16385, 24576, 24577, 32767, 32768
};

static void PrintModelCosts(CostModelFun* f, void* ctx) {
  int l;
  size_t d;
  for (l = 0; l < 256; l++) printf("%a ", f(l, 0, ctx));
  printf("\n");
  for (l = 3; l <= 258; l++) {
    for (d = 0; d < sizeof(kDists) / sizeof(kDists[0]); d++) {
      printf("%a ", f(l, kDists[d], ctx));
    }
  }
  printf("\n%a\n", GetCostModelMinCost(f, ctx));
}

/* Synthetic functions for FindMinimum. All values are exact in double. */
static double SynthF(size_t i, void* context) {
  int k = *(int*)context;
  unsigned long long x = (unsigned long long)i;
  switch (k) {
    case 0: /* Parabola around 777. */
      return (double)((x > 777 ? x - 777 : 777 - x) * (x > 777 ? x - 777 : 777 - x));
    case 1: /* Pseudo-random. */
      return (double)((x * 2654435761ULL) % 100003ULL);
    case 2: /* Parabola plus bumps (local minima). */
      return (double)((x > 5000 ? x - 5000 : 5000 - x)) * 0.5
          + (double)((x * 40503ULL) % 977ULL);
    case 3: /* Constant. */
      return 42.0;
    case 4: /* Decreasing. */
      return 1e6 - (double)x;
    case 5: /* Increasing. */
      return (double)x * 0.25;
    default: /* Large values (> ZOPFLI_LARGE_FLOAT) everywhere except a pit. */
      return x % 1000 == 3 ? 1.0 : 2e30;
  }
}

static double CmdOptimalInstrumented(ZopfliBlockState *s,
    const unsigned char* in, size_t instart, size_t inend,
    int numiterations, ZopfliLZ77Store* store) {
  /* Copy of ZopfliLZ77Optimal (squeeze.c) with the cost of each run printed. */
  size_t blocksize = inend - instart;
  unsigned short* length_array =
      (unsigned short*)malloc(sizeof(unsigned short) * (blocksize + 1));
  unsigned short* path = 0;
  size_t pathsize = 0;
  ZopfliLZ77Store currentstore;
  ZopfliHash hash;
  ZopfliHash* h = &hash;
  SymbolStats stats, beststats, laststats;
  int i;
  float* costs = (float*)malloc(sizeof(float) * (blocksize + 1));
  double cost;
  double bestcost = ZOPFLI_LARGE_FLOAT;
  double lastcost = 0;
  RanState ran_state;
  int lastrandomstep = -1;

  InitRanState(&ran_state);
  InitStats(&stats);
  ZopfliInitLZ77Store(in, &currentstore);
  ZopfliAllocHash(ZOPFLI_WINDOW_SIZE, h);

  ZopfliLZ77Greedy(s, in, instart, inend, &currentstore, h);
  GetStatistics(&currentstore, &stats);

  for (i = 0; i < numiterations; i++) {
    double runcost;
    ZopfliCleanLZ77Store(&currentstore);
    ZopfliInitLZ77Store(in, &currentstore);
    runcost = LZ77OptimalRun(s, in, instart, inend, &path, &pathsize,
                   length_array, GetCostStat, (void*)&stats,
                   &currentstore, h, costs);
    cost = ZopfliCalculateBlockSize(&currentstore, 0, currentstore.size, 2);
    printf("iter %d %a %a %zu\n", i, runcost, cost, currentstore.size);
    if (s->options->verbose_more || (s->options->verbose && cost < bestcost)) {
      fprintf(stderr, "Iteration %d: %d bit\n", i, (int) cost);
    }
    if (cost < bestcost) {
      ZopfliCopyLZ77Store(&currentstore, store);
      CopyStats(&stats, &beststats);
      bestcost = cost;
    }
    CopyStats(&stats, &laststats);
    ClearStatFreqs(&stats);
    GetStatistics(&currentstore, &stats);
    if (lastrandomstep != -1) {
      AddWeighedStatFreqs(&stats, 1.0, &laststats, 0.5, &stats);
      CalculateStatistics(&stats);
    }
    if (i > 5 && cost == lastcost) {
      CopyStats(&beststats, &stats);
      RandomizeStatFreqs(&ran_state, &stats);
      CalculateStatistics(&stats);
      lastrandomstep = i;
    }
    lastcost = cost;
  }

  free(length_array);
  free(path);
  free(costs);
  ZopfliCleanLZ77Store(&currentstore);
  ZopfliCleanHash(h);
  return bestcost;
}

int main(int argc, char** argv) {
  const char* cmd;
  if (argc < 2) return 1;
  cmd = argv[1];

  if (!strcmp(cmd, "ran")) {
    RanState st;
    long n = atol(argv[2]), i;
    InitRanState(&st);
    for (i = 0; i < n; i++) printf("%u\n", Ran(&st));
  } else if (!strcmp(cmd, "randomize")) {
    SymbolStats st;
    RanState rs;
    FILE* f = OpenText(argv[2]);
    int rounds = atoi(argv[3]), r;
    InitStats(&st);
    ReadCounts(f, &st);
    fclose(f);
    InitRanState(&rs);
    for (r = 0; r < rounds; r++) {
      RandomizeStatFreqs(&rs, &st);
      PrintCounts(&st);
    }
  } else if (!strcmp(cmd, "costs")) {
    SymbolStats st;
    size_t i;
    FILE* f = OpenText(argv[2]);
    char buf[64];
    InitStats(&st);
    ReadCounts(f, &st);
    for (i = 0; i < ZOPFLI_NUM_LL; i++) {
      if (fscanf(f, "%63s", buf) != 1) return 3;
      st.ll_symbols[i] = strtod(buf, 0);
    }
    for (i = 0; i < ZOPFLI_NUM_D; i++) {
      if (fscanf(f, "%63s", buf) != 1) return 3;
      st.d_symbols[i] = strtod(buf, 0);
    }
    fclose(f);
    PrintModelCosts(GetCostStat, &st);
    PrintModelCosts(GetCostFixed, 0);
  } else if (!strcmp(cmd, "entropy")) {
    SymbolStats st;
    FILE* f = OpenText(argv[2]);
    InitStats(&st);
    ReadCounts(f, &st);
    fclose(f);
    CalculateStatistics(&st);
    PrintSymbolCosts(&st);
  } else if (!strcmp(cmd, "addweighed")) {
    SymbolStats a, b;
    FILE* f = OpenText(argv[2]);
    InitStats(&a);
    InitStats(&b);
    ReadCounts(f, &a);
    ReadCounts(f, &b);
    fclose(f);
    AddWeighedStatFreqs(&a, 1.0, &b, 0.5, &a);
    PrintCounts(&a);
  } else if (!strcmp(cmd, "trace")) {
    FILE* f = OpenText(argv[2]);
    size_t size, i;
    unsigned short* la;
    unsigned short* path = 0;
    size_t pathsize = 0;
    if (fscanf(f, "%zu", &size) != 1) return 3;
    la = (unsigned short*)malloc(sizeof(unsigned short) * (size + 1));
    for (i = 0; i <= size; i++) {
      unsigned v;
      if (fscanf(f, "%u", &v) != 1) return 3;
      la[i] = (unsigned short)v;
    }
    fclose(f);
    TraceBackwards(size, la, &path, &pathsize);
    for (i = 0; i < pathsize; i++) printf("%u ", path[i]);
    printf("\n");
    free(la);
    free(path);
  } else if (!strcmp(cmd, "findmin")) {
    int k = atoi(argv[2]);
    size_t start = (size_t)atol(argv[3]), end = (size_t)atol(argv[4]);
    double smallest;
    size_t r = FindMinimum(SynthF, &k, start, end, &smallest);
    printf("%zu %a\n", r, smallest);
  } else {
    size_t insize;
    unsigned char* in = ReadFile(argv[2], &insize);
    size_t instart = (size_t)atol(argv[3]);
    size_t inend = (size_t)atol(argv[4]);
    ZopfliOptions options;
    ZopfliInitOptions(&options);

    if (!strcmp(cmd, "best")) {
      int model = atoi(argv[5]);
      int iters = atoi(argv[6]);
      size_t blocksize = inend - instart, i;
      unsigned short* la =
          (unsigned short*)malloc(sizeof(unsigned short) * (blocksize + 1));
      float* costs = (float*)malloc(sizeof(float) * (blocksize + 1));
      ZopfliBlockState s;
      ZopfliHash hash;
      SymbolStats stats;
      ZopfliLZ77Store store;
      double cost;
      ZopfliInitBlockState(&options, instart, inend, 1, &s);
      ZopfliAllocHash(ZOPFLI_WINDOW_SIZE, &hash);
      InitStats(&stats);
      if (model == 1) {
        unsigned short* path = 0;
        size_t pathsize = 0;
        int it;
        ZopfliInitLZ77Store(in, &store);
        ZopfliLZ77Greedy(&s, in, instart, inend, &store, &hash);
        GetStatistics(&store, &stats);
        for (it = 0; it < iters; it++) {
          ZopfliCleanLZ77Store(&store);
          ZopfliInitLZ77Store(in, &store);
          LZ77OptimalRun(&s, in, instart, inend, &path, &pathsize, la,
                         GetCostStat, &stats, &store, &hash, costs);
          ClearStatFreqs(&stats);
          GetStatistics(&store, &stats);
        }
        ZopfliCleanLZ77Store(&store);
        free(path);
        cost = GetBestLengths(&s, in, instart, inend, GetCostStat, &stats,
                              la, &hash, costs);
      } else {
        cost = GetBestLengths(&s, in, instart, inend, GetCostFixed, 0,
                              la, &hash, costs);
      }
      printf("%a\n", cost);
      if (instart != inend) {
        for (i = 0; i <= blocksize; i++) printf("%u ", la[i]);
        printf("\n");
        for (i = 0; i <= blocksize; i++) printf("%a ", (double)costs[i]);
        printf("\n");
      }
      free(la);
      free(costs);
      ZopfliCleanBlockState(&s);
      ZopfliCleanHash(&hash);
    } else if (!strcmp(cmd, "optimal")) {
      int numiter = atoi(argv[5]);
      ZopfliBlockState s;
      ZopfliLZ77Store store;
      double best;
      options.verbose = atoi(argv[6]) & 1;
      options.verbose_more = (atoi(argv[6]) >> 1) & 1;
      ZopfliInitLZ77Store(in, &store);
      ZopfliInitBlockState(&options, instart, inend, 1, &s);
      best = CmdOptimalInstrumented(&s, in, instart, inend, numiter, &store);
      printf("best %a\n", best);
      PrintStore(&store);
      ZopfliCleanLZ77Store(&store);
      ZopfliCleanBlockState(&s);
      /* The real function, without verbose output. */
      options.verbose = options.verbose_more = 0;
      ZopfliInitLZ77Store(in, &store);
      ZopfliInitBlockState(&options, instart, inend, 1, &s);
      ZopfliLZ77Optimal(&s, in, instart, inend, numiter, &store);
      PrintStore(&store);
      ZopfliCleanLZ77Store(&store);
      ZopfliCleanBlockState(&s);
    } else if (!strcmp(cmd, "fixed")) {
      ZopfliBlockState s;
      ZopfliLZ77Store store;
      ZopfliInitLZ77Store(in, &store);
      ZopfliInitBlockState(&options, instart, inend, 1, &s);
      ZopfliLZ77OptimalFixed(&s, in, instart, inend, &store);
      PrintStore(&store);
      ZopfliCleanLZ77Store(&store);
      ZopfliCleanBlockState(&s);
    } else if (!strcmp(cmd, "split")) {
      size_t maxblocks = (size_t)atol(argv[5]);
      size_t* sp = 0;
      size_t np = 0, i;
      options.verbose = atoi(argv[6]);
      ZopfliBlockSplit(&options, in, instart, inend, maxblocks, &sp, &np);
      printf("split %zu\n", np);
      for (i = 0; i < np; i++) printf("%zu\n", sp[i]);
      free(sp);
    } else if (!strcmp(cmd, "splitlz77")) {
      size_t maxblocks = (size_t)atol(argv[5]);
      int numiter = atoi(argv[6]);
      size_t* sp = 0;
      size_t np = 0, i;
      ZopfliBlockState s;
      ZopfliLZ77Store store;
      ZopfliHash hash;
      ZopfliInitLZ77Store(in, &store);
      if (numiter == 0) {
        ZopfliInitBlockState(&options, instart, inend, 0, &s);
        ZopfliAllocHash(ZOPFLI_WINDOW_SIZE, &hash);
        ZopfliLZ77Greedy(&s, in, instart, inend, &store, &hash);
        ZopfliCleanHash(&hash);
      } else {
        ZopfliInitBlockState(&options, instart, inend, 1, &s);
        ZopfliLZ77Optimal(&s, in, instart, inend, numiter, &store);
      }
      options.verbose = atoi(argv[7]);
      ZopfliBlockSplitLZ77(&options, &store, maxblocks, &sp, &np);
      printf("split %zu\n", np);
      for (i = 0; i < np; i++) printf("%zu\n", sp[i]);
      free(sp);
      ZopfliCleanLZ77Store(&store);
      ZopfliCleanBlockState(&s);
    } else {
      fprintf(stderr, "unknown command %s\n", cmd);
      return 1;
    }
    free(in);
  }
  return 0;
}
