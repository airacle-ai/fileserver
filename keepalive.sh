#!/bin/bash
# fileserver keepalive — start the file server if it's not already running on port 41011.
# Safe to call repeatedly (idempotent). Run from cron, .bashrc, or by hand.

set -euo pipefail

PORT=41011
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Storage lives on sensei-fs (persists across pod restarts).
# If the sensei-fs (Lustre) shared quota fills up and uploads start 500ing with
# "Disk quota exceeded", switch to localssd by exporting before launch:
#   FILESERVER_DATA_DIR=/mnt/localssd/fileserver_data ./keepalive.sh
# (localssd is fast + quota-free, but wiped on pod restart.)
export FILESERVER_DATA_DIR="${FILESERVER_DATA_DIR:-$DIR/data}"
export FILESERVER_CHUNK_DIR="${FILESERVER_CHUNK_DIR:-$DIR/.upload_chunks}"
# Logs go to localssd regardless — if the quota is full, even writing the log
# fails and the server can't start.
LOG_DIR="/mnt/localssd/fileserver_logs"
mkdir -p "$FILESERVER_DATA_DIR" "$LOG_DIR"
LOG="$LOG_DIR/server.log"
PIDFILE="$LOG_DIR/server.pid"

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
