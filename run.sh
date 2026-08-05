#!/usr/bin/env bash
# Compatibility shim. `uv run pr-rename-review build` is the real entry point.
#
#   ./run.sh 259
#   REPO=/path/to/checkout ./run.sh https://github.com/owner/repo/pull/259
#   REPO=/path/to/checkout BASE=52efff3 HEAD_REF=1ce7bfa ./run.sh
#
# With no argument, the PR of the checked-out branch is reviewed. BASE and
# HEAD_REF skip GitHub entirely.
set -euo pipefail
# Capture the caller's directory before the cd below. An unset $REPO means the
# tool reviews the checkout it was invoked in -- and after the cd that is this
# script's own checkout, not whatever repo the caller is sitting in: the wrong
# PR, the wrong base, the wrong head.
REPO="${REPO:-$PWD}"; export REPO
cd "$(dirname "$0")"
exec uv run pr-rename-review build "$@"
