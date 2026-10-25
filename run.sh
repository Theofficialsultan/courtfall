#!/usr/bin/env bash
# Start the API and the Vite app. Streamlit remains: .venv/bin/streamlit run app.py
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if ! lsof -ti tcp:8000 >/dev/null 2>&1; then
  .venv/bin/uvicorn backend.api:app --reload --port 8000 &
  API_PID=$!
  trap 'kill "$API_PID" 2>/dev/null || true' EXIT
else
  echo "API already listening on port 8000"
fi

cd "$ROOT/frontend"
npm run dev -- --host 127.0.0.1 --port 5173
