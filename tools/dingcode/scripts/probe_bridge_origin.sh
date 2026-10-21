#!/bin/sh
# External Origin must not receive the bridge session token.
# Usage: scripts/probe_bridge_origin.sh [port]
set -eu
cd "$(dirname "$0")/.."
port="${1:-18763}"
log="${TMPDIR:-/tmp}/dingcode-bridge-probe.log"
python3 -m core.bridge --port "$port" >"$log" 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true' EXIT
ready=0
i=0
while [ "$i" -lt 50 ]; do
  if curl -sf -o /dev/null "http://127.0.0.1:$port/ping"; then
    ready=1
    break
  fi
  i=$((i + 1))
  sleep 0.05
done
if [ "$ready" != 1 ]; then
  echo "bridge did not start" >&2
  cat "$log" >&2 || true
  exit 1
fi
hdr=$(mktemp)
body=$(mktemp)
code=$(curl -sS -D "$hdr" -o "$body" -w "%{http_code}" -H 'Origin: https://evil.example' "http://127.0.0.1:$port/ping")
if [ "$code" != "403" ]; then
  echo "expected 403, got $code" >&2
  cat "$hdr" "$body" >&2
  exit 1
fi
if grep -q 'token' "$body"; then
  echo "token leaked in body" >&2
  cat "$body" >&2
  exit 1
fi
if grep -i 'access-control-allow-origin' "$hdr" >/dev/null; then
  echo "denied origin was echoed" >&2
  cat "$hdr" >&2
  exit 1
fi
if grep -i 'access-control-allow-private-network' "$hdr" >/dev/null; then
  echo "private-network header sent to a denied origin" >&2
  cat "$hdr" >&2
  exit 1
fi
echo "probe ok"
