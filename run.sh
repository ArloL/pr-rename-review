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
cd "$(dirname "$0")"
exec uv run pr-rename-review build "$@"
