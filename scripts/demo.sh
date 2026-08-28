#!/usr/bin/env bash
# One-shot local demo: create an incident, then run the postmortem agent on it.
#
# Usage:
#   ./scripts/demo.sh                # fully offline: mock agent + Notion dry-run  (== make demo)
#   ./scripts/demo.sh --mock-agent   # mock RCA, live Notion publish              (== make demo-notion)
#                                    # (live publish needs NOTION_TOKEN + NOTION_PARENT_PAGE_ID)
#   NOTION_TOKEN=... NOTION_PARENT_PAGE_ID=... CURSOR_API_KEY=... ./scripts/demo.sh
#                                    # live Cursor SDK agent + live Notion publish
# Any arguments are passed straight through to `python -m postmortem_agent`.
set -euo pipefail

ROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
    echo "error: virtualenv missing at .venv" >&2
    echo "run: python3 -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'" >&2
    exit 1
fi

# 1) Produce a fresh incident bundle.
make incident

# 2) Select the most recent bundle.
BUNDLE=$(ls -dt incidents/inc-* 2>/dev/null | head -1 || true)
if [ -z "$BUNDLE" ]; then
    echo "error: no incident bundle was produced under incidents/" >&2
    exit 1
fi
echo "Using bundle: $BUNDLE"

# 3) Run the postmortem workflow. Default to the fully offline path.
if [ "$#" -eq 0 ]; then
    set -- --mock-agent --dry-run
fi

# Remediation may check out a postmortem/<id> branch; return to the starting
# branch afterward so the demo leaves the repo where it began.
START_REF=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
"$PY" -m postmortem_agent --bundle "$BUNDLE" "$@"
if [ -n "$START_REF" ] && [ "$START_REF" != "HEAD" ]; then
    git checkout "$START_REF" >/dev/null 2>&1 || true
fi
