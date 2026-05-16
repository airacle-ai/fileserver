#!/bin/bash
# fileserver keepalive — start the file server if it's not already running on port 41011.
# Safe to call repeatedly (idempotent). Run from cron, .bashrc, or by hand.

set -euo pipefail

PORT=41011
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$DIR/server.log"
PIDFILE="$DIR/server.pid"

is_running() {
  # Prefer pidfile check, fall back to port scan
  if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    return 0
  fi
  # netstat fallback (works without /proc walk)
  if command -v ss >/dev/null 2>&1; then
    ss -tlnp 2>/dev/null | grep -q ":$PORT "
  else
    netstat -tlnp 2>/dev/null | grep -q ":$PORT "
  fi
}

if is_running; then
  echo "[keepalive] fileserver already running on :$PORT"
  exit 0
fi

echo "[keepalive] starting fileserver on :$PORT  ($(date -Is))"
cd "$DIR"
nohup python3 app.py "$PORT" >> "$LOG" 2>&1 &
echo $! > "$PIDFILE"
sleep 1
echo "[keepalive] PID $(cat "$PIDFILE") — log: $LOG"
