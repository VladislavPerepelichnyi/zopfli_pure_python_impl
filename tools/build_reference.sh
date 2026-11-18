#!/bin/sh
# Builds tools/build/zopfli and tools/build/libzopfli_ref.so from the reference
# C sources. Thin wrapper around build_reference.py (see its docstring).
# Usage: tools/build_reference.sh [--force] [--verbose]
set -e
here=$(cd "$(dirname "$0")" && pwd)
exec "${PYTHON:-python3}" "$here/build_reference.py" "$@"
