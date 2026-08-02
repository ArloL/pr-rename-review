#!/usr/bin/env bash
# Compatibility shim. `uv run pr-rename-review build` is the real entry point.
#
#   ./run.sh
#   REPO=/path/to/checkout BASE=52efff3 HEAD_REF=1ce7bfa ./run.sh
#
# Refs default to [repo] in .pr-rename-review.toml when unset.
set -euo pipefail
cd "$(dirname "$0")"
exec uv run pr-rename-review build "$@"
