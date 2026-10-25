#!/bin/sh
# Run the Python unit tests from the package root (core.test_core imports
# "core.*", so direct ./core/test_core.py execution does not resolve them).
cd "$(dirname "$0")/.." || exit 1
exec python3 -m unittest core.test_core handoff_test "$@"
