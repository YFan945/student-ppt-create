#!/usr/bin/env sh
# Single-run wrapper for the v0.8 gate set.
#
# All logic lives in run_gates.py so Windows and Linux behave identically; this
# file only locates the interpreter. It deliberately avoids `dirname`/`readlink`
# so it also works in minimal shells where coreutils are not on PATH.
#
# Usage:
#   sh run_gates.sh --art-direction art-direction.yaml --slide-spec slide-spec.yaml \
#                   --evidence-dir outputs/.pptx-work/<work-id> --lock-file slide-spec-lock.json

set -eu

HERE=${0%/*}
if [ "$HERE" = "$0" ]; then
  HERE=.
fi

PY=${PYTHON:-python3}
# `command -v` is not enough on Windows: the Microsoft Store python3.exe alias
# stub is on PATH and passes command -v, but exits 49 without running anything
# (observed in the 2026-09-16 live run: three silent exit-49 failures). Probe
# by actually executing an import, then fall back to `python`.
if ! "$PY" -c "import sys" >/dev/null 2>&1; then
  PY=python
  if ! "$PY" -c "import sys" >/dev/null 2>&1; then
    echo "run_gates.sh: no working Python interpreter (tried python3, python); set PYTHON=/path/to/python" >&2
    exit 127
  fi
fi

exec "$PY" "$HERE/run_gates.py" "$@"
