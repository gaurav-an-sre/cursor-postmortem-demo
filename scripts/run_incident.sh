#!/bin/sh
set -eu

ROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
PYTHON="$ROOT/.venv/bin/python"
PORT=${CHECKOUT_PORT:-8000}
SERVICE_PID=
LOADGEN_PID=
WATCHDOG_PID=

cleanup() {
    set +e
    [ -n "$WATCHDOG_PID" ] && kill "$WATCHDOG_PID" 2>/dev/null
    [ -n "$LOADGEN_PID" ] && kill "$LOADGEN_PID" 2>/dev/null
    [ -n "$SERVICE_PID" ] && kill "$SERVICE_PID" 2>/dev/null
    wait 2>/dev/null
}
trap cleanup EXIT INT TERM

cd "$ROOT"
mkdir -p var incidents
rm -f var/orders.db var/app.log var/metrics.csv

CHECKOUT_DATA_DIR="$ROOT/var" "$PYTHON" -m uvicorn checkout_svc.app:app --host 127.0.0.1 --port "$PORT" >var/service.stdout.log 2>&1 &
SERVICE_PID=$!
"$PYTHON" -c "import time, urllib.request; deadline=time.time()+10
while time.time() < deadline:
    try:
        urllib.request.urlopen('http://127.0.0.1:$PORT/healthz', timeout=1)
        break
    except Exception:
        time.sleep(.2)
else:
    raise SystemExit('service did not start')" 

# BSD date has no %N, so take the sub-second load start time from Python.
LOAD_STARTED_AT=$("$PYTHON" -c "import time; print(time.time())")
"$PYTHON" tools/loadgen.py --url "http://127.0.0.1:$PORT/checkout" --rps "${INCIDENT_RPS:-20}" \
    --duration "${INCIDENT_DURATION:-80}" --output var/metrics.csv &
LOADGEN_PID=$!
"$PYTHON" tools/watchdog.py --metrics var/metrics.csv --log var/app.log --bundle-root incidents \
    --repo "$ROOT" --service-pid "$SERVICE_PID" \
    --deploy-path checkout_svc \
    --restart-command "env CHECKOUT_DATA_DIR=$ROOT/var $ROOT/.venv/bin/python -m uvicorn checkout_svc.app:app --host 127.0.0.1 --port $PORT" \
    --health-url "http://127.0.0.1:$PORT/healthz" --load-started-at "$LOAD_STARTED_AT" &
WATCHDOG_PID=$!

if ! wait "$WATCHDOG_PID"; then
    echo "watchdog failed to fire an alert" >&2
    exit 1
fi
WATCHDOG_PID=
kill "$LOADGEN_PID" 2>/dev/null || true
wait "$LOADGEN_PID" 2>/dev/null || true
LOADGEN_PID=
LATEST_BUNDLE=$("$PYTHON" -c "from pathlib import Path
root = Path('incidents')
bundles = [path for path in root.iterdir() if path.is_dir() and path.name.startswith('inc-')]
print(max(bundles, key=lambda path: path.stat().st_mtime) if bundles else '')")
printf 'Incident bundle: %s\n' "$LATEST_BUNDLE"
