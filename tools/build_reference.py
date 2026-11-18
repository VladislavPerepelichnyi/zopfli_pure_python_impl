#!/usr/bin/env python3
"""Build the reference Zopfli C oracle used by the test suite.

Produces, in ``tools/build/`` (gitignored):

* ``zopfli``            the reference command-line binary (zopfli_bin.c)
* ``libzopfli_ref.so``  the reference library plus ``tools/ref_shim.c``, which
                        exposes intermediate stages through flat C functions
                        for ctypes (see ``tests/ref.py``).

Both are compiled from the unmodified google/zopfli sources with ``-O2``, no
``-ffast-math``, ``-ffp-contract=off`` (no FMA contraction) and, on x86-64,
``-march=x86-64 -mno-fma`` so floating point matches plain SSE2 semantics.

The reference source directory is found via ``$ZOPFLI_REFERENCE_DIR`` or by
looking for a ``zopfli_reference/src/zopfli`` directory next to any parent of
this repository. Rebuilds only when a source file (or this script) is newer
than the output, unless ``--force`` is given.

Usage::

    python tools/build_reference.py [--force] [--verbose]
"""

import os
import platform
import shutil
import subprocess
import sys

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(TOOLS_DIR)
BUILD_DIR = os.path.join(TOOLS_DIR, "build")
SHIM = os.path.join(TOOLS_DIR, "ref_shim.c")

LIB_SOURCES = [
    "blocksplitter.c", "cache.c", "deflate.c", "gzip_container.c", "hash.c",
    "katajainen.c", "lz77.c", "squeeze.c", "tree.c", "util.c",
    "zlib_container.c", "zopfli_lib.c",
]
BIN_SOURCE = "zopfli_bin.c"

LIB_NAME = "libzopfli_ref.so"
BIN_NAME = "zopfli"


class BuildError(RuntimeError):
    pass


def find_reference_dir():
    """Return the reference ``src/zopfli`` directory, or raise BuildError."""
    env = os.environ.get("ZOPFLI_REFERENCE_DIR")
    candidates = []
    if env:
        candidates.append(env)
    d = REPO_DIR
    while True:
        candidates.append(os.path.join(d, "zopfli_reference"))
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    for c in candidates:
        for sub in ("src/zopfli", ""):
            p = os.path.join(c, sub) if sub else c
            if os.path.isfile(os.path.join(p, "deflate.c")) and \
                    os.path.isfile(os.path.join(p, "zopfli.h")):
                return os.path.abspath(p)
    raise BuildError("reference sources not found; set ZOPFLI_REFERENCE_DIR "
                     "to the zopfli checkout (or its src/zopfli)")


def find_cc():
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
    if not cc or not shutil.which(cc):
        raise BuildError("no C compiler found (gcc/cc); set CC")
    return cc


def cflags():
    flags = ["-O2", "-std=c99", "-fPIC", "-ffp-contract=off",
             "-fno-fast-math", "-W", "-Wall", "-Wno-unused-function",
             "-Wno-unused-parameter"]
    if platform.machine() in ("x86_64", "AMD64"):
        flags += ["-march=x86-64", "-mno-fma"]
    return flags


def _stale(output, inputs):
    if not os.path.exists(output):
        return True
    t = os.path.getmtime(output)
    return any(os.path.getmtime(i) > t for i in inputs)


def _run(cmd, verbose):
    if verbose:
        print(" ".join(cmd), file=sys.stderr)
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if r.returncode != 0:
        raise BuildError("command failed: %s\n%s" % (
            " ".join(cmd), r.stdout.decode("utf-8", "replace")))


def build(force=False, verbose=False):
    """Build both targets if stale. Returns (lib_path, bin_path)."""
    src = find_reference_dir()
    cc = find_cc()
    os.makedirs(BUILD_DIR, exist_ok=True)
    lib_srcs = [os.path.join(src, f) for f in LIB_SOURCES]
    headers = [os.path.join(src, f) for f in os.listdir(src) if f.endswith(".h")]
    deps = lib_srcs + headers + [os.path.abspath(__file__)]
    flags = cflags()

    lib = os.path.join(BUILD_DIR, LIB_NAME)
    if force or _stale(lib, deps + [SHIM]):
        tmp = lib + ".tmp%d" % os.getpid()
        _run([cc] + flags + ["-shared", "-I", src, "-o", tmp] + lib_srcs
             + [SHIM, "-lm"], verbose)
        os.replace(tmp, lib)  # atomic: safe with parallel test workers

    binp = os.path.join(BUILD_DIR, BIN_NAME)
    bin_src = os.path.join(src, BIN_SOURCE)
    if force or _stale(binp, deps + [bin_src]):
        tmp = binp + ".tmp%d" % os.getpid()
        _run([cc] + flags + ["-I", src, "-o", tmp] + lib_srcs + [bin_src, "-lm"],
             verbose)
        os.replace(tmp, binp)
    return lib, binp


def main(argv):
    force = "--force" in argv
    verbose = "--verbose" in argv or "-v" in argv
    try:
        lib, binp = build(force=force, verbose=verbose)
    except BuildError as e:
        print("build_reference: %s" % e, file=sys.stderr)
        return 1
    print(lib)
    print(binp)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
