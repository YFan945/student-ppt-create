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
if ! command -v "$PY" >/dev/null 2>&1; then
  PY=python
fi

exec "$PY" "$HERE/run_gates.py" "$@"
