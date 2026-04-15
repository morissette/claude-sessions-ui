#!/usr/bin/env bash
# Dev mode: hot-reload frontend + backend
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "⬡  Claude Sessions UI — dev mode"
echo ""

if [ ! -d frontend/node_modules ]; then
  echo "→ Installing frontend dependencies..."
  (cd frontend && npm install)
fi

# Start backend in background
echo "→ Backend  → http://localhost:8765"
echo "→ Frontend → http://localhost:5173"
echo ""

python3 -m uvicorn backend.app:app --host 127.0.0.1 --port 8765 --reload &
BACKEND_PID=$!

(cd frontend && npm run dev) &
FRONTEND_PID=$!

cleanup() {
  kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
  exit 0
}
trap cleanup INT TERM

wait
