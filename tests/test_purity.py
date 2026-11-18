"""Purity checks: zopfli_pure may only import math, array, sys, struct and
its own modules (docs/PORTING_SPEC.md, "Strict pure-Python rule").

* Static: AST scan of every .py file in zopfli_pure/ (all import statements,
  including ones nested in functions, plus __import__/importlib calls).
* Dynamic: compress() runs in a subprocess in which zlib, binascii, gzip,
  ctypes, _cffi_backend, zopfli (and other native compression modules) are
  poisoned in sys.modules before zopfli_pure is imported, so any import of
  them raises ImportError.
"""

import ast
import os
import subprocess
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(_REPO, "zopfli_pure")

ALLOWED = {"math", "array", "sys", "struct", "__future__"}
POISONED = ["zlib", "binascii", "gzip", "ctypes", "_ctypes", "_cffi_backend",
            "cffi", "zopfli", "zopfli.zopfli", "zopfli.gzip", "_zlib", "bz2",
            "_bz2", "lzma", "_lzma", "zipfile", "numpy"]


def package_files():
    out = []
    for root, _dirs, files in os.walk(PKG):
        if "__pycache__" in root:
            continue
        for f in files:
            if f.endswith(".py"):
                out.append(os.path.join(root, f))
    return sorted(out)


def imports_of(path):
    """Yield (lineno, module, is_relative) for every import in the file."""
    with open(path, "rb") as f:
        tree = ast.parse(f.read(), filename=path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield node.lineno, a.name, False
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                yield node.lineno, node.module or ".", True
            else:
                yield node.lineno, node.module, False
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (
                fn.attr if isinstance(fn, ast.Attribute) else None)
            if name in ("__import__", "import_module"):
                yield node.lineno, "<dynamic %s()>" % name, False


FILES = package_files()


def test_package_has_files():
    assert FILES, "zopfli_pure/ has no .py files"


@pytest.mark.parametrize("path", FILES, ids=[os.path.relpath(p, PKG) for p in FILES])
def test_static_imports(path):
    bad = []
    for lineno, mod, rel in imports_of(path):
        if rel:
            continue
        top = mod.split(".")[0]
        if top == "zopfli_pure":
            continue
        if top not in ALLOWED:
            bad.append("%s:%d imports %s" % (os.path.relpath(path, _REPO), lineno, mod))
    assert not bad, "forbidden imports:\n" + "\n".join(bad)


DYNAMIC_SCRIPT = r"""
import sys
for m in %(poisoned)r:
    sys.modules[m] = None
sys.path.insert(0, %(repo)r)
import zopfli_pure
if not hasattr(zopfli_pure, "compress"):
    print("NO_COMPRESS")
    sys.exit(0)
data = (b"pure python purity check " * 40) + bytes(range(256)) + b"\x00" * 300
out = zopfli_pure.compress(data, numiterations=2)
gz = zopfli_pure.compress(data, numiterations=1, gzip_mode=1)
s = zopfli_pure.compress("str input €", numiterations=1)
assert isinstance(out, bytes) and isinstance(gz, bytes) and isinstance(s, bytes)
# every zopfli_pure module that was loaded
loaded = sorted(m for m in sys.modules if m.startswith("zopfli_pure"))
nonstd = sorted(m for m, v in sys.modules.items()
                if v is not None and m.split(".")[0] in %(watch)r)
print("OK", out.hex(), gz.hex(), s.hex())
print("LOADED", " ".join(loaded))
print("NONSTD", " ".join(nonstd))
"""


def test_dynamic_no_native_modules():
    script = DYNAMIC_SCRIPT % dict(poisoned=POISONED, repo=_REPO,
                                   watch=sorted(set(m.split(".")[0] for m in POISONED)))
    r = subprocess.run([sys.executable, "-c", script], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=600)
    out = r.stdout.decode()
    if "NO_COMPRESS" in out:
        pytest.skip("zopfli_pure.compress not available yet")
    assert r.returncode == 0, "subprocess failed:\n%s\n%s" % (
        out, r.stderr.decode())
    lines = dict(l.split(" ", 1) if " " in l else (l, "")
                 for l in out.splitlines())
    assert lines.get("NONSTD", "") == ""
    # the poisoned run must give the same bytes as a normal in-process run
    from port import compress
    data = (b"pure python purity check " * 40) + bytes(range(256)) + b"\x00" * 300
    ok = lines["OK"].split()
    assert bytes.fromhex(ok[0]) == compress(data, numiterations=2)
