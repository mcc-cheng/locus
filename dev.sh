#!/usr/bin/env bash
# Run Locus locally for development: backend (port 8000) + frontend (port 5173).
# Usage:  ./dev.sh    then open http://localhost:5173 . Ctrl-C stops both.
set -euo pipefail
cd "$(dirname "$0")"

PORT=8000
DATA="${LOCUS_DATA:-./data}"
# Which local Ollama model the analyst uses (override: LOCUS_AGENT_MODEL=… ./dev.sh).
export LOCUS_AGENT_MODEL="${LOCUS_AGENT_MODEL:-gemma4}"
echo "▶ analyst model: $LOCUS_AGENT_MODEL"

# Free the port if a previous run is lingering.
lsof -ti tcp:$PORT 2>/dev/null | xargs kill 2>/dev/null || true

echo "▶ starting Locus engine on http://127.0.0.1:$PORT  (data: $DATA)"
LOCUS_PORT=$PORT LOCUS_DATA="$DATA" .venv/bin/python -m api.sidecar &
BACKEND=$!

cleanup() { echo; echo "stopping…"; kill "$BACKEND" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# Wait until the engine answers before starting the UI.
for _ in $(seq 1 40); do
  if curl -s --max-time 1 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "✓ engine is up"
    break
  fi
  sleep 0.5
done

echo "▶ starting UI — open http://localhost:5173"
npm --prefix frontend run dev
