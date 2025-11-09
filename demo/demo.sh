#!/usr/bin/env bash
set -eu

# This script works no matter where you run it from.
# It finds the script directory and runs queuectl.py from the project root.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Project root: $ROOT_DIR"
echo "Cleaning old DB..."
rm -f "$ROOT_DIR/queue.db" || true

echo "Enqueue success job"
python3 "$ROOT_DIR/queuectl.py" enqueue '{"id":"job-ok","command":"echo Hello from job-ok"}'

echo "Enqueue failing job"
python3 "$ROOT_DIR/queuectl.py" enqueue '{"id":"job-bad","command":"no_such_cmd","max_retries":2,"base_backoff":2}'

echo "Start one worker in background (nohup) and save output to demo/worker.out"
mkdir -p "$SCRIPT_DIR"
nohup python3 "$ROOT_DIR/queuectl.py" worker start --count 1 > "$SCRIPT_DIR/worker.out" 2>&1 &

sleep 1

echo "Wait 6 seconds for processing..."
sleep 6

echo
echo "=== STATUS ==="
python3 "$ROOT_DIR/queuectl.py" status || true

echo
echo "=== PENDING ==="
python3 "$ROOT_DIR/queuectl.py" list --state pending || true

echo
echo "=== DLQ (dead jobs) ==="
python3 "$ROOT_DIR/queuectl.py" dlq list || true

echo
echo "Stopping background worker processes (pkill python)..."
pkill -f "python3 $ROOT_DIR/queuectl.py worker start" || pkill -f "python $ROOT_DIR/queuectl.py worker start" || true

echo "Done"

