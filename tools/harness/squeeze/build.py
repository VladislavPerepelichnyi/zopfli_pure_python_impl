"""Build the squeeze/blocksplitter C reference harness.

    python tools/harness/squeeze/build.py      # prints the binary path

The reference sources default to ../zopfli_reference/src/zopfli relative to the
repository's parent directory; override with ZOPFLI_REFERENCE_SRC.
Output: tools/build/squeeze_harness (gitignored).
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
DEFAULT_REF = "/home/vlad/thesis/wasm/pure_python_impl/zopfli_reference/src/zopfli"
OTHER_SOURCES = ["lz77.c", "hash.c", "cache.c", "tree.c", "katajainen.c",
                 "deflate.c", "util.c"]


def reference_dir():
    return os.environ.get("ZOPFLI_REFERENCE_SRC", DEFAULT_REF)


def build(force=False):
    """Compile the harness if needed; return its path, or None if impossible."""
    ref = reference_dir()
    gcc = shutil.which("gcc") or shutil.which("cc")
    if gcc is None or not os.path.isfile(os.path.join(ref, "squeeze.c")):
        return None
    outdir = os.path.join(ROOT, "tools", "build")
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, "squeeze_harness")
    src = os.path.join(HERE, "harness.c")
    deps = [src] + [os.path.join(ref, f) for f in
                    OTHER_SOURCES + ["squeeze.c", "blocksplitter.c"]]
    if (not force and os.path.exists(out)
            and os.path.getmtime(out) >= max(os.path.getmtime(d) for d in deps)):
        return out
    cmd = [gcc, "-O2", "-std=c99", "-D_POSIX_C_SOURCE=200809L", "-I", ref,
           "-o", out, src] + [os.path.join(ref, f) for f in OTHER_SOURCES] + ["-lm"]
    subprocess.check_call(cmd)
    return out


if __name__ == "__main__":
    path = build(force="--force" in sys.argv)
    if path is None:
        sys.exit("gcc or reference sources not found")
    print(path)
