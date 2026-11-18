"""Shared helpers for tests/test_deflate.py and tests/test_containers.py."""
import importlib
import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS = os.path.join(ROOT, "tools", "harness", "deflate")
REF = "/home/vlad/thesis/wasm/pure_python_impl/zopfli_reference/src/zopfli"

DEPS = ("util", "symbols", "lz77", "tree", "katajainen", "bitwriter", "squeeze",
        "blocksplitter", "hash", "cache")


def have_gcc():
    return shutil.which("gcc") is not None and os.path.isdir(
        os.environ.get("ZOPFLI_REFERENCE_SRC", REF))


def need_c():
    if not have_gcc():
        pytest.skip("gcc or the reference C sources are not available")


def need_oracle():
    try:
        import zopfli.zopfli  # noqa: F401
    except ImportError:
        pytest.skip("py-zopfli (oracle) is not installed")


def need_package():
    """Skips unless every module deflate.py depends on is importable."""
    for name in DEPS + ("deflate", "zlib_container", "gzip_container", "zopfli_lib"):
        try:
            importlib.import_module("zopfli_pure." + name)
        except ImportError as e:
            pytest.skip("zopfli_pure.%s not available yet: %s" % (name, e))


def checks(seed=12345):
    """The tools/harness/deflate/checks.py module bound to the real modules."""
    need_c()
    need_package()
    if HARNESS not in sys.path:
        sys.path.insert(0, HARNESS)
    import checks as c
    c.init(use_stubs=False, seed=seed)
    if c.D.__dict__.get("__stub__") or any(
            getattr(m, "__stub__", False) for m in c.mods.values()):
        pytest.fail("stand-in modules leaked into the test process")
    return c
