#!/usr/bin/env bash
# Prototype driver. Runs the four passes in order and prints where the page
# landed. See README.md for what this is and is not.
#
#   ./run.sh                                    # main...HEAD
#   BASE=52efff3 HEAD_REF=origin/my-branch ./run.sh
set -euo pipefail
cd "$(dirname "$0")"

export REPO=${REPO:-$(git rev-parse --show-toplevel)}
export BASE=${BASE:-main}
export HEAD_REF=${HEAD_REF:-HEAD}
export OUT=${OUT:-$PWD/build}
mkdir -p "$OUT"

# Full output goes to a log; the console gets the tail. Do not pipe these into
# `head` -- the scripts die on SIGPIPE mid-write and leave a truncated file.
run() {
  local name=$1; shift
  echo "== $name"
  python3 "$@" > "$OUT/$name.log"
  tail -n 4 "$OUT/$name.log"
}

run pair    pairup.py
run scope   scope.py
run residual gen2.py
run page    render2.py

echo
echo "pairing disagreements are in $OUT/pair.log"
echo "open $OUT/hidden-renames.html"
