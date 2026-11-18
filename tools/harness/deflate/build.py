"""Builds tools/build/deflate_harness.so (unity build of the reference C).

Usage: python tools/harness/deflate/build.py   (prints the .so path)
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
REF = os.environ.get(
    "ZOPFLI_REFERENCE_SRC",
    "/home/vlad/thesis/wasm/pure_python_impl/zopfli_reference/src/zopfli")
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness.c")
OUT = os.path.join(ROOT, "tools", "build", "deflate_harness.so")


def build():
    """Returns the path of the shared library, or None if it cannot be built."""
    if not os.path.isdir(REF) or shutil.which("gcc") is None:
        return None
    deps = [SRC] + [os.path.join(REF, f) for f in os.listdir(REF)
                    if f.endswith((".c", ".h"))]
    if os.path.exists(OUT) and all(
            os.path.getmtime(OUT) >= os.path.getmtime(d) for d in deps):
        return OUT
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # Same FP semantics as the oracle build: SSE2, no FMA contraction.
    cmd = ["gcc", "-O2", "-shared", "-fPIC", "-ffp-contract=off", "-w",
           "-I", REF, SRC, "-o", OUT, "-lm"]
    subprocess.check_call(cmd)
    return OUT


if __name__ == "__main__":
    path = build()
    if path is None:
        sys.exit("gcc or reference sources missing")
    print(path)
