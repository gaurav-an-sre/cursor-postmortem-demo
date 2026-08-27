#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap: prepare the Python virtualenv and install
# the project (plus dev tooling) in editable mode.
set -euo pipefail

ROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

# The default image ships python3.12 but not the venv/ensurepip module.
if ! python3 -c "import ensurepip" >/dev/null 2>&1; then
    sudo apt-get update -qq
    sudo apt-get install -y --no-install-recommends python3-venv
fi

if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
